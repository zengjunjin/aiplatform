import { useMemo } from 'react';
import {
  Modal, Descriptions, Tag, Row, Col, Card, Skeleton, Table, Space, Typography,
} from 'antd';
import { BarChart3 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import type { EvaluationRunItem, EvaluationResultItem } from '../../api/evaluation';
import type { EvaluationMetrics } from '../../types';
import { formatDateTime } from '../../utils/format';
import { STATUS_MAP } from '../../constants/status';
import MetricCard from './MetricCard';

const { Text } = Typography;

// 横向 mini-bar：宽度 ~70px，按值显示颜色（0-0.4 红 / 0.4-0.7 黄 / 0.7-1 绿）
// 提取为模块级纯函数：不依赖任何 props/state/t，避免 useMemo 每次渲染重建与依赖数组 lint 告警
const renderMiniBar = (v: number | null) => {
  if (v == null) return <Text type="secondary">-</Text>;
  const pct = Math.max(0, Math.min(1, v)) * 100;
  const color =
    v >= 0.7 ? 'var(--accent-success)' : v >= 0.4 ? 'var(--accent-warning)' : 'var(--accent-danger)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 120 }}>
      <span style={{ fontSize: 12, minWidth: 44 }}>{(v * 100).toFixed(1)}%</span>
      <div
        style={{
          flex: 1,
          height: 6,
          borderRadius: 3,
          background: 'var(--bg-tertiary)',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: '100%',
            background: color,
            borderRadius: 3,
            transition: 'width var(--transition-base)',
          }}
        />
      </div>
    </div>
  );
};

interface RunDetailModalProps {
  open: boolean;
  selectedRun: EvaluationRunItem | null;
  results: EvaluationResultItem[];
  resultsLoading: boolean;
  prevRunMetrics: EvaluationMetrics | null;
  onClose: () => void;
}

/**
 * Task 4.1: 从 EvaluationPage 抽出的详情弹窗。
 * 包含：run 基本信息 Descriptions + 4 个 MetricCard（Task 5.8 独立组件）+ 箱线图 + 单题结果表。
 */
