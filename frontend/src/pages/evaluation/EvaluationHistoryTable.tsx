import { useMemo } from 'react';
import { Table, Tag, Button, Space, Popconfirm, Card, Skeleton, Empty } from 'antd';
import { BarChart3, Play, Trash2, Eye, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { EvaluationRunItem } from '../../api/evaluation';
import { formatDateTime } from '../../utils/format';
import { STATUS_MAP } from '../../constants/status';

interface EvaluationHistoryTableProps {
  runs: EvaluationRunItem[];
  loading: boolean;
  kbs: { id: number; name: string }[];
  onRefresh: () => void;
  onTrigger: () => void;
  onViewDetail: (run: EvaluationRunItem) => void;
  onDelete: (runId: number) => void;
  pagination: { current: number; pageSize: number; total: number };
  onTableChange: (page: number, pageSize: number) => void;
}

/**
 * Task 4.1: 从 EvaluationPage 抽出的历史表卡片。
 * Task 5.2: columns 依赖 handleViewDetail/handleDelete（父组件以 useCallback 传入），
 *           不再需要 eslint-disable-next-line react-hooks/exhaustive-deps。
 */
export default function EvaluationHistoryTable({
  runs,
  loading,
  kbs,
  onRefresh,
  onTrigger,
  onViewDetail,
  onDelete,
  pagination,
  onTableChange,
}: EvaluationHistoryTableProps) {
  const { t } = useTranslation();

  const columns = useMemo(() => [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 70,
    },
    {
      title: t('evaluation.columns.kb'),
      dataIndex: 'knowledge_base_id',
      key: 'kb_id',
      width: 100,
      render: (id: number) => {
        const kb = kbs.find((k) => k.id === id);
        return kb?.name || `KB #${id}`;
      },
    },
    {
      title: t('evaluation.columns.status'),
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const cfg = STATUS_MAP[status] || { color: 'default', labelKey: status };
        return <Tag color={cfg.color}>{cfg.labelKey.startsWith('evaluation.') ? t(cfg.labelKey) : status}</Tag>;
      },
    },
    {
      title: t('evaluation.columns.questionCount'),
      dataIndex: 'total_questions',
      key: 'total_questions',
      width: 80,
    },
    {
      title: t('evaluation.metrics.faithfulness'),
      key: 'faithfulness',
      width: 100,
      render: (_: unknown, record: EvaluationRunItem) => {
        const v = record.metrics?.faithfulness;
        return v != null ? `${(v * 100).toFixed(1)}%` : '-';
      },
    },
    {
      title: t('evaluation.metrics.answerRelevancy'),
      key: 'answer_relevancy',
      width: 100,
      render: (_: unknown, record: EvaluationRunItem) => {
        const v = record.metrics?.answer_relevancy;
        return v != null ? `${(v * 100).toFixed(1)}%` : '-';
      },
    },
    {
      title: t('evaluation.columns.createdAt'),
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (v: string | null) => (v ? formatDateTime(v) : '-'),
    },
    {
      title: t('evaluation.columns.actions'),
      key: 'actions',
      width: 160,
      render: (_: unknown, record: EvaluationRunItem) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<Eye size={14} />}
            onClick={() => onViewDetail(record)}
          >
            {t('evaluation.detail')}
          </Button>
          <Popconfirm
            title={t('evaluation.deleteConfirmTitle')}
            onConfirm={() => onDelete(record.id)}
            okText={t('common.confirm')}
            cancelText={t('common.cancel')}
          >
            <Button type="link" size="small" danger icon={<Trash2 size={14} />}>
              {t('evaluation.delete')}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ], [t, kbs, onViewDetail, onDelete]);

  return (
    <Card
      title={
        <Space>
          <BarChart3 size={20} />
          <span>{t('evaluation.history')}</span>
        </Space>
      }
      extra={
        <Space>
          <Button icon={<RefreshCw size={14} />} onClick={onRefresh}>
            {t('evaluation.refresh')}
          </Button>
          <Button
            type="primary"
            icon={<Play size={14} />}
            onClick={onTrigger}
          >
            {t('evaluation.trigger')}
          </Button>
        </Space>
      }
    >
      {loading ? (
        // 与最终表格行数匹配，避免布局抖动
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : runs.length === 0 ? (
        <Empty description={t('evaluation.noRecords')} />
      ) : (
        <Table
          dataSource={runs}
          columns={columns}
          rowKey="id"
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: pagination.total,
            showSizeChanger: true,
          }}
          onChange={(p) => onTableChange(p.current ?? 1, p.pageSize ?? pagination.pageSize)}
        />
      )}
    </Card>
  );
}
