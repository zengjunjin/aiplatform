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
} from 'lucide-react';
import { documentApi } from '../api';
import { useKBStore } from '../store/kb';
import { formatFileSize, formatDateTime, getStatusColor, getStatusText } from '../utils/format';
import type { Document } from '../types';

const { Title, Text } = Typography;

export default function DocumentsPage() {
  // 精细化订阅
  const knowledgeBases = useKBStore((s) => s.knowledgeBases);
  const fetchKBs = useKBStore((s) => s.fetchKBs);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(false);
  const [kbFilter, setKbFilter] = useState<number | undefined>(undefined);
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
      message.error(e.message || '加载失败');
    } finally {
      if (version === fetchVersionRef.current) {
        setLoading(false);
      }
    }
  }, [knowledgeBases, kbFilter, message]);

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
      message.success('删除成功');
      fetchAllDocuments();
    } catch (e: any) {
      message.error(e.message || '删除失败');
    }
  };

  const handleReparse = async (docId: number) => {
    try {
      await documentApi.reparse(docId);
      message.success('已重新解析');
      fetchAllDocuments();
    } catch (e: any) {
      message.error(e.message || '操作失败');
    }
  };

  const getKBName = (kbId: number) => {
    const kb = knowledgeBases.find((k) => k.id === kbId);
    return kb?.name || `知识库 #${kbId}`;
  };

  const columns = [
    {
      title: '文件名',
      dataIndex: 'filename',
      key: 'filename',
      render: (text: string) => (
        <Space>
          <FileText size={16} style={{ color: '#1677ff' }} />
          <span>{text}</span>
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'file_type',
      key: 'file_type',
      width: 80,
      render: (type: string) => <Tag>{(type || 'file').toUpperCase()}</Tag>,
    },
    {
      title: '大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 100,
      render: (size: number) => formatFileSize(size),
    },
    {
      title: '所属知识库',
      dataIndex: 'kb_id',
      key: 'kb_id',
      width: 180,
      render: (kbId: number) => <Tag color="geekblue">{getKBName(kbId)}</Tag>,
    },
    {
      title: '状态',
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
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (t: string) => formatDateTime(t),
    },
    {
      title: '操作',
      key: 'actions',
      width: 180,
      render: (_: any, record: Document) => (
        <Space>
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
            重新解析
          </Button>
          <Popconfirm
            title="确定删除该文档？"
            description="删除后文档及其分块数据将永久丢失"
            onConfirm={() => handleDelete(record.id)}
            okText="删除"
            cancelText="取消"
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
          文档管理
        </Title>
        <Space>
          <Select
            placeholder="按知识库筛选"
            allowClear
            style={{ width: 240 }}
            value={kbFilter}
            onChange={(val) => setKbFilter(val)}
            options={knowledgeBases.map((kb) => ({
              label: `${kb.name} (${kb.doc_count || 0} 文档)`,
              value: kb.id,
            }))}
          />
          <Button icon={<RefreshCw size={16} />} onClick={fetchAllDocuments} loading={loading}>
            刷新
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
                暂无文档
                <br />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  请到知识库页面上传文档
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
    </div>
  );
}
