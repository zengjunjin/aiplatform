/**
 * 反馈类型 → i18n key 映射。
 * Task 35: 从 FeedbackFilterBar / FeedbackTypeChart / LowRatedTable 三处内联定义抽到统一常量。
 * 注意：值为 i18n key（如 chat.feedbackType.notAccurate），使用方需通过 t() 翻译，而非直接展示。
 */
export const FEEDBACK_TYPE_LABELS: Record<string, string> = {
  faithfulness_issue: 'chat.feedbackType.faithfulnessIssue',
  context_insufficient: 'chat.feedbackType.contextInsufficient',
  incompleteness: 'chat.feedbackType.incompleteness',
  irrelevance: 'chat.feedbackType.irrelevance',
  verbosity: 'chat.feedbackType.verbosity',
  other: 'chat.feedbackType.other',
};