export default function RunDetailModal({
  open,
  selectedRun,
  results,
  resultsLoading,
  prevRunMetrics,
  onClose,
}: RunDetailModalProps) {
  const { t } = useTranslation();

  const resultColumns = useMemo(() => [
    { title: '#', dataIndex: 'id', key: 'id', width: 60 },
    {
      title: t('evaluation.resultColumns.question'),
      dataIndex: 'question',
      key: 'question',
      width: 200,
      ellipsis: true,
    },
    {
      title: t('evaluation.resultColumns.generatedAnswer'),
      dataIndex: 'generated_answer',
      key: 'generated_answer',
      width: 250,
      ellipsis: true,
    },
    {
      title: t('evaluation.metrics.faithfulness'),
      dataIndex: 'faithfulness',
      key: 'faithfulness',
      width: 140,
      render: (v: number | null) => renderMiniBar(v),
    },
    {
      title: t('evaluation.metrics.relevancy'),
      dataIndex: 'answer_relevancy',
      key: 'answer_relevancy',
      width: 140,
      render: (v: number | null) => renderMiniBar(v),
    },
    {
      title: t('evaluation.metrics.precision'),
      dataIndex: 'context_precision',
      key: 'context_precision',
      width: 140,
      render: (v: number | null) => renderMiniBar(v),
    },
    {
      title: t('evaluation.metrics.recall'),
      dataIndex: 'context_recall',
      key: 'context_recall',
      width: 140,
      render: (v: number | null) => renderMiniBar(v),
    },
  ], [t]);

  // 箱线图：展示 4 个指标在所有单题结果上的分布
  // ECharts boxplot data 格式：[min, Q1, median, Q3, max]
  const boxplotChartOption = useMemo(() => {
    const metricKeys: Array<'faithfulness' | 'answer_relevancy' | 'context_precision' | 'context_recall'> = [
      'faithfulness',
      'answer_relevancy',
      'context_precision',
      'context_recall',
    ];
    const labels = [
      t('evaluation.metrics.faithfulness'),
      t('evaluation.metrics.relevancy'),
      t('evaluation.metrics.precision'),
      t('evaluation.metrics.recall'),
    ];

    // 计算分位数（线性插值法）
    const quantile = (sorted: number[], q: number): number => {
      if (sorted.length === 0) return 0;
      if (sorted.length === 1) return sorted[0];
      const pos = (sorted.length - 1) * q;
      const base = Math.floor(pos);
      const rest = pos - base;
      const next = base + 1 < sorted.length ? sorted[base + 1] : sorted[base];
      return sorted[base] + rest * (next - sorted[base]);
    };

    const boxData = metricKeys.map((key) => {
      const values = results
        .map((r) => r[key])
        .filter((v): v is number => typeof v === 'number' && !Number.isNaN(v))
        .sort((a, b) => a - b);
      if (values.length === 0) return [0, 0, 0, 0, 0];
      return [
        values[0],
        quantile(values, 0.25),
        quantile(values, 0.5),
        quantile(values, 0.75),
        values[values.length - 1],
      ];
    });

    return {
      tooltip: {
        trigger: 'item' as const,
      },
      grid: { left: '3%', right: '4%', bottom: '3%', top: 16, containLabel: true },
      xAxis: {
        type: 'category' as const,
        data: labels,
        axisLabel: { interval: 0, fontSize: 11 },
      },
      yAxis: {
        type: 'value' as const,
        min: 0,
        max: 1,
        axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
      },
      series: [
        {
          name: t('evaluation.metricDistribution'),
          type: 'boxplot' as const,
          data: boxData,
          itemStyle: { color: 'rgba(59, 130, 246, 0.25)' },
        },
      ],
    };
  }, [results, t]);

  const hasResultData = results.some(
    (r) =>
      r.faithfulness != null ||
      r.answer_relevancy != null ||
      r.context_precision != null ||
      r.context_recall != null,
  );

  return (
    <Modal
      title={t('evaluation.detailTitle', { id: selectedRun?.id })}
      open={open}
      onCancel={onClose}
      transitionName=""
      maskTransitionName=""
      footer={null}
      width={900}
      centered
    >
      {selectedRun && (
        <>
          <Descriptions bordered column={2} size="small" style={{ marginBottom: 16 }}>
            <Descriptions.Item label={t('evaluation.detail.status')}>
              <Tag color={STATUS_MAP[selectedRun.status]?.color}>
                {STATUS_MAP[selectedRun.status] ? t(STATUS_MAP[selectedRun.status].labelKey) : selectedRun.status}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label={t('evaluation.detail.questionCount')}>{selectedRun.total_questions}</Descriptions.Item>
            <Descriptions.Item label={t('evaluation.detail.startTime')}>
              {selectedRun.started_at ? formatDateTime(selectedRun.started_at) : '-'}
            </Descriptions.Item>
            <Descriptions.Item label={t('evaluation.detail.completeTime')}>
              {selectedRun.completed_at ? formatDateTime(selectedRun.completed_at) : '-'}
            </Descriptions.Item>
            {selectedRun.error_message && (
              <Descriptions.Item label={t('evaluation.detail.error')} span={2}>
                <Text type="danger">{selectedRun.error_message}</Text>
              </Descriptions.Item>
            )}
          </Descriptions>

          {selectedRun.metrics && (
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={6}>
                <MetricCard label={t('evaluation.metrics.faithfulness')} value={selectedRun.metrics.faithfulness} prevValue={prevRunMetrics?.faithfulness} />
              </Col>
              <Col span={6}>
                <MetricCard label={t('evaluation.metrics.answerRelevancy')} value={selectedRun.metrics.answer_relevancy} prevValue={prevRunMetrics?.answer_relevancy} />
              </Col>
              <Col span={6}>
                <MetricCard label={t('evaluation.metrics.contextPrecision')} value={selectedRun.metrics.context_precision} prevValue={prevRunMetrics?.context_precision} />
              </Col>
              <Col span={6}>
                <MetricCard label={t('evaluation.metrics.contextRecall')} value={selectedRun.metrics.context_recall} prevValue={prevRunMetrics?.context_recall} />
              </Col>
            </Row>
          )}

          <Text strong style={{ display: 'block', marginBottom: 8 }}>{t('evaluation.perQuestionResults')}</Text>
          {!resultsLoading && hasResultData && (
            <Card
              size="small"
              title={
                <Space size={6}>
                  <BarChart3 size={14} />
                  <span style={{ fontSize: 13 }}>{t('evaluation.metricDistribution')}</span>
                </Space>
              }
              style={{ marginBottom: 12 }}
              styles={{ body: { padding: 12 } }}
            >
              <ReactEChartsCore
                echarts={echarts}
                option={boxplotChartOption}
                style={{ height: 200 }}
                notMerge
                aria-label={t('evaluation.metricDistribution')}
              />
            </Card>
          )}
          {resultsLoading ? (
            <Skeleton active paragraph={{ rows: 6 }} />
          ) : (
            <Table
              dataSource={results}
              columns={resultColumns}
              rowKey="id"
              size="small"
              pagination={{ pageSize: 10 }}
              scroll={{ x: 800 }}
            />
          )}
        </>
      )}
    </Modal>
  );
}
