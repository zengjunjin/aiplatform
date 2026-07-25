import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
  Table,
  Tag,
  Space,
  Typography,
  Button,
  Select,
  Card,
  Popconfirm,
  App as AntdApp,
  Skeleton,
  Empty,
  Badge,
} from 'antd';
import {
  RefreshCw,
  Trash2,
  FileText,
  AlertCircle,
  CheckCircle,
  Clock,
  Eye,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { documentApi } from '../api';
import { useKBStore } from '../store/kb';
import { useKbOptions } from '../hooks/useKbOptions';
import { formatFileSize, formatDateTime, getStatusColor, getStatusTextKey } from '../utils/format';
import type { Document } from '../types';
import DocumentPreviewModal from '../components/DocumentPreviewModal';
import { getErrorMessage } from '../utils/errorReporter';
import { DocumentsStatsRow } from './DocumentsPage.parts';

const { Title, Text } = Typography;

const PAGE_SIZE = 10;

export default function DocumentsPage() {
  const { t } = useTranslation();
  // 精细化订阅
  const knowledgeBases = useKBStore((s) => s.knowledgeBases);
  const fetchKBs = useKBStore((s) => s.fetchKBs);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [kbFilter, setKbFilter] = useState<number | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(PAGE_SIZE);
  const [previewDoc, setPreviewDoc] = useState<Document | null>(null);
  // Task 25: 单条文档操作 loading 防止重复点击
  const [deletingIds, setDeletingIds] = useState<Set<number>>(new Set());
  const [reparsingIds, setReparsingIds] = useState<Set<number>>(new Set());
  // Task 20: 通过 ref 读取最新的 Set，避免 columns useMemo 因 Set 引用变化频繁重建
  const deletingIdsRef = useRef(deletingIds);
  deletingIdsRef.current = deletingIds;
  const reparsingIdsRef = useRef(reparsingIds);
  reparsingIdsRef.current = reparsingIds;
  const { message } = AntdApp.useApp();
  // 用于取消过期的并发请求 (切换筛选/翻页时旧请求结果应被丢弃)
  const fetchVersionRef = useRef(0);

  const fetchDocuments = useCallback(async (targetPage: number, targetKbFilter?: number) => {
    const version = ++fetchVersionRef.current;
    setLoading(true);
    try {
      const data = await documentApi.list(targetKbFilter, targetPage, PAGE_SIZE);
      // 检查是否被新的请求取代 (用户切换了筛选或快速翻页)
      if (version !== fetchVersionRef.current) return;
      setDocuments(data.items || []);
      setTotal(data.total || 0);
    } catch (e: unknown) {
      if (version !== fetchVersionRef.current) return;
      message.error(getErrorMessage(e) || t('document.loadFailed'));
      setDocuments([]);
      setTotal(0);
    } finally {
      if (version === fetchVersionRef.current) {
        setLoading(false);
      }
    }
  }, [message, t]);

  // 持有最新的 fetchDocuments 引用, 避免 useCallback 依赖变化时 useEffect 反复触发导致循环
  const fetchDocumentsRef = useRef(fetchDocuments);
  fetchDocumentsRef.current = fetchDocuments;

  useEffect(() => {
    fetchKBs();
  }, [fetchKBs]);

  // 知识库加载完成后或筛选/页码变化时, 发起服务端分页请求
  useEffect(() => {
    fetchDocumentsRef.current(page, kbFilter);
  }, [knowledgeBases.length, kbFilter, page]);

  const handleKbFilterChange = (val: number | undefined) => {
    setKbFilter(val);
    // 切换筛选器时重置到第 1 页
    setPage(1);
  };

  const handlePageChange = (nextPage: number, nextPageSize: number) => {
    setPage(nextPage);
    // pageSize 保持不变 (PAGE_SIZE 常量), 这里仅消费参数避免 lint 警告
    void nextPageSize;
  };

  const handleRefresh = () => {
    fetchDocuments(page, kbFilter);
  };

  const handleDelete = useCallback(async (docId: number) => {
    // 防止重复点击
    if (deletingIds.has(docId)) return;
    setDeletingIds((prev) => new Set(prev).add(docId));
    // 乐观更新: 本地立即移除该文档, 失败时回滚
    const snapshot = documents;
    const snapshotTotal = total;
    setDocuments((prev) => prev.filter((d) => d.id !== docId));
    setTotal((prev) => Math.max(0, prev - 1));
    try {
      await documentApi.delete(docId);
      message.success(t('document.deleteSuccess'));
    } catch (e: unknown) {
      // 回滚
      setDocuments(snapshot);
      setTotal(snapshotTotal);
      message.error(getErrorMessage(e) || t('document.deleteFailed'));
    } finally {
      setDeletingIds((prev) => {
        const next = new Set(prev);
        next.delete(docId);
        return next;
      });
    }
  }, [deletingIds, documents, total, message, t]);

  const handleReparse = useCallback(async (docId: number) => {
    // 防止重复点击
    if (reparsingIds.has(docId)) return;
    setReparsingIds((prev) => new Set(prev).add(docId));
    // 乐观更新: 本地立即把 status 置为 'parsing', 失败时回滚
    const snapshot = documents;
    setDocuments((prev) =>
      prev.map((d) => (d.id === docId ? { ...d, status: 'parsing' as const, error_message: null } : d))
    );
    try {
      await documentApi.reparse(docId);
      message.success(t('document.reparsed'));
    } catch (e: unknown) {
      // 回滚
      setDocuments(snapshot);
      message.error(getErrorMessage(e) || t('document.operationFailed'));
    } finally {
      setReparsingIds((prev) => {
        const next = new Set(prev);
        next.delete(docId);
        return next;
      });
    }
  }, [reparsingIds, documents, message, t]);

  const getKBName = useCallback((kbId: number) => {
    const kb = knowledgeBases.find((k) => k.id === kbId);
    return kb?.name || t('document.kbLabel', { kbId });
  }, [knowledgeBases, t]);

  const kbOptions = useKbOptions(knowledgeBases, t);

  const columns = useMemo(() => [
    {
      title: t('document.filename'),
      dataIndex: 'filename',
      key: 'filename',
      // Task 59: 失败文档置顶（sorter 让 failed 排在最前，其余按创建时间倒序）
      sorter: (a: Document, b: Document) => {
        if (a.status === 'failed' && b.status !== 'failed') return -1;
        if (b.status === 'failed' && a.status !== 'failed') return 1;
        return (b.created_at || '').localeCompare(a.created_at || '');
      },
      defaultSortOrder: 'ascend' as const,
      render: (text: string, record: Document) => (
        <Space>
          <FileText size={16} style={{ color: 'var(--accent-primary)' }} />
          <span>{text}</span>
          {/* Task 59: 失败文档红色徽章 */}
          {record.status === 'failed' && (
            <Badge
              count={t('document.statsFailedBadge')}
              style={{ backgroundColor: 'var(--accent-danger)' }}
            />
          )}
        </Space>
      ),
    },
    {
      title: t('document.type'),
      dataIndex: 'file_type',
      key: 'file_type',
      width: 80,
      render: (type: string) => <Tag>{(type || 'file').toUpperCase()}</Tag>,
    },
    {
      title: t('document.size'),
      dataIndex: 'file_size',
      key: 'file_size',
      width: 100,
      render: (size: number) => formatFileSize(size),
    },
    {
      title: t('document.belongsToKB'),
      dataIndex: 'kb_id',
      key: 'kb_id',
      width: 180,
      render: (kbId: number) => <Tag color="geekblue">{getKBName(kbId)}</Tag>,
    },
    {
      title: t('document.status'),
      key: 'status',
      width: 140,
      render: (_: unknown, record: Document) => {
        const StatusIcon =
          record.status === 'failed'
            ? AlertCircle
            : record.status === 'done'
              ? CheckCircle
              : Clock;
        return (
          <Tag color={getStatusColor(record.status)} icon={<StatusIcon size={12} />}>
            {getStatusTextKey(record.status)}
          </Tag>
        );
      },
    },
    {
      title: t('document.createdAt'),
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (t: string) => formatDateTime(t),
    },
    {
      title: t('document.actions'),
      key: 'actions',
      width: 230,
      render: (_: unknown, record: Document) => (
        <Space>
          <Button
            size="small"
            icon={<Eye size={14} />}
            onClick={() => setPreviewDoc(record)}
          >
            {t('document.preview')}
          </Button>
          <Button
            size="small"
            icon={<RefreshCw size={14} />}
            onClick={() => handleReparse(record.id)}
            loading={reparsingIdsRef.current.has(record.id)}
            disabled={
              record.status === 'parsing' ||
              record.status === 'embedding' ||
              record.status === 'chunking'
            }
          >
            {t('document.reparse')}
          </Button>
          <Popconfirm
            title={t('document.deleteConfirmTitle')}
            description={t('document.deleteConfirmDesc')}
            onConfirm={() => handleDelete(record.id)}
            okText={t('document.delete')}
            cancelText={t('document.cancel')}
            disabled={deletingIds.has(record.id)}
          >
            <Button
              size="small"
              danger
              icon={<Trash2 size={14} />}
              aria-label={t('document.delete')}
              loading={deletingIdsRef.current.has(record.id)}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ], [t, handleReparse, handleDelete, getKBName, setPreviewDoc, deletingIds]);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>
          {t('document.management')}
        </Title>
        <Space>
          <Select
            placeholder={t('document.filterByKB')}
            allowClear
            style={{ width: 240 }}
            value={kbFilter}
            onChange={handleKbFilterChange}
            options={kbOptions}
          />
          <Button icon={<RefreshCw size={16} />} onClick={handleRefresh} loading={loading}>
            {t('document.refresh')}
          </Button>
        </Space>
      </div>

      <Card>
        {loading ? (
          <Skeleton active paragraph={{ rows: 6 }} />
        ) : documents.length === 0 ? (
          <Empty
            description={
              <span>
                {t('document.noDocuments')}
                <br />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t('document.noDocumentsHint')}
                </Text>
              </span>
            }
          />
        ) : (
          <>
            {/* Task 59: 顶部聚合统计 - 状态环形图 + 类型横向条形图 + 总大小 Statistic */}
            <DocumentsStatsRow documents={documents} />
            <Table
              dataSource={documents}
              columns={columns}
              rowKey="id"
              pagination={{
                current: page,
                pageSize,
                total,
                showSizeChanger: false,
                onChange: handlePageChange,
              }}
            />
          </>
        )}
      </Card>

      <DocumentPreviewModal
        open={!!previewDoc}
        docId={previewDoc?.id || 0}
        filename={previewDoc?.filename || ''}
        fileType={previewDoc?.file_type || ''}
        onClose={() => setPreviewDoc(null)}
      />
    </div>
  );
}
