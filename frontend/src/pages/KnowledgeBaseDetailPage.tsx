import { useState, useEffect } from 'react';
import {
  Button,
  Table,
  Tag,
  Space,
  Typography,
  Upload,
  Modal,
  Progress,
  Popconfirm,
  App as AntdApp,
  Breadcrumb,
  Tooltip,
  Card,
  Skeleton,
  Empty,
  Form,
  Input,
} from 'antd';
import {
  ArrowLeft,
  Upload as UploadIcon,
  RefreshCw,
  Trash2,
  FileText,
  AlertCircle,
  CheckCircle,
  Clock,
  Edit3,
} from 'lucide-react';
import { useParams, useNavigate } from 'react-router-dom';
import { useKBStore } from '../store/kb';
import { documentApi } from '../api';
import { formatFileSize, formatDateTime, getStatusColor, getStatusText } from '../utils/format';
import type { Document, DocumentProgress } from '../types';

const { Title, Text } = Typography;

export default function KnowledgeBaseDetailPage() {
  const { kbId } = useParams<{ kbId: string }>();
  const navigate = useNavigate();
  // 精细化订阅
  const knowledgeBases = useKBStore((s) => s.knowledgeBases);
  const fetchKBs = useKBStore((s) => s.fetchKBs);
  const fetchDocuments = useKBStore((s) => s.fetchDocuments);
  const deleteDocument = useKBStore((s) => s.deleteDocument);
  const reparseDocument = useKBStore((s) => s.reparseDocument);
  const pollProgress = useKBStore((s) => s.pollProgress);
  const updateKB = useKBStore((s) => s.updateKB);
  const [uploadModal, setUploadModal] = useState(false);
  const [editModal, setEditModal] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [progressMap, setProgressMap] = useState<Record<number, DocumentProgress>>({});
  const [editForm] = Form.useForm();
  const { message } = AntdApp.useApp();

  const kbIdNum = parseInt(kbId || '0', 10);
  const kb = knowledgeBases.find((k) => k.id === kbIdNum);
  const documents = useKBStore((s) => s.documents[kbIdNum] || []);
  const loading = useKBStore((s) => s.loadingDocs[kbIdNum] || false);

  useEffect(() => {
    if (kbIdNum > 0) {
      fetchKBs();
      fetchDocuments(kbIdNum);
    }
  }, [kbIdNum, fetchKBs, fetchDocuments]);

  // Poll only for documents that are still processing.
  // Use a stable string key to avoid infinite re-trigger when documents array reference changes.
  const pendingDocIds = documents
    .filter((d) => d.status !== 'done' && d.status !== 'failed')
    .map((d) => d.id)
    .join(',');

  useEffect(() => {
    if (!pendingDocIds) return;
    const ids = pendingDocIds.split(',').map(Number);
    const stopFns: (() => void)[] = [];
    ids.forEach((docId) => {
      const stop = pollProgress(docId, (p) => {
        setProgressMap((prev) => ({ ...prev, [docId]: p }));
        if (p.status === 'done' || p.status === 'failed') {
          fetchDocuments(kbIdNum);
        }
      });
      stopFns.push(stop);
    });
    return () => stopFns.forEach((fn) => fn());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingDocIds, kbIdNum]);

  const handleUpload = async (file: File) => {
    setUploading(true);
    setUploadProgress(0);
    try {
      await documentApi.upload(kbIdNum, file, (loaded, total) => {
        setUploadProgress(Math.round((loaded / total) * 100));
      });
      message.success('上传成功，正在处理...');
      setUploadModal(false);
      fetchDocuments(kbIdNum);
    } catch (e: any) {
      message.error(e.message || '上传失败');
    } finally {
      setUploading(false);
      setUploadProgress(0);
    }
  };

  const handleReparse = async (docId: number) => {
    try {
      await reparseDocument(kbIdNum, docId);
      message.success('已重新解析');
    } catch (e: any) {
      message.error(e.message || '操作失败');
    }
  };

  const handleDelete = async (docId: number) => {
    try {
      await deleteDocument(kbIdNum, docId);
      message.success('删除成功');
    } catch (e: any) {
      message.error(e.message || '删除失败');
    }
  };

  const handleEditClick = () => {
    editForm.setFieldsValue({
      name: kb?.name || '',
      description: kb?.description || '',
    });
    setEditModal(true);
  };

  const handleEditSubmit = async () => {
    try {
      const values = await editForm.validateFields();
      await updateKB(kbIdNum, values.name, values.description || '');
      message.success('更新成功');
      setEditModal(false);
    } catch (e: any) {
      if (e.errorFields) return;
      message.error(e.message || '更新失败');
    }
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
      render: (type: string) => <Tag>{type.toUpperCase()}</Tag>,
    },
    {
      title: '大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 100,
      render: (size: number) => formatFileSize(size),
    },
    {
      title: '状态',
      key: 'status',
      width: 220,
      render: (_: any, record: Document) => {
        const progress = progressMap[record.id];
        const statusText = progress?.status ? getStatusText(progress.status) : getStatusText(record.status);
        const statusColor = progress?.status ? getStatusColor(progress.status) : getStatusColor(record.status);
        const progressVal = progress?.progress || 0;

        const StatusIcon = record.status === 'failed' ? AlertCircle : record.status === 'done' ? CheckCircle : Clock;

        return (
          <div>
            <Space>
              <Tag color={statusColor} icon={<StatusIcon size={12} />}>
                {statusText}
              </Tag>
            </Space>
            {(record.status === 'parsing' || record.status === 'chunking' || record.status === 'embedding') && (
              <Progress percent={progressVal} size="small" style={{ marginTop: 4, width: 140 }} />
            )}
            {record.status === 'failed' && record.error_message && (
              <Tooltip title={record.error_message}>
                <Text type="danger" style={{ fontSize: 12, cursor: 'pointer' }}>
                  查看错误详情
                </Text>
              </Tooltip>
            )}
          </div>
        );
      },
    },
    {
      title: '分块数',
      dataIndex: 'chunk_count',
      key: 'chunk_count',
      width: 80,
      render: (n: number) => n || 0,
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (t: string) => formatDateTime(t),
    },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      render: (_: any, record: Document) => (
        <Space>
          <Button
            size="small"
            icon={<RefreshCw size={14} />}
            onClick={() => handleReparse(record.id)}
            disabled={record.status === 'parsing' || record.status === 'embedding' || record.status === 'chunking'}
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
      <Breadcrumb style={{ marginBottom: 16 }}>
        <Breadcrumb.Item>
          <a onClick={() => navigate('/knowledge-bases')} style={{ cursor: 'pointer' }}>
            知识库
          </a>
        </Breadcrumb.Item>
        <Breadcrumb.Item>{kb?.name || '加载中...'}</Breadcrumb.Item>
      </Breadcrumb>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            {kb?.name || '加载中...'}
          </Title>
          <Text type="secondary">{kb?.description || ''}</Text>
        </div>
        <Space>
          <Button icon={<Edit3 size={16} />} onClick={handleEditClick}>
            编辑
          </Button>
          <Button icon={<RefreshCw size={16} />} onClick={() => fetchDocuments(kbIdNum)} loading={loading}>
            刷新
          </Button>
          <Button type="primary" icon={<UploadIcon size={16} />} onClick={() => setUploadModal(true)}>
            上传文档
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
                  上传 PDF、DOCX、Markdown 或 TXT 文件开始构建知识库
                </Text>
              </span>
            }
          >
            <Button type="primary" icon={<UploadIcon size={14} />} onClick={() => setUploadModal(true)}>
              上传第一个文档
            </Button>
          </Empty>
        ) : (
          <Table
            dataSource={documents}
            columns={columns}
            rowKey="id"
            pagination={{ pageSize: 10 }}
          />
        )}
      </Card>

      <Modal
        title="上传文档"
        open={uploadModal}
        onCancel={() => setUploadModal(false)}
        footer={null}
      >
        <Upload.Dragger
          name="file"
          customRequest={({ file }) => handleUpload(file as File)}
          showUploadList={false}
          accept=".pdf,.docx,.md,.markdown,.txt"
          multiple={false}
          disabled={uploading}
        >
          <p className="ant-upload-drag-icon">
            <UploadIcon size={48} style={{ color: '#1677ff' }} />
          </p>
          <p className="ant-upload-text">
            {uploading ? '上传中...' : '点击或拖拽文件到此区域上传'}
          </p>
          <p className="ant-upload-hint">
            支持 PDF、DOCX、Markdown、TXT 格式，单个文件最大 50MB
          </p>
        </Upload.Dragger>
        {uploading && uploadProgress > 0 && (
          <Progress percent={uploadProgress} style={{ marginTop: 16 }} />
        )}
      </Modal>

      <Modal
        title="编辑知识库"
        open={editModal}
        onOk={handleEditSubmit}
        onCancel={() => setEditModal(false)}
        okText="保存"
        cancelText="取消"
      >
        <Form form={editForm} layout="vertical">
          <Form.Item
            name="name"
            label="知识库名称"
            rules={[{ required: true, message: '请输入知识库名称' }]}
          >
            <Input maxLength={100} placeholder="请输入知识库名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} maxLength={500} placeholder="请输入知识库描述（可选）" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
