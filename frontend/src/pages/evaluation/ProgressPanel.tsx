import { useEffect } from 'react';
import { Modal, Progress, Button, Typography } from 'antd';
import { useTranslation } from 'react-i18next';

// Task 58: 评估耗时估算系数（与 TriggerEvalModal 保持一致）
const ESTIMATE_SECONDS_PER_QUESTION = 3;

export interface ProgressState {
  total: number;
  current: number;
  startTime: number;
  completed: boolean;
}

interface ProgressPanelProps {
  progressState: ProgressState | null;
  /** 更新 progressState（父组件的 setProgressState 包装） */
  onProgress: (updater: (prev: ProgressState | null) => ProgressState | null) => void;
  /** 用户点击 OK 关闭进度面板 */
  onClose: () => void;
}

/**
 * Task 4.1: 从 EvaluationPage 抽出的进度面板 Modal。
 * Task 8.2: 1s 计时器 useEffect 依赖已拆分为
 *           [progressState?.completed, progressState?.startTime, progressState?.total, onProgress]，
 *           不再依赖整个 progressState 对象（current 变化不会重建 timer）。
 * 后端无 SSE 推送，使用估算总时长模拟；同时利用已有 30s 自动 fetchRuns 检测实际状态。
 */
export default function ProgressPanel({ progressState, onProgress, onClose }: ProgressPanelProps) {
  const { t } = useTranslation();

  // 1s 计时器推进 current 题号
  useEffect(() => {
    if (!progressState || progressState.completed) return;
    const timer = setInterval(() => {
      onProgress((prev) => {
        if (!prev) return prev;
        const elapsedSec = (Date.now() - prev.startTime) / 1000;
        const next = Math.min(prev.total, Math.floor(elapsedSec / ESTIMATE_SECONDS_PER_QUESTION) + 1);
        // 到达总题数即视为完成（实际状态由 fetchRuns 校正）
        if (next >= prev.total) {
          return { ...prev, current: prev.total, completed: true };
        }
        return { ...prev, current: next };
      });
    }, 1000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅依赖 progressState 的具体属性，整体加入会导致不必要重新执行
  }, [progressState?.completed, progressState?.startTime, progressState?.total, onProgress]);

  return (
    <Modal
      title={t('evaluation.progressTitle')}
      open={!!progressState}
      footer={null}
      closable={false}
      maskClosable={false}
      transitionName=""
      maskTransitionName=""
      centered
      width={480}
    >
      {progressState && (
        <div style={{ padding: '8px 0' }}>
          <Progress
            percent={Math.round((progressState.current / progressState.total) * 100)}
            status={progressState.completed ? 'success' : 'active'}
            strokeColor={{
              from: 'var(--accent-primary)',
              to: 'var(--accent-secondary)',
            }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12 }}>
            <Typography.Text style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
              {t('evaluation.progressQuestion', {
                current: progressState.current,
                total: progressState.total,
              })}
            </Typography.Text>
            <Typography.Text
              strong
              style={{
                fontSize: 13,
                color: progressState.completed ? 'var(--accent-success)' : 'var(--accent-primary)',
              }}
            >
              {progressState.completed
                ? t('evaluation.progressCompleted')
                : t('evaluation.progressRunning')}
            </Typography.Text>
          </div>
          <div style={{ marginTop: 12, display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Button onClick={onClose}>
              {t('common.ok')}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
