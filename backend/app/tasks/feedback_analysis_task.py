"""
反馈分析定时任务

每周日凌晨 3 点执行，汇总过去一周的反馈数据，生成 Markdown 分析报告。
"""
import os
from datetime import datetime, timedelta, timezone
from loguru import logger
from app.tasks.celery_app import celery_app
from app.database import async_session
from app.services.feedback_service import analyze_feedback
from app.core.prompt_optimizer import generate_optimization_suggestions


REPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "feedback_reports")


@celery_app.task(
    name="app.tasks.feedback_analysis_task.run_feedback_analysis",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def run_feedback_analysis(self):
    """每周汇总反馈数据并生成分析报告"""
    import asyncio

    async def _run():
        logger.info("Starting weekly feedback analysis task...")

        end_date = datetime.now(timezone.utc)
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
                report = _generate_markdown_report(
                    analysis, optimization, start_date, end_date
                )

                # 保存报告
                os.makedirs(REPORT_DIR, exist_ok=True)
                report_filename = f"feedback_report_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.md"
                report_path = os.path.join(REPORT_DIR, report_filename)

                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(report)

                logger.info(f"Feedback analysis report saved to: {report_path}")

                # 清理旧报告（保留最近 12 周）
                _cleanup_old_reports(keep=12)

                return {
                    "report_path": report_path,
                    "total_feedback": analysis["stats"]["total_feedback"],
                    "negative_rate": analysis["stats"]["negative_rate"],
                    "suggestions_count": len(optimization["suggestions"]),
                }

        except Exception as e:
            logger.error(f"Feedback analysis task failed: {e}")
            raise self.retry(exc=e)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


def _generate_markdown_report(
    analysis: dict,
    optimization: dict,
    start_date: datetime,
    end_date: datetime,
) -> str:
    """生成 Markdown 格式的分析报告"""
    stats = analysis.get("stats", {})
    patterns = analysis.get("failure_patterns", {})
    suggestions = analysis.get("suggestions", [])
    samples = analysis.get("low_rated_samples", [])
    opt_suggestions = optimization.get("suggestions", [])
    prompt_constraints = optimization.get("prompt_constraints", [])
    summary = optimization.get("summary", "")

    lines = [
        f"# 反馈分析报告",
        f"",
        f"**分析周期**: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}",
        f"**生成时间**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"",
        f"---",
        f"",
        f"## 概览",
        f"",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| 总反馈数 | {stats.get('total_feedback', 0)} |",
        f"| 正向率 | {stats.get('positive_rate', 0):.1%} |",
        f"| 负向率 | {stats.get('negative_rate', 0):.1%} |",
        f"",
        f"### 反馈类型分布",
        f"",
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

    lines.extend([
        f"---",
        f"",
        f"## 失败模式分析",
        f"",
        f"| 模式 | 数量 |",
        f"|------|------|",
        f"| 上下文覆盖不足 | {patterns.get('context_insufficient', 0)} |",
        f"| 检索偏差 | {patterns.get('retrieval_bias', 0)} |",
        f"| 忠实度问题（幻觉） | {patterns.get('faithfulness_issue', 0)} |",
        f"| 完整性不足 | {patterns.get('incompleteness', 0)} |",
        f"| 不相关 | {patterns.get('irrelevance', 0)} |",
        f"| 冗长/简短 | {patterns.get('verbosity', 0)} |",
        f"",
        f"---",
        f"",
        f"## 优化建议",
        f"",
    ])

    if suggestions:
        for i, s in enumerate(suggestions, 1):
            lines.append(f"{i}. {s}")
        lines.append("")
    else:
        lines.append("本周无优化建议。")
        lines.append("")

    lines.extend([
        f"### Prompt 约束建议",
        f"",
    ])

    if prompt_constraints:
        for i, c in enumerate(prompt_constraints, 1):
            lines.append(f"{i}. {c}")
        lines.append("")
    else:
        lines.append("无新的 Prompt 约束建议。")
        lines.append("")

    if opt_suggestions:
        lines.append("### 优化规则")
        lines.append("")
        lines.append("| 规则 | 原因 | 严重程度 |")
        lines.append("|------|------|----------|")
        for s in opt_suggestions:
            lines.append(f"| {s['rule']} | {s['reason']} | {s['severity']} |")
        lines.append("")

    lines.extend([
        f"---",
        f"",
        f"## 低分样本（Top 5）",
        f"",
    ])

    if samples:
        for i, sample in enumerate(samples, 1):
            lines.append(f"### 样本 {i}")
            lines.append(f"")
            lines.append(f"- **问题**: {sample.get('question', 'N/A')[:300]}")
            lines.append(f"- **回答**: {sample.get('answer', 'N/A')[:300]}")
            lines.append(f"- **反馈类型**: {sample.get('feedback_type', 'N/A')}")
            if sample.get('comment'):
                lines.append(f"- **用户评价**: {sample['comment']}")
            lines.append(f"")
    else:
        lines.append("本周无低分样本。")
        lines.append("")

    lines.extend([
        f"---",
        f"",
        f"## 总结",
        f"",
        f"{summary}",
        f"",
        f"*本报告由系统自动生成。*",
    ])

    return "\n".join(lines)


def _cleanup_old_reports(keep: int = 12):
    """清理旧报告，只保留最近 N 个"""
    try:
        if not os.path.exists(REPORT_DIR):
            return
        files = sorted(
            [f for f in os.listdir(REPORT_DIR) if f.startswith("feedback_report_") and f.endswith(".md")],
            reverse=True,
        )
        for old_file in files[keep:]:
            os.remove(os.path.join(REPORT_DIR, old_file))
            logger.info(f"Cleaned up old report: {old_file}")
    except Exception as e:
        logger.warning(f"Failed to cleanup old reports: {e}")