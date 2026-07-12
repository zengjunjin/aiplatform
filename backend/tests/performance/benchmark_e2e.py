"""端到端 RAG 管线基准测试脚本。

测试完整 RAG 管线延迟、流式生成 TTFT 和 Token 速率。

使用方法:
    python benchmark_e2e.py --kb-id 1
    python benchmark_e2e.py --kb-id 1 --concurrent 5 --duration 30 --output e2e_report.json
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx

# 确保 backend 目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

DEFAULT_DATASET = Path(__file__).resolve().parent / "datasets" / "small.json"


def load_dataset(dataset_path: str) -> dict:
    path = Path(dataset_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / dataset_path
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p / 100.0
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_values):
        return sorted_values[f] + c * (sorted_values[f + 1] - sorted_values[f])
    return sorted_values[f]


async def authenticate(base_url: str, username: str, password: str) -> str | None:
    """注册并登录，返回 access_token。"""
    email = f"{username}@benchmark.test"
    async with httpx.AsyncClient(base_url=base_url) as client:
        await client.post(
            "/api/v1/auth/register",
            json={"username": username, "email": email, "password": password},
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        if resp.status_code == 200:
            return resp.json()["data"]["access_token"]
    return None


async def create_session(base_url: str, token: str, kb_id: int | None) -> int | None:
    """创建聊天会话，返回 session_id。"""
    async with httpx.AsyncClient(base_url=base_url) as client:
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.post(
            "/api/v1/chat/sessions",
            json={"title": "Benchmark Session", "kb_id": kb_id},
            headers=headers,
        )
        if resp.status_code == 200:
            return resp.json()["data"]["id"]
    return None


async def send_message_stream(
    base_url: str,
    token: str,
    session_id: int,
    question: str,
) -> dict:
    """发送消息并收集流式响应指标。

    Returns:
        dict with keys: e2e_latency, ttft, token_count, total_tokens_time, tokens_per_second, error
    """
    headers = {"Authorization": f"Bearer {token}"}
    result = {
        "e2e_latency": 0.0,
        "ttft": 0.0,
        "token_count": 0,
        "total_tokens_time": 0.0,
        "tokens_per_second": 0.0,
        "error": None,
    }

    start_time = time.perf_counter()
    first_token_time = None
    first_token_recorded = False

    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"/api/v1/chat/sessions/{session_id}/messages",
                json={"content": question},
                headers=headers,
            ) as response:
                if response.status_code != 200:
                    result["error"] = f"HTTP {response.status_code}"
                    result["e2e_latency"] = time.perf_counter() - start_time
                    return result

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue

                    data_str = line[6:]  # strip "data: "
                    if data_str == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    event = data.get("event", "")

                    if event == "delta" and not first_token_recorded:
                        first_token_time = time.perf_counter()
                        first_token_recorded = True

                    if event == "delta":
                        result["token_count"] += 1

    except Exception as e:
        result["error"] = str(e)

    end_time = time.perf_counter()
    result["e2e_latency"] = end_time - start_time

    if first_token_time:
        result["ttft"] = first_token_time - start_time
        if result["token_count"] > 0:
            result["total_tokens_time"] = end_time - first_token_time
            result["tokens_per_second"] = result["token_count"] / max(result["total_tokens_time"], 0.001)

    return result


async def run_e2e_benchmark(
    base_url: str,
    kb_id: int,
    username: str,
    password: str,
    dataset_path: str,
    output: str | None = None,
) -> dict:
    """运行端到端基准测试。

    Args:
        base_url: API 基础 URL
        kb_id: 知识库 ID
        username: 测试用户名
        password: 测试密码
        dataset_path: 数据集 JSON 文件路径
        output: 输出 JSON 报告文件路径
    """
    dataset = load_dataset(dataset_path)
    questions = dataset.get("questions", [])
    metadata = dataset.get("metadata", {})

    if not questions:
        print("错误: 数据集中没有问题", file=sys.stderr)
        sys.exit(1)

    # 认证
    print("正在认证...")
    token = await authenticate(base_url, username, password)
    if not token:
        print("错误: 认证失败", file=sys.stderr)
        sys.exit(1)

    # 创建会话
    session_id = await create_session(base_url, token, kb_id)
    if not session_id:
        print("错误: 创建会话失败", file=sys.stderr)
        sys.exit(1)
    print(f"会话已创建: session_id={session_id}")

    e2e_latencies: list[float] = []
    ttfts: list[float] = []
    tps_values: list[float] = []
    results: list[dict] = []
    errors: list[dict] = []

    print(f"开始端到端基准测试: kb_id={kb_id}, 数据集={metadata.get('name', 'unknown')}, 问题数={len(questions)}")
    print("-" * 60)

    for i, q in enumerate(questions):
        question = q["question"]
        print(f"[{i + 1}/{len(questions)}] {question[:60]}...")

        r = await send_message_stream(base_url, token, session_id, question)

        if r["error"]:
            print(f"    错误: {r['error']}")
            errors.append({
                "index": i,
                "question": question,
                "error": r["error"],
            })
        else:
            e2e_latencies.append(r["e2e_latency"])
            if r["ttft"] > 0:
                ttfts.append(r["ttft"])
            if r["tokens_per_second"] > 0:
                tps_values.append(r["tokens_per_second"])

            result_entry = {
                "index": i,
                "question": question,
                "difficulty": q.get("difficulty"),
                "question_type": q.get("question_type"),
                "e2e_latency_seconds": round(r["e2e_latency"], 4),
                "ttft_seconds": round(r["ttft"], 4),
                "token_count": r["token_count"],
                "tokens_per_second": round(r["tokens_per_second"], 2),
            }
            results.append(result_entry)
            print(f"    E2E: {r['e2e_latency']:.4f}s, TTFT: {r['ttft']:.4f}s, "
                  f"Tokens: {r['token_count']}, TPS: {r['tokens_per_second']:.2f}")

        # 每个问题之间短暂间隔
        await asyncio.sleep(1)

    sorted_e2e = sorted(e2e_latencies)
    sorted_ttft = sorted(ttfts)
    sorted_tps = sorted(tps_values)

    report = {
        "benchmark": "e2e",
        "base_url": base_url,
        "dataset": metadata,
        "kb_id": kb_id,
        "session_id": session_id,
        "total_questions": len(questions),
        "successful": len(e2e_latencies),
        "errors": len(errors),
        "e2e_latency_stats": {
            "min": round(sorted_e2e[0], 4) if sorted_e2e else 0,
            "max": round(sorted_e2e[-1], 4) if sorted_e2e else 0,
            "mean": round(sum(e2e_latencies) / len(e2e_latencies), 4) if e2e_latencies else 0,
            "p50": round(percentile(sorted_e2e, 50), 4),
            "p95": round(percentile(sorted_e2e, 95), 4),
            "p99": round(percentile(sorted_e2e, 99), 4),
        },
        "ttft_stats": {
            "min": round(sorted_ttft[0], 4) if sorted_ttft else 0,
            "max": round(sorted_ttft[-1], 4) if sorted_ttft else 0,
            "mean": round(sum(ttfts) / len(ttfts), 4) if ttfts else 0,
            "p50": round(percentile(sorted_ttft, 50), 4),
            "p95": round(percentile(sorted_ttft, 95), 4),
            "p99": round(percentile(sorted_ttft, 99), 4),
        },
        "tokens_per_second_stats": {
            "min": round(sorted_tps[0], 2) if sorted_tps else 0,
            "max": round(sorted_tps[-1], 2) if sorted_tps else 0,
            "mean": round(sum(tps_values) / len(tps_values), 2) if tps_values else 0,
            "p50": round(percentile(sorted_tps, 50), 2),
            "p95": round(percentile(sorted_tps, 95), 2),
            "p99": round(percentile(sorted_tps, 99), 2),
        },
        "results": results,
        "errors": errors,
    }

    print("-" * 60)
    print("端到端基准测试完成")
    print(f"  成功: {len(e2e_latencies)}, 失败: {len(errors)}")
    print(f"  E2E 延迟 (秒): P50={report['e2e_latency_stats']['p50']}, "
          f"P95={report['e2e_latency_stats']['p95']}, "
          f"P99={report['e2e_latency_stats']['p99']}")
    print(f"  TTFT (秒): P50={report['ttft_stats']['p50']}, "
          f"P95={report['ttft_stats']['p95']}")
    print(f"  TPS: mean={report['tokens_per_second_stats']['mean']}")

    if output:
        output_path = Path(output)
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"报告已保存到: {output_path}")

    return report


def main():
    parser = argparse.ArgumentParser(description="RAG 端到端管线基准测试")
    parser.add_argument("--kb-id", type=int, required=True, help="知识库 ID")
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:8000",
        help="API 基础 URL (默认: http://localhost:8000)",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="datasets/small.json",
        help="数据集 JSON 文件路径 (默认: datasets/small.json)",
    )
    parser.add_argument("--username", type=str, default="benchmark_user", help="测试用户名")
    parser.add_argument("--password", type=str, default="Benchmark@123", help="测试密码")
    parser.add_argument("--output", type=str, default=None, help="输出 JSON 报告文件路径")
    args = parser.parse_args()

    asyncio.run(run_e2e_benchmark(
        base_url=args.base_url,
        kb_id=args.kb_id,
        username=args.username,
        password=args.password,
        dataset_path=args.dataset,
        output=args.output,
    ))


if __name__ == "__main__":
    main()