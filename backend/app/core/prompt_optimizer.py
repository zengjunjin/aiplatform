from loguru import logger


async def generate_optimization_suggestions(feedback_data: dict) -> dict:
    """基于反馈数据生成 Prompt 优化建议

    Args:
        feedback_data: analyze_feedback() 返回的分析结果

    Returns:
        {
            "suggestions": [
                {"rule": "...", "reason": "...", "severity": "high/medium/low"}
            ],
            "prompt_constraints": ["...", "..."],
            "summary": "..."
        }
    """
    stats = feedback_data.get("stats", {})
    patterns = feedback_data.get("failure_patterns", {})
    samples = feedback_data.get("low_rated_samples", [])
    suggestions = feedback_data.get("suggestions", [])

    total = stats.get("total_feedback", 0)
    negative_rate = stats.get("negative_rate", 0)

    prompt_constraints = []
    rule_suggestions = []

    # 根据失败模式生成具体约束
    if patterns.get("faithfulness_issue", 0) > 0:
        prompt_constraints.append(
            "回答时严格基于提供的上下文，不要添加任何上下文之外的信息。"
            "如果上下文不足以回答用户问题，请明确说明。"
        )
        rule_suggestions.append(
            {
                "rule": "增强忠实度约束",
                "reason": f"检测到 {patterns['faithfulness_issue']} 条幻觉相关反馈",
                "severity": "high",
            }
        )

    if patterns.get("context_insufficient", 0) > 0:
        prompt_constraints.append(
            "在回答前仔细检查上下文是否覆盖了用户问题的所有方面。"
            "如果某个方面信息不足，请在回答中标注。"
        )
        rule_suggestions.append(
            {
                "rule": "增强上下文覆盖检查",
                "reason": f"检测到 {patterns['context_insufficient']} 条准确性相关反馈",
                "severity": "high",
            }
        )

    if patterns.get("incompleteness", 0) > 0:
        prompt_constraints.append(
            "请全面覆盖上下文中的所有关键信息，不要遗漏重要细节。"
            "回答应结构清晰，按点列出关键信息。"
        )
        rule_suggestions.append(
            {
                "rule": "增强完整性要求",
                "reason": f"检测到 {patterns['incompleteness']} 条完整性相关反馈",
                "severity": "medium",
            }
        )

    if patterns.get("irrelevance", 0) > 0:
        prompt_constraints.append(
            "回答前先判断上下文与用户问题的相关性，只回答与问题直接相关的内容。"
            "不要引入无关信息。"
        )
        rule_suggestions.append(
            {
                "rule": "增强相关性过滤",
                "reason": f"检测到 {patterns['irrelevance']} 条不相关反馈",
                "severity": "medium",
            }
        )

    if patterns.get("verbosity", 0) > 0:
        prompt_constraints.append(
            "根据用户问题的复杂度调整回答长度：简单问题简洁回答，复杂问题详细展开。"
        )
        rule_suggestions.append(
            {
                "rule": "优化回答长度控制",
                "reason": f"检测到 {patterns['verbosity']} 条长度相关反馈",
                "severity": "low",
            }
        )

    # 分析样本以提取更多洞察
    # 修复（v0.4.0）：防止 Prompt 注入 — 截断 + 转义换行符
    sample_insights = []
    for sample in samples:
        if sample.get("comment"):
            # 截断到 200 字符，转义换行符避免注入系统指令
            safe_comment = str(sample["comment"])[:200].replace("\n", "\\n")
            sample_insights.append(f"用户反馈: {safe_comment}")

    summary = f"分析周期内共收到 {total} 条反馈，负向率 {negative_rate:.1%}。"
    if rule_suggestions:
        summary += f" 识别出 {len(rule_suggestions)} 个优化方向。"

    logger.info(f"Prompt optimization: {len(rule_suggestions)} suggestions generated")

    return {
        "suggestions": rule_suggestions,
        "prompt_constraints": prompt_constraints,
        "summary": summary,
        "sample_insights": sample_insights[:5],
        "original_suggestions": suggestions,
    }
