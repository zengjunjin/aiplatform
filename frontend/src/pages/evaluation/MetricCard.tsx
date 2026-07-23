import { Card, Statistic } from 'antd';
import Delta from './Delta';
import ThresholdBar from './ThresholdBar';

interface MetricCardProps {
  label: string;
  value: number | null | undefined;
  prevValue: number | null | undefined;
}

/**
 * Task 5.8: 从 EvaluationPage.renderMetricCard 抽出的独立组件。
 * 单个指标卡片：数值 + Delta（与上一次差值）+ ThresholdBar（阈值条）。
 */
export default function MetricCard({ label, value, prevValue }: MetricCardProps) {
  return (
    <Card size="small">
      <Statistic
        title={label}
        value={value != null ? (value * 100).toFixed(1) : '-'}
        suffix={value != null ? '%' : ''}
        valueStyle={{
          color:
            value != null
              ? value >= 0.7
                ? 'var(--accent-success)'
                : value >= 0.4
                  ? 'var(--accent-warning)'
                  : 'var(--accent-danger)'
              : undefined,
        }}
      />
      <Delta current={value} prev={prevValue} />
      <ThresholdBar value={value} />
    </Card>
  );
}
