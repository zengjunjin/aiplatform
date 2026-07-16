import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Table,
  Tag,
  Button,
  Space,
  Popconfirm,
  App as AntdApp,
  Card,
  Skeleton,
  Empty,
  Modal,
  Descriptions,
  Statistic,
  Row,
  Col,
  InputNumber,
  Select,
  Form,
  Typography,
} from 'antd';
import {
  BarChart3,
  Play,
  Trash2,
  Eye,
  RefreshCw,
  TrendingUp,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { LineChart, BarChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { evaluationApi, kbApi } from '../api';
import type { EvaluationRunItem, EvaluationMetrics, EvaluationResultItem } from '../api/evaluation';

echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent, CanvasRenderer]);

const { Text } = Typography;

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  pending: { color: 'default', label: '待执行' },
  running: { color: 'processing', label: '运行中' },
  completed: { color: 'success', label: '已完成' },
  failed: { color: 'error', label: '失败' },
};

export default function EvaluationPage() {
  const { t } = useTranslation();
  const { message } = AntdApp.useApp();
  const [runs, setRuns] = useState<EvaluationRunItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [kbs, setKbs] = useState<{ id: number; name: string }[]>([]);
  const [triggerModal, setTriggerModal] = useState(false);
  const [detailModal, setDetailModal] = useState(false);
  const [selectedRun, setSelectedRun] = useState<EvaluationRunItem | null>(null);
  const [results, setResults] = useState<EvaluationResultItem[]>([]);
  const [resultsLoading, setResultsLoading] = useState(false);
  const [form] = Form.useForm();

  const fetchRuns = useCallback(async () => {
    setLoading(true);
    try {
      const data = await evaluationApi.listRuns({ page_size: 50 });
      setRuns(data?.items || []);
    } catch (e: any) {
      message.error(e.message || '加载评估历史失败');
    } finally {
      setLoading(false);
    }
  }, [message]);

  const fetchKbs = useCallback(async () => {
    try {
      const data = await kbApi.list(1, 100);
      setKbs((data?.items || []).map((kb: any) => ({ id: kb.id, name: kb.name })));
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    fetchRuns();
    fetchKbs();
  }, [fetchRuns, fetchKbs]);

  const handleTrigger = async () => {
    try {
      const values = await form.validateFields();
      await evaluationApi.triggerEvaluation(values.kb_id, values.num_questions || 50);
      message.success('评估任务已触发');
      setTriggerModal(false);
      form.resetFields();
      fetchRuns();
    } catch (e: any) {
      if (e.errorFields) return;
      message.error(e.message || '触发评估失败');
    }
  };

  const handleViewDetail = async (run: EvaluationRunItem) => {
    setSelectedRun(run);
    setDetailModal(true);
    setResultsLoading(true);
    try {
      const data = await evaluationApi.getResults(run.id, 1, 100);
      setResults(data?.items || []);
    } catch {
      setResults([]);
    } finally {
      setResultsLoading(false);
    }
  };

  const handleDelete = async (runId: number) => {
    try {
      await evaluationApi.deleteRun(runId);
      message.success('评估记录已删除');
      fetchRuns();
    } catch (e: any) {
      message.error(e.message || '删除失败');
    }
  };

  const handleRefresh = () => {
    fetchRuns();
  };

  const renderMetricCard = (label: string, value: number | null | undefined) => (
    <Card size="small">
      <Statistic
        title={label}
        value={value != null ? (value * 100).toFixed(1) : '-'}
        suffix={value != null ? '%' : ''}
        valueStyle={{ color: value != null ? (value >= 0.7 ? '#52c41a' : value >= 0.4 ? '#faad14' : '#ff4d4f') : undefined }}
      />
    </Card>
  );

  const trendChartOption = useMemo(() => {
    const completedRuns = runs
      .filter((r) => r.status === 'completed' && r.metrics)
      .reverse()
      .slice(-20);

    return {
      tooltip: { trigger: 'axis' as const },
      legend: { data: ['忠实度', '答案相关性', '上下文精确度', '上下文召回率'], top: 0 },
      grid: { left: '3%', right: '4%', bottom: '3%', top: 40, containLabel: true },
      xAxis: {
        type: 'category' as const,
        data: completedRuns.map((r) => `#${r.id}`),
        axisLabel: { rotate: 45 },
      },
      yAxis: {
        type: 'value' as const,
        min: 0,
        max: 1,
        axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
      },
      series: [
        {
          name: '忠实度',
          type: 'line',
          data: completedRuns.map((r) => r.metrics?.faithfulness ?? 0),
          smooth: true,
        },
        {
          name: '答案相关性',
          type: 'line',
          data: completedRuns.map((r) => r.metrics?.answer_relevancy ?? 0),
          smooth: true,
        },
        {
          name: '上下文精确度',
          type: 'line',
          data: completedRuns.map((r) => r.metrics?.context_precision ?? 0),
          smooth: true,
        },
        {
          name: '上下文召回率',
          type: 'line',
          data: completedRuns.map((r) => r.metrics?.context_recall ?? 0),
          smooth: true,
        },
      ],
    };
  }, [runs]);

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 70,
    },
    {
      title: '知识库',
      dataIndex: 'knowledge_base_id',
      key: 'kb_id',
      width: 100,
      render: (id: number) => {
        const kb = kbs.find((k) => k.id === id);
        return kb?.name || `KB #${id}`;
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const cfg = STATUS_MAP[status] || { color: 'default', label: status };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '题目数',
      dataIndex: 'total_questions',
      key: 'total_questions',
      width: 80,
    },
    {
      title: '忠实度',
      key: 'faithfulness',
      width: 100,
      render: (_: any, record: EvaluationRunItem) => {
        const v = record.metrics?.faithfulness;
        return v != null ? `${(v * 100).toFixed(1)}%` : '-';
      },
    },
    {
      title: '答案相关性',
      key: 'answer_relevancy',
      width: 100,
      render: (_: any, record: EvaluationRunItem) => {
        const v = record.metrics?.answer_relevancy;
        return v != null ? `${(v * 100).toFixed(1)}%` : '-';
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (v: string | null) => (v ? new Date(v).toLocaleString() : '-'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_: any, record: EvaluationRunItem) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<Eye size={14} />}
            onClick={() => handleViewDetail(record)}
          >
            详情
          </Button>
          <Popconfirm
            title="确定删除此评估记录？"
            onConfirm={() => handleDelete(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button type="link" size="small" danger icon={<Trash2 size={14} />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const resultColumns = [
    { title: '#', dataIndex: 'id', key: 'id', width: 60 },
    {
      title: '问题',
      dataIndex: 'question',
      key: 'question',
      width: 200,
      ellipsis: true,
    },
    {
      title: '生成答案',
      dataIndex: 'generated_answer',
      key: 'generated_answer',
      width: 250,
      ellipsis: true,
    },
    {
      title: '忠实度',
      dataIndex: 'faithfulness',
      key: 'faithfulness',
      width: 80,
      render: (v: number | null) => (v != null ? `${(v * 100).toFixed(1)}%` : '-'),
    },
    {
      title: '相关性',
      dataIndex: 'answer_relevancy',
      key: 'answer_relevancy',
      width: 80,
      render: (v: number | null) => (v != null ? `${(v * 100).toFixed(1)}%` : '-'),
    },
    {
      title: '精确度',
      dataIndex: 'context_precision',
      key: 'context_precision',
      width: 80,
      render: (v: number | null) => (v != null ? `${(v * 100).toFixed(1)}%` : '-'),
    },
    {
      title: '召回率',
      dataIndex: 'context_recall',
      key: 'context_recall',
      width: 80,
      render: (v: number | null) => (v != null ? `${(v * 100).toFixed(1)}%` : '-'),
    },
  ];

  return (
    <div>
      {/* Trend Chart */}
      <Card
        title={
          <Space>
            <TrendingUp size={20} />
            <span>评估趋势</span>
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        {runs.filter((r) => r.status === 'completed' && r.metrics).length > 0 ? (
          <ReactEChartsCore
            echarts={echarts}
            option={trendChartOption}
            style={{ height: 300 }}
            notMerge
          />
        ) : (
          <Empty description="暂无评估数据" />
        )}
      </Card>

      {/* Runs Table */}
      <Card
        title={
          <Space>
            <BarChart3 size={20} />
            <span>评估历史</span>
          </Space>
        }
        extra={
          <Space>
            <Button icon={<RefreshCw size={14} />} onClick={handleRefresh}>
              刷新
            </Button>
            <Button
              type="primary"
              icon={<Play size={14} />}
              onClick={() => setTriggerModal(true)}
            >
              触发评估
            </Button>
          </Space>
        }
      >
        {loading ? (
          <Skeleton active paragraph={{ rows: 8 }} />
        ) : runs.length === 0 ? (
          <Empty description="暂无评估记录，点击「触发评估」开始" />
        ) : (
          <Table
            dataSource={runs}
            columns={columns}
            rowKey="id"
            pagination={{ pageSize: 20 }}
          />
        )}
      </Card>

      {/* Trigger Modal */}
      <Modal
        title="触发评估"
        open={triggerModal}
        onOk={handleTrigger}
        onCancel={() => {
          setTriggerModal(false);
          form.resetFields();
        }}
        transitionName=""
        maskTransitionName=""
        okText="开始评估"
        cancelText="取消"
        centered
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="kb_id"
            label="选择知识库"
            rules={[{ required: true, message: '请选择知识库' }]}
          >
            <Select
              placeholder="选择要评估的知识库"
              options={kbs.map((kb) => ({
                label: kb.name,
                value: kb.id,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="num_questions"
            label="问题数量"
            initialValue={50}
          >
            <InputNumber min={5} max={200} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      {/* Detail Modal */}
      <Modal
        title={`评估详情 #${selectedRun?.id}`}
        open={detailModal}
        onCancel={() => {
          setDetailModal(false);
          setSelectedRun(null);
          setResults([]);
        }}
        transitionName=""
        maskTransitionName=""
        footer={null}
        width={900}
        centered
      >
        {selectedRun && (
          <>
            <Descriptions bordered column={2} size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="状态">
                <Tag color={STATUS_MAP[selectedRun.status]?.color}>
                  {STATUS_MAP[selectedRun.status]?.label}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="题目数">{selectedRun.total_questions}</Descriptions.Item>
              <Descriptions.Item label="开始时间">
                {selectedRun.started_at ? new Date(selectedRun.started_at).toLocaleString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="完成时间">
                {selectedRun.completed_at ? new Date(selectedRun.completed_at).toLocaleString() : '-'}
              </Descriptions.Item>
              {selectedRun.error_message && (
                <Descriptions.Item label="错误信息" span={2}>
                  <Text type="danger">{selectedRun.error_message}</Text>
                </Descriptions.Item>
              )}
            </Descriptions>

            {selectedRun.metrics && (
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={6}>
                  {renderMetricCard('忠实度', selectedRun.metrics.faithfulness)}
                </Col>
                <Col span={6}>
                  {renderMetricCard('答案相关性', selectedRun.metrics.answer_relevancy)}
                </Col>
                <Col span={6}>
                  {renderMetricCard('上下文精确度', selectedRun.metrics.context_precision)}
                </Col>
                <Col span={6}>
                  {renderMetricCard('上下文召回率', selectedRun.metrics.context_recall)}
                </Col>
              </Row>
            )}

            <Text strong style={{ display: 'block', marginBottom: 8 }}>逐题结果</Text>
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
    </div>
  );
}