import { useTranslation } from 'react-i18next';

interface ThresholdBarProps {
  value: number | null | undefined;
}

/**
 * Task 5.8: 从 EvaluationPage.renderThresholdBar 抽出的独立组件。
 * 阈值横向 progress bar：0/0.4/0.7/1.0 四段着色 + 当前值指示器。
 */
export default function ThresholdBar({ value }: ThresholdBarProps) {
  const { t } = useTranslation();
  if (value == null) return null;
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div
      style={{
        position: 'relative',
        height: 8,
        marginTop: 8,
        borderRadius: 4,
        overflow: 'hidden',
        display: 'flex',
        background: 'var(--bg-tertiary)',
      }}
      role="meter"
      aria-label={t('evaluation.ragasThreshold')}
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={1}
    >
      {/* 0 ~ 0.4 红 */}
      <div style={{ width: '40%', background: 'var(--accent-danger)' }} />
      {/* 0.4 ~ 0.7 黄 */}
      <div style={{ width: '30%', background: 'var(--accent-warning)' }} />
      {/* 0.7 ~ 1.0 绿 */}
      <div style={{ width: '30%', background: 'var(--accent-success)' }} />
      {/* 当前值指示器 */}
      <div
        style={{
          position: 'absolute',
          top: -2,
          bottom: -2,
          left: `${pct}%`,
          width: 2,
          background: 'var(--text-primary)',
          transform: 'translateX(-1px)',
          boxShadow: '0 0 0 1px var(--bg-secondary)',
        }}
      />
    </div>
  );
}
