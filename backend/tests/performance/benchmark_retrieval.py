"""检索性能基准测试脚本。

加载测试数据集，调用检索 API 获取延迟，计算 P50/P95/P99 分位数。

使用方法:
    python benchmark_retrieval.py --kb-id 1 --dataset datasets/small.json
    python benchmark_retrieval.py --kb-id 1 --dataset datasets/medium.json --output report.json
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# 确保 backend 目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def load_dataset(dataset_path: str) -> dict:
    """加载测试数据集 JSON 文件。"""
    path = Path(dataset_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / dataset_path
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def percentile(sorted_values: list[float], p: float) -> float:
    """计算百分位数（线性插值）。"""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p / 100.0
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_values):
        return sorted_values[f] + c * (sorted_values[f + 1] - sorted_values[f])
    return sorted_values[f]


async def run_retrieval_benchmark(kb_id: int, dataset_path: str, output: str | None = None) -> dict:
    """运行检索基准测试。

    Args:
        kb_id: 知识库 ID
        dataset_path: 数据集 JSON 文件路径
        output: 输出 JSON 报告文件路径（可选）

    Returns:
        包含延迟统计的字典
    """
    from app.rag.retriever import retriever

    dataset = load_dataset(dataset_path)
    questions = dataset.get("questions", [])
    metadata = dataset.get("metadata", {})

    if not questions:
        print("错误: 数据集中没有问题", file=sys.stderr)
        sys.exit(1)

    latencies: list[float] = []
    stage_latencies: dict[str, list[float]] = {
        "total": [],
    }
    results: list[dict] = []
    errors: list[dict] = []

    print(f"开始检索基准测试: kb_id={kb_id}, 数据集={metadata.get('name', 'unknown')}, 问题数={len(questions)}")
    print("-" * 60)

    for i, q in enumerate(questions):
        question = q["question"]
        print(f"[{i + 1}/{len(questions)}] {question[:60]}...")

        try:
            start = time.perf_counter()
            chunks = await retriever.retrieve(question, kb_id, top_k=10)
            elapsed = time.perf_counter() - start

            latencies.append(elapsed)

            result_entry = {
                "index": i,
                "question": question,
                "difficulty": q.get("difficulty"),
                "question_type": q.get("question_type"),
                "latency_seconds": round(elapsed, 4),
                "chunks_returned": len(chunks),
                "top_chunk_scores": [round(c.get("rrf_score", c.get("score", 0)), 4) for c in chunks[:5]],
            }
            results.append(result_entry)
            print(f"    延迟: {elapsed:.4f}s, 返回块数: {len(chunks)}")

        except Exception as e:
            print(f"    错误: {e}")
            errors.append({
                "index": i,
                "question": question,
                "error": str(e),
            })

    sorted_latencies = sorted(latencies)

    report = {
        "benchmark": "retrieval",
        "dataset": metadata,
        "kb_id": kb_id,
        "total_questions": len(questions),
        "successful": len(latencies),
        "errors": len(errors),
        "latency_stats": {
            "min": round(sorted_latencies[0], 4) if sorted_latencies else 0,
            "max": round(sorted_latencies[-1], 4) if sorted_latencies else 0,
            "mean": round(sum(latencies) / len(latencies), 4) if latencies else 0,
            "p50": round(percentile(sorted_latencies, 50), 4),
            "p95": round(percentile(sorted_latencies, 95), 4),
            "p99": round(percentile(sorted_latencies, 99), 4),
        },
        "results": results,
        "errors": errors,
    }

    print("-" * 60)
    print("检索基准测试完成")
    print(f"  成功: {len(latencies)}, 失败: {len(errors)}")
    print(f"  延迟 (秒): min={report['latency_stats']['min']}, "
          f"mean={report['latency_stats']['mean']}, "
          f"max={report['latency_stats']['max']}")
    print(f"  分位数: P50={report['latency_stats']['p50']}, "
          f"P95={report['latency_stats']['p95']}, "
          f"P99={report['latency_stats']['p99']}")

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
    parser = argparse.ArgumentParser(description="RAG 检索性能基准测试")
    parser.add_argument("--kb-id", type=int, required=True, help="知识库 ID")
    parser.add_argument(
        "--dataset",
        type=str,
        default="datasets/small.json",
        help="数据集 JSON 文件路径 (默认: datasets/small.json)",
    )
    parser.add_argument("--output", type=str, default=None, help="输出 JSON 报告文件路径")
    args = parser.parse_args()

    asyncio.run(run_retrieval_benchmark(
        kb_id=args.kb_id,
        dataset_path=args.dataset,
        output=args.output,
    ))


if __name__ == "__main__":
    main()