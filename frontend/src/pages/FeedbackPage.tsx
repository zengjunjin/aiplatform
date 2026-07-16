import { useState, useEffect, useCallback } from 'react';
import {
  Card, Table, Tag, Statistic, Row, Col, Typography, Select, DatePicker,
  Space, Empty, Spin, Collapse, App as AntdApp, Radio,
} from 'antd';
import {
  LikeOutlined, DislikeOutlined, CommentOutlined, BarChartOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { feedbackApi } from '../api/chat';
import type { FeedbackStats, FeedbackDetail } from '../api/chat';
import { kbApi } from '../api';
import type { KnowledgeBase } from '../types';
import dayjs from 'dayjs';

const { Title, Text, Paragraph } = Typography;
const { RangePicker } = DatePicker;

const FEEDBACK_TYPE_LABELS: Record<string, string> = {
  not_accurate: 'chat.feedbackType.notAccurate',
  incomplete: 'chat.feedbackType.incomplete',
  hallucination: 'chat.feedbackType.hallucination',
  irrelevant: 'chat.feedbackType.irrelevant',
  too_verbose: 'chat.feedbackType.tooVerbose',
  too_brief: 'chat.feedbackType.tooBrief',
  other: 'chat.feedbackType.other',
};

const FEEDBACK_TYPE_COLORS: Record<string, string> = {
  not_accurate: 'orange',
  incomplete: 'blue',
  hallucination: 'red',
  irrelevant: 'purple',
  too_verbose: 'cyan',
  too_brief: 'geekblue',
  other: 'default',
};

export default function FeedbackPage() {
  const { t } = useTranslation();
  const { message } = AntdApp.useApp();

  const [stats, setStats] = useState<FeedbackStats | null>(null);
  const [feedbacks, setFeedbacks] = useState<FeedbackDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const [statsLoading, setStatsLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);

  // 筛选条件
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKbId, setSelectedKbId] = useState<number | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);
  const [selectedType, setSelectedType] = useState<string | undefined>();

  const fetchKBs = useCallback(async () => {
    try {
      const res = await kbApi.list(1, 100);
      setKnowledgeBases(res.items);
    } catch {
      // ignore
    }
  }, []);

  const fetchStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      const s = await feedbackApi.getStats(selectedKbId);
      setStats(s);
    } catch (e: any) {
      message.error(e.message || 'Failed to load stats');
    } finally {
      setStatsLoading(false);
    }
  }, [selectedKbId, message]);

  const fetchFeedbacks = useCallback(async () => {
    setLoading(true);
    try {
      const result = await feedbackApi.getLowRated({
        kb_id: selectedKbId,
        start_date: dateRange?.[0]?.toISOString(),
        end_date: dateRange?.[1]?.toISOString(),
        feedback_type: selectedType,
        page,
        page_size: pageSize,
      });
      setFeedbacks(result.items);
      setTotal(result.total);
    } catch (e: any) {
      message.error(e.message || 'Failed to load feedbacks');
    } finally {
      setLoading(false);
    }
  }, [selectedKbId, dateRange, selectedType, page, pageSize, message]);

  useEffect(() => {
    fetchKBs();
  }, [fetchKBs]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  useEffect(() => {
    fetchFeedbacks();
  }, [fetchFeedbacks]);

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      width: 80,
    },
    {
      title: t('chat.feedbackTypeLabel'),
      dataIndex: 'feedback_type',
      width: 130,
      render: (type: string | null) => {
        if (!type) return <Tag>N/A</Tag>;
        const label = FEEDBACK_TYPE_LABELS[type];
        const color = FEEDBACK_TYPE_COLORS[type] || 'default';
        return <Tag color={color}>{label ? t(label) : type}</Tag>;
      },
    },
    {
      title: t('chat.feedbackCommentLabel'),
      dataIndex: 'comment',
      width: 200,
      ellipsis: true,
      render: (comment: string | null) => comment || '-',
    },
    {
      title: 'Question',
      dataIndex: 'question',
      width: 250,
      ellipsis: true,
    },
    {
      title: 'Answer',
      dataIndex: 'answer',
      width: 250,
      ellipsis: true,
    },
    {
      title: 'KB ID',
      dataIndex: 'kb_id',
      width: 80,
      render: (kbId: number | null) => kbId ? `#${kbId}` : '-',
    },
    {
      title: 'Time',
      dataIndex: 'created_at',
      width: 170,
      render: (time: string) => dayjs(time).format('YYYY-MM-DD HH:mm'),
    },
  ];

  return (
    <div style={{ padding: 24, maxWidth: 1400, margin: '0 auto' }}>
      <Title level={3} style={{ marginBottom: 24 }}>
        <BarChartOutlined style={{ marginRight: 8 }} />
        Feedback Management
      </Title>

      {/* 统计概览 */}
      <Spin spinning={statsLoading}>
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col span={6}>
            <Card>
              <Statistic
                title="Total Feedback"
                value={stats?.total_feedback || 0}
                prefix={<CommentOutlined />}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="Positive Rate"
                value={stats ? (stats.positive_rate * 100).toFixed(1) : 0}
                suffix="%"
                prefix={<LikeOutlined />}
                valueStyle={{ color: '#3f8600' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="Negative Rate"
                value={stats ? (stats.negative_rate * 100).toFixed(1) : 0}
                suffix="%"
                prefix={<DislikeOutlined />}
                valueStyle={{ color: '#cf1322' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="By Type"
                value={stats ? Object.keys(stats.by_type).length : 0}
                suffix="types"
              />
            </Card>
          </Col>
        </Row>
      </Spin>

      {/* 类型分布 */}
      {stats && Object.keys(stats.by_type).length > 0 && (
        <Card title="Feedback Type Distribution" style={{ marginBottom: 24 }}>
          <Space wrap>
            {Object.entries(stats.by_type).map(([type, count]) => (
              <Tag
                key={type}
                color={FEEDBACK_TYPE_COLORS[type] || 'default'}
                style={{ fontSize: 14, padding: '4px 12px' }}
              >
                {t(FEEDBACK_TYPE_LABELS[type] || type)}: {count}
              </Tag>
            ))}
          </Space>
        </Card>
      )}

      {/* 筛选条件 */}
      <Card style={{ marginBottom: 24 }}>
        <Space wrap>
          <Select
            placeholder="Filter by KB"
            allowClear
            style={{ width: 200 }}
            value={selectedKbId}
            onChange={(val) => {
              setSelectedKbId(val);
              setPage(1);
            }}
            options={knowledgeBases.map((kb) => ({
              label: kb.name,
              value: kb.id,
            }))}
          />
          <RangePicker
            value={dateRange}
            onChange={(dates) => {
              setDateRange(dates as [dayjs.Dayjs, dayjs.Dayjs] | null);
              setPage(1);
            }}
          />
          <Select
            placeholder="Filter by Type"
            allowClear
            style={{ width: 180 }}
            value={selectedType}
            onChange={(val) => {
              setSelectedType(val);
              setPage(1);
            }}
            options={Object.entries(FEEDBACK_TYPE_LABELS).map(([value, label]) => ({
              label: t(label),
              value,
            }))}
          />
        </Space>
      </Card>

      {/* 低分回答列表 */}
      <Card title="Low-Rated Answers">
        <Table
          dataSource={feedbacks}
          columns={columns}
          rowKey="id"
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total,
            onChange: (p) => setPage(p),
            showSizeChanger: false,
            showTotal: (t) => `Total ${t} items`,
          }}
          expandable={{
            expandedRowRender: (record) => (
              <div style={{ padding: 16 }}>
                <Card
                  title="Question"
                  size="small"
                  style={{ marginBottom: 12, background: '#f6ffed' }}
                >
                  <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                    {record.question || '(No question found)'}
                  </Paragraph>
                </Card>
                <Card
                  title="System Answer"
                  size="small"
                  style={{ marginBottom: 12, background: '#fff7e6' }}
                >
                  <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                    {record.answer}
                  </Paragraph>
                </Card>
                {record.comment && (
                  <Card
                    title="User Feedback"
                    size="small"
                    style={{ background: 'var(--bg-tertiary)' }}
                  >
                    <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                      {record.comment}
                    </Paragraph>
                  </Card>
                )}
              </div>
            ),
          }}
          locale={{ emptyText: <Empty description="No feedback data" /> }}
        />
      </Card>
    </div>
  );
}