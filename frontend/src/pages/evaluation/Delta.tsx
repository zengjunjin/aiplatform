import { Space, Typography } from 'antd';
import { ArrowUp, ArrowDown } from 'lucide-react';
import { useTranslation } from 'react-i18next';

const { Text } = Typography;

interface DeltaProps {
  current: number | null | undefined;
  prev: number | null | undefined;
}

/**
 * Task 5.8: 从 EvaluationPage.renderDelta 抽出的独立组件。
 * 显示当前指标与上一次 completed run 的差值（百分比点）。
 */
export default function Delta({ current, prev }: DeltaProps) {
  const { t } = useTranslation();
  if (current == null || prev == null) {
    return <Text type="secondary" style={{ fontSize: 12 }}>{t('evaluation.deltaNoPrev')}</Text>;
  }
  const delta = (current - prev) * 100;
  if (Math.abs(delta) < 0.05) {
    return <Text type="secondary" style={{ fontSize: 12 }}>{t('evaluation.deltaFlat')}</Text>;
  }
  const isUp = delta > 0;
  const absDelta = Math.abs(delta).toFixed(1);
  const color = isUp ? 'var(--accent-success)' : 'var(--accent-danger)';
  const Icon = isUp ? ArrowUp : ArrowDown;
  return (
    <Space size={4} style={{ marginTop: 4 }} aria-label={isUp ? t('evaluation.deltaUp', { delta: absDelta }) : t('evaluation.deltaDown', { delta: absDelta })}>
      <Icon size={14} color={color} />
      <Text style={{ fontSize: 12, color }}>
        {t(isUp ? 'evaluation.deltaUp' : 'evaluation.deltaDown', { delta: absDelta })}
      </Text>
    </Space>
  );
}
