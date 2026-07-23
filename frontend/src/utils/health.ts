/**
 * 组件健康判定工具。
 * Task 58: 从 SystemPage 抽出，供多页面复用。
 */

/** 判定单个组件是否健康（值为 "up" 视为健康） */
export function isHealthy(value: string | undefined): boolean {
  return !!value && value.toLowerCase() === 'up';
}
