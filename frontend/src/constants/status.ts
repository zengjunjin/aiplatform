/**
 * 评估运行状态 → Tag 颜色 + i18n key 映射。
 * Task 57: 从 EvaluationHistoryTable / RunDetailModal 抽出，供两处复用。
 * 注意：labelKey 为 i18n key（如 evaluation.status.pending），使用方需通过 t() 翻译。
 */
export const STATUS_MAP: Record<string, { color: string; labelKey: string }> = {
  pending: { color: 'default', labelKey: 'evaluation.status.pending' },
  running: { color: 'processing', labelKey: 'evaluation.status.running' },
  completed: { color: 'success', labelKey: 'evaluation.status.completed' },
  failed: { color: 'error', labelKey: 'evaluation.status.failed' },
};
