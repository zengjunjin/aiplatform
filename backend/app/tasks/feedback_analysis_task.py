"""
反馈分析定时任务

每周日凌晨 3 点执行，汇总过去一周的反馈数据，生成 Markdown 分析报告。
"""

import os
from datetime import UTC, datetime, timedelta

from loguru import logger

from app.config import settings
from app.core.prompt_optimizer import generate_optimization_suggestions
from app.database import async_session
from app.services.feedback_service import analyze_feedback
from app.tasks.celery_app import celery_app


def _get_report_dir() -> str:
    """获取反馈报告目录路径。

    Task 61: 每次调用时动态读取 settings.STORAGE_DIR，
    避免模块级常量在 import 时固定路径（影响测试中动态修改 settings）。
    """
    if settings.STORAGE_DIR:
        return os.path.join(settings.STORAGE_DIR, "feedback_reports")
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "feedback_reports",
    )


def _write_report(path: str, content: str) -> None:
    """同步写入报告文件（供 asyncio.to_thread 调用）"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


@celery_app.task(
    name="app.tasks.feedback_analysis_task.run_feedback_analysis",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def run_feedback_analysis(self) -> dict:
    """每周汇总反馈数据并生成分析报告"""
    import asyncio

    report_dir = _get_report_dir()

    # === 幂等性检查 (Task 6) ===
    # 如果最近 6 小时内已生成过报告，跳过避免重复执行
    # (Celery acks_late 场景下可能重投递；或定时任务因故重复触发)
    cutoff = datetime.now(UTC) - timedelta(hours=6)
    if os.path.exists(report_dir):
        for filename in os.listdir(report_dir):
            if not (filename.startswith("feedback_report_") and filename.endswith(".md")):
                continue
            filepath = os.path.join(report_dir, filename)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath), tz=UTC)
                if mtime > cutoff:
                    logger.info(f"Recent report exists: {filepath}, skipping (idempotent)")
                    return {"status": "skipped", "reason": "recent_report_exists"}
            except OSError as e:
                logger.warning(f"Failed to stat {filepath}: {e}")
                continue
    # === 幂等性检查结束 ===

    async def _run():
        logger.info("Starting weekly feedback analysis task...")

        end_date = datetime.now(UTC)
        start_date = end_date - timedelta(days=7)

        try:
            async with async_session() as db:
                analysis = await analyze_feedback(
                    kb_id=None,
                    start_date=start_date,
                    end_date=end_date,
                    db=db,
                )

                # 生成 Prompt 优化建议
                optimization = await generate_optimization_suggestions(analysis)

                # 生成 Markdown 报告
                report = _generate_markdown_report(analysis, optimization, start_date, end_date)

                # 保存报告
                os.makedirs(report_dir, exist_ok=True)
                report_filename = f"feedback_report_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.md"
                report_path = os.path.join(report_dir, report_filename)

                await asyncio.to_thread(_write_report, report_path, report)

                logger.info(f"Feedback analysis report saved to: {report_path}")

                # 清理旧报告（保留最近 12 周）
                _cleanup_old_reports(keep=settings.FEEDBACK_REPORT_KEEP_COUNT)

                return {
                    "report_path": report_path,
                    "total_feedback": analysis["stats"]["total_feedback"],
                    "negative_rate": analysis["stats"]["negative_rate"],
                    "suggestions_count": len(optimization["suggestions"]),
                }

        except Exception as e:
            logger.error(f"Feedback analysis task failed: {e}")
            raise self.retry(exc=e) from e

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


def _render_overview(analysis: dict, start_date: datetime, end_date: datetime) -> list[str]:
    """渲染报告头部、概览统计与反馈类型分布"""
    stats = analysis.get("stats", {})
    lines = [
        "# 反馈分析报告",
        "",
        f"**分析周期**: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}",
        f"**生成时间**: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "---",
        "",
        "## 概览",
        "",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 总反馈数 | {stats.get('total_feedback', 0)} |",
        f"| 正向率 | {stats.get('positive_rate', 0):.1%} |",
        f"| 负向率 | {stats.get('negative_rate', 0):.1%} |",
        "",
        "### 反馈类型分布",
        "",
    ]

    by_type = stats.get("by_type", {})
    if by_type:
        lines.append("| 类型 | 数量 |")
        lines.append("|------|------|")
        for type_name, count in sorted(by_type.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"| {type_name} | {count} |")
        lines.append("")
    else:
        lines.append("本周无负反馈记录。")
        lines.append("")

    return lines


def _render_failure_patterns(analysis: dict) -> list[str]:
    """渲染失败模式分析段落"""
    patterns = analysis.get("failure_patterns", {})
    return [
        "---",
        "",
        "## 失败模式分析",
        "",
        "| 模式 | 数量 |",
        "|------|------|",
        f"| 上下文覆盖不足 | {patterns.get('context_insufficient', 0)} |",
        f"| 检索偏差 | {patterns.get('retrieval_bias', 0)} |",
        f"| 忠实度问题（幻觉） | {patterns.get('faithfulness_issue', 0)} |",
        f"| 完整性不足 | {patterns.get('incompleteness', 0)} |",
        f"| 不相关 | {patterns.get('irrelevance', 0)} |",
        f"| 冗长/简短 | {patterns.get('verbosity', 0)} |",
        "",
    ]


def _render_suggestions(analysis: dict) -> list[str]:
    """渲染优化建议段落（基于 analysis 中的 suggestions）"""
    suggestions = analysis.get("suggestions", [])
    lines = [
        "---",
        "",
        "## 优化建议",
        "",
    ]
    if suggestions:
        for i, s in enumerate(suggestions, 1):
            lines.append(f"{i}. {s}")
        lines.append("")
    else:
        lines.append("本周无优化建议。")
        lines.append("")
    return lines


def _render_prompt_constraints(optimization: dict) -> list[str]:
    """渲染 Prompt 约束建议段落"""
    prompt_constraints = optimization.get("prompt_constraints", [])
    lines = [
        "### Prompt 约束建议",
        "",
    ]
    if prompt_constraints:
        for i, c in enumerate(prompt_constraints, 1):
            lines.append(f"{i}. {c}")
        lines.append("")
    else:
        lines.append("无新的 Prompt 约束建议。")
        lines.append("")
    return lines


def _render_optimization_rules(optimization: dict) -> list[str]:
    """渲染优化规则表格段落（仅有数据时输出）"""
    opt_suggestions = optimization.get("suggestions", [])
    lines = []
    if opt_suggestions:
        lines.append("### 优化规则")
        lines.append("")
        lines.append("| 规则 | 原因 | 严重程度 |")
        lines.append("|------|------|----------|")
        for s in opt_suggestions:
            lines.append(f"| {s['rule']} | {s['reason']} | {s['severity']} |")
        lines.append("")
    return lines


def _render_low_rated_samples(analysis: dict) -> list[str]:
    """渲染低分样本段落"""
    samples = analysis.get("low_rated_samples", [])
    lines = [
        "---",
        "",
        "## 低分样本（Top 5）",
        "",
    ]
    if samples:
        for i, sample in enumerate(samples, 1):
            lines.append(f"### 样本 {i}")
            lines.append("")
            lines.append(f"- **问题**: {sample.get('question', 'N/A')[:300]}")
            lines.append(f"- **回答**: {sample.get('answer', 'N/A')[:300]}")
            lines.append(f"- **反馈类型**: {sample.get('feedback_type', 'N/A')}")
            if sample.get("comment"):
                lines.append(f"- **用户评价**: {sample['comment']}")
            lines.append("")
    else:
        lines.append("本周无低分样本。")
        lines.append("")
    return lines


def _render_summary(optimization: dict) -> list[str]:
    """渲染总结段落（基于 optimization 中的 summary）"""
    summary = optimization.get("summary", "")
    return [
        "---",
        "",
        "## 总结",
        "",
        f"{summary}",
        "",
        "*本报告由系统自动生成。*",
    ]


def _generate_markdown_report(
    analysis: dict,
    optimization: dict,
    start_date: datetime,
    end_date: datetime,
) -> str:
    """生成 Markdown 格式的分析报告"""
    lines = []
    lines.extend(_render_overview(analysis, start_date, end_date))
    lines.extend(_render_failure_patterns(analysis))
    lines.extend(_render_suggestions(analysis))
    lines.extend(_render_prompt_constraints(optimization))
    lines.extend(_render_optimization_rules(optimization))
    lines.extend(_render_low_rated_samples(analysis))
    lines.extend(_render_summary(optimization))
    return "\n".join(lines)


def _cleanup_old_reports(keep: int = 12) -> None:
    """清理旧报告，只保留最近 N 个"""
    report_dir = _get_report_dir()
    try:
        if not os.path.exists(report_dir):
            return
        files = sorted(
            [
                f
                for f in os.listdir(report_dir)
                if f.startswith("feedback_report_") and f.endswith(".md")
            ],
            reverse=True,
        )
        for old_file in files[keep:]:
            os.remove(os.path.join(report_dir, old_file))
            logger.info(f"Cleaned up old report: {old_file}")
    except Exception as e:
        logger.warning(f"Failed to cleanup old reports: {e}")
