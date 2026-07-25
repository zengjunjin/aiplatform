"""对比基准测试脚本。

对比不同配置下的 RAG 性能：
- 有/无 Rerank 的延迟对比
- 不同分块策略的延迟对比

使用方法:
    python benchmark_compare.py --kb-id 1 --compare rerank
    python benchmark_compare.py --kb-id 1 --compare chunking --output compare_report.json
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# 性能回归基线
BASELINE_FILE = Path(__file__).parent / "baseline.json"


def load_baseline() -> dict:
    """加载性能基线阈值。"""
    if BASELINE_FILE.exists():
        return json.loads(BASELINE_FILE.read_text())
    return {}


def assert_within_baseline(metric_name: str, actual_ms: float):
    """断言指标在基线 20% 容差范围内，否则触发回归告警。"""
    baseline = load_baseline()
    if metric_name in baseline:
        threshold = baseline[metric_name] * 1.2  # 允许 20% 退化
        assert (
            actual_ms <= threshold
        ), f"{metric_name}: {actual_ms}ms exceeds baseline {baseline[metric_name]}ms by >20%"


DEFAULT_DATASET = Path(__file__).resolve().parent / "datasets" / "small.json"


def load_dataset(dataset_path: str) -> dict:
    path = Path(dataset_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / dataset_path
    with open(path, encoding="utf-8") as f:
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


def compute_stats(values: list[float]) -> dict:
    if not values:
        return {"min": 0, "max": 0, "mean": 0, "p50": 0, "p95": 0, "p99": 0}
    s = sorted(values)
    return {
        "min": round(s[0], 4),
        "max": round(s[-1], 4),
        "mean": round(sum(s) / len(s), 4),
        "p50": round(percentile(s, 50), 4),
        "p95": round(percentile(s, 95), 4),
        "p99": round(percentile(s, 99), 4),
    }


async def retrieve_without_rerank(query: str, kb_id: int) -> tuple[float, list[dict]]:
    """仅检索，不经过 Rerank。"""
    from app.rag.retriever import retriever

    start = time.perf_counter()
    chunks = await retriever.retrieve(query, kb_id, top_k=10)
    elapsed = time.perf_counter() - start
    return elapsed, chunks


async def retrieve_with_rerank(query: str, kb_id: int) -> tuple[float, list[dict]]:
    """检索 + Rerank。"""
    from app.rag.reranker import reranker
    from app.rag.retriever import retriever

    start = time.perf_counter()
    chunks = await retriever.retrieve(query, kb_id, top_k=10)
    if chunks:
        try:
            chunks = await reranker.rerank(query, chunks, top_k=5)
        except Exception:
            chunks = chunks[:5]
    elapsed = time.perf_counter() - start
    return elapsed, chunks


async def run_rerank_comparison(kb_id: int, dataset_path: str, output: str | None = None) -> dict:
    """对比有/无 Rerank 的延迟差异。"""
    dataset = load_dataset(dataset_path)
    questions = dataset.get("questions", [])
    metadata = dataset.get("metadata", {})

    without_latencies: list[float] = []
    with_latencies: list[float] = []
    results: list[dict] = []
    errors: list[dict] = []

    print(
        f"Rerank 对比测试: kb_id={kb_id}, 数据集={metadata.get('name', 'unknown')}, 问题数={len(questions)}"
    )
    print("-" * 60)

    for i, q in enumerate(questions):
        question = q["question"]
        print(f"[{i + 1}/{len(questions)}] {question[:60]}...")

        try:
            # 无 Rerank
            wo_latency, wo_chunks = await retrieve_without_rerank(question, kb_id)
            without_latencies.append(wo_latency)

            # 有 Rerank
            w_latency, w_chunks = await retrieve_with_rerank(question, kb_id)
            with_latencies.append(w_latency)

            entry = {
                "index": i,
                "question": question,
                "difficulty": q.get("difficulty"),
                "question_type": q.get("question_type"),
                "without_rerank": {
                    "latency_seconds": round(wo_latency, 4),
                    "chunks_returned": len(wo_chunks),
                },
                "with_rerank": {
                    "latency_seconds": round(w_latency, 4),
                    "chunks_returned": len(w_chunks),
                },
                "overhead_seconds": round(w_latency - wo_latency, 4),
                "overhead_pct": round((w_latency - wo_latency) / max(wo_latency, 0.001) * 100, 1),
            }
            results.append(entry)
            print(
                f"    无 Rerank: {wo_latency:.4f}s, 有 Rerank: {w_latency:.4f}s, "
                f"开销: {w_latency - wo_latency:.4f}s (+{entry['overhead_pct']}%)"
            )

        except Exception as e:
            print(f"    错误: {e}")
            errors.append({"index": i, "question": question, "error": str(e)})

    report = {
        "benchmark": "compare_rerank",
        "dataset": metadata,
        "kb_id": kb_id,
        "total_questions": len(questions),
        "successful": len(without_latencies),
        "without_rerank_stats": compute_stats(without_latencies),
        "with_rerank_stats": compute_stats(with_latencies),
        "results": results,
        "errors": errors,
    }

    print("-" * 60)
    print("Rerank 对比测试完成")
    print(
        f"  无 Rerank: P50={report['without_rerank_stats']['p50']}s, "
        f"P95={report['without_rerank_stats']['p95']}s"
    )
    print(
        f"  有 Rerank: P50={report['with_rerank_stats']['p50']}s, "
        f"P95={report['with_rerank_stats']['p95']}s"
    )

    # 性能回归断言：无 Rerank 的 P95 延迟应在基线 20% 容差内
    if without_latencies:
        assert_within_baseline(
            "bm25_search_time_ms",
            report["without_rerank_stats"]["p95"] * 1000,
        )

    if output:
        output_path = Path(output) if Path(output).is_absolute() else Path.cwd() / output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"报告已保存到: {output_path}")

    return report


async def run_chunking_comparison(kb_id: int, dataset_path: str, output: str | None = None) -> dict:
    """对比不同 chunk_size 配置的延迟差异。

    注意: 此测试需要重启服务来切换 chunk_size 配置，
    因此这里产生的是模拟报告，展示框架结构。
    实际使用时，需要配合配置切换脚本。
    """
    dataset = load_dataset(dataset_path)
    questions = dataset.get("questions", [])
    metadata = dataset.get("metadata", {})

    from app.config import settings
    from app.rag.retriever import retriever

    current_chunk_size = settings.CHUNK_SIZE
    configs_to_test = [256, 512, 1024]
    # 移除当前配置，避免重复
    configs_to_test = [c for c in configs_to_test if c != current_chunk_size]
    configs_to_test.insert(0, current_chunk_size)

    config_results: dict[int, dict] = {}

    print(f"分块策略对比测试: kb_id={kb_id}, 数据集={metadata.get('name', 'unknown')}")
    print(f"当前 CHUNK_SIZE={current_chunk_size}, 测试配置: {configs_to_test}")
    print("-" * 60)

    for chunk_size in configs_to_test:
        if chunk_size != current_chunk_size:
            print(
                f"注意: chunk_size={chunk_size} 需要重启服务才生效，当前使用 {current_chunk_size}"
            )
            print("  将使用当前配置运行，并在报告中标注期望的 chunk_size")

        config_key = f"chunk_size_{chunk_size}"
        config_latencies: list[float] = []
        config_results_list: list[dict] = []

        for i, q in enumerate(questions):
            question = q["question"]

            try:
                start = time.perf_counter()
                chunks = await retriever.retrieve(question, kb_id, top_k=10)
                elapsed = time.perf_counter() - start

                config_latencies.append(elapsed)
                config_results_list.append(
                    {
                        "index": i,
                        "question": question,
                        "latency_seconds": round(elapsed, 4),
                        "chunks_returned": len(chunks),
                    }
                )

            except Exception as e:
                print(f"    [{config_key}][{i}] 错误: {e}")

            await asyncio.sleep(0.5)

        actual_chunk_size = current_chunk_size if chunk_size != current_chunk_size else chunk_size
        config_results[config_key] = {
            "chunk_size": chunk_size,
            "actual_chunk_size": actual_chunk_size,
            "note": "实际使用当前配置运行" if chunk_size != current_chunk_size else "当前配置",
            "stats": compute_stats(config_latencies),
            "results": config_results_list,
        }

        print(
            f"  chunk_size={chunk_size} (实际={actual_chunk_size}): "
            f"P50={config_results[config_key]['stats']['p50']}s, "
            f"mean={config_results[config_key]['stats']['mean']}s"
        )

    report = {
        "benchmark": "compare_chunking",
        "dataset": metadata,
        "kb_id": kb_id,
        "current_chunk_size": current_chunk_size,
        "configs": list(config_results.values()),
        "note": "不同 chunk_size 需要重启服务才生效，请分别运行并对比报告",
    }

    print("-" * 60)
    print("分块策略对比测试完成")
    print("注意: 不同 chunk_size 需要重启服务并分别运行，请将报告合并对比")

    # 性能回归断言：当前 chunk_size 的 P95 延迟应在基线 20% 容差内
    current_key = f"chunk_size_{current_chunk_size}"
    current_stats = config_results.get(current_key, {}).get("stats", {})
    if current_stats.get("p95", 0) > 0:
        assert_within_baseline("bm25_search_time_ms", current_stats["p95"] * 1000)

    if output:
        output_path = Path(output) if Path(output).is_absolute() else Path.cwd() / output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"报告已保存到: {output_path}")

    return report


def main():
    parser = argparse.ArgumentParser(description="RAG 对比基准测试")
    parser.add_argument("--kb-id", type=int, required=True, help="知识库 ID")
    parser.add_argument(
        "--compare",
        type=str,
        required=True,
        choices=["rerank", "chunking"],
        help="对比维度: rerank (有/无 Rerank), chunking (不同分块策略)",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="datasets/small.json",
        help="数据集 JSON 文件路径 (默认: datasets/small.json)",
    )
    parser.add_argument("--output", type=str, default=None, help="输出 JSON 报告文件路径")
    args = parser.parse_args()

    if args.compare == "rerank":
        asyncio.run(
            run_rerank_comparison(
                kb_id=args.kb_id,
                dataset_path=args.dataset,
                output=args.output,
            )
        )
    elif args.compare == "chunking":
        raise NotImplementedError(
            "chunking 对比需要为每个 chunk_size 重启服务，CLI 直接运行仅产生"
            "模拟报告（使用当前配置），具有误导性。\n"
            "请按以下步骤手动运行：\n"
            "  1. 修改 CHUNK_SIZE 环境变量并重启服务\n"
            "  2. 运行 benchmark_retrieval.py 记录单配置基线\n"
            "  3. 合并多份报告进行对比\n"
            "或直接调用 run_chunking_comparison() 函数（程序化使用）。"
        )


if __name__ == "__main__":
    main()
