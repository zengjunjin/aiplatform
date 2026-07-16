import { useState, useEffect, useCallback, useRef } from 'react';
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
import { formatFileSize, formatDateTime, getStatusColor, getStatusText } from '../utils/format';
import type { Document } from '../types';
import DocumentPreviewModal from '../components/DocumentPreviewModal';

const { Title, Text } = Typography;

export default function DocumentsPage() {
  const { t } = useTranslation();
  // 精细化订阅
  const knowledgeBases = useKBStore((s) => s.knowledgeBases);
  const fetchKBs = useKBStore((s) => s.fetchKBs);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(false);
  const [kbFilter, setKbFilter] = useState<number | undefined>(undefined);
  const [previewDoc, setPreviewDoc] = useState<Document | null>(null);
  const { message } = AntdApp.useApp();
  // 用于取消过期的并发请求 (切换筛选时旧请求结果应被丢弃)
  const fetchVersionRef = useRef(0);

  const fetchAllDocuments = useCallback(async () => {
    const version = ++fetchVersionRef.current;
    setLoading(true);
    try {
      // 并发获取所有（或选中的）知识库的文档
      const kbsToFetch = kbFilter
        ? knowledgeBases.filter((kb) => kb.id === kbFilter)
        : knowledgeBases;

      if (kbsToFetch.length === 0) {
        if (version !== fetchVersionRef.current) return; // 被新请求取代
        setDocuments([]);
        return;
      }

      const results = await Promise.all(
        kbsToFetch.map((kb) =>
          documentApi.list(kb.id, 1, 200)
            .then((res) => res.items)
            .catch(() => [] as Document[]),
        ),
      );

      // 检查是否被新的请求取代 (用户切换了筛选)
      if (version !== fetchVersionRef.current) return;

      const merged: Document[] = [];
      results.forEach((docs, idx) => {
        const kbId = kbsToFetch[idx]?.id;
        docs.forEach((doc) => {
          merged.push({ ...doc, kb_id: kbId ?? doc.kb_id });
        });
      });
      // 按创建时间倒序
      merged.sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      );
      setDocuments(merged);
    } catch (e: any) {
      if (version !== fetchVersionRef.current) return;
      message.error(e.message || t('document.loadFailed'));
    } finally {
      if (version === fetchVersionRef.current) {
        setLoading(false);
      }
    }
  }, [knowledgeBases, kbFilter, message, t]);

  useEffect(() => {
    fetchKBs();
  }, [fetchKBs]);

  useEffect(() => {
    if (knowledgeBases.length > 0) {
      fetchAllDocuments();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [knowledgeBases.length, kbFilter]);

  const handleDelete = async (docId: number) => {
    try {
      await documentApi.delete(docId);
      message.success(t('document.deleteSuccess'));
      fetchAllDocuments();
    } catch (e: any) {
      message.error(e.message || t('document.deleteFailed'));
    }
  };

  const handleReparse = async (docId: number) => {
    try {
      await documentApi.reparse(docId);
      message.success(t('document.reparsed'));
      fetchAllDocuments();
    } catch (e: any) {
      message.error(e.message || t('document.operationFailed'));
    }
  };

  const getKBName = (kbId: number) => {
    const kb = knowledgeBases.find((k) => k.id === kbId);
    return kb?.name || t('document.kbLabel', { kbId });
  };

  const columns = [
    {
      title: t('document.filename'),
      dataIndex: 'filename',
      key: 'filename',
      render: (text: string) => (
        <Space>
          <FileText size={16} style={{ color: 'var(--accent-primary)' }} />
          <span>{text}</span>
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
      render: (_: any, record: Document) => {
        const StatusIcon =
          record.status === 'failed'
            ? AlertCircle
            : record.status === 'done'
              ? CheckCircle
              : Clock;
        return (
          <Tag color={getStatusColor(record.status)} icon={<StatusIcon size={12} />}>
            {getStatusText(record.status)}
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
      render: (_: any, record: Document) => (
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
          >
            <Button size="small" danger icon={<Trash2 size={14} />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

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
            onChange={(val) => setKbFilter(val)}
            options={knowledgeBases.map((kb) => ({
              label: `${kb.name} (${kb.doc_count || 0} ${t('kb.documents', { count: kb.doc_count || 0 })})`,
              value: kb.id,
            }))}
          />
          <Button icon={<RefreshCw size={16} />} onClick={fetchAllDocuments} loading={loading}>
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
          <Table
            dataSource={documents}
            columns={columns}
            rowKey="id"
            pagination={{ pageSize: 10 }}
          />
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
