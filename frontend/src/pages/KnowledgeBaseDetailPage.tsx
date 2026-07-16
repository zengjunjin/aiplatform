import { useState, useEffect, useCallback } from 'react';
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
  Select,
  Divider,
  List,
  Avatar,
  AutoComplete,
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
  Users,
  UserPlus,
  UserX,
  Eye,
} from 'lucide-react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useKBStore } from '../store/kb';
import { documentApi, kbApi } from '../api';
import authApi from '../api/auth';
import { formatFileSize, formatDateTime, getStatusColor, getStatusText } from '../utils/format';
import type { Document, DocumentProgress, CollaboratorInfo } from '../types';
import DocumentPreviewModal from '../components/DocumentPreviewModal';

const { Title, Text } = Typography;

export default function KnowledgeBaseDetailPage() {
  const { t } = useTranslation();
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
  const [collabModal, setCollabModal] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [progressMap, setProgressMap] = useState<Record<number, DocumentProgress>>({});
  const [collaborators, setCollaborators] = useState<CollaboratorInfo[]>([]);
  const [collabLoading, setCollabLoading] = useState(false);
  const [previewDoc, setPreviewDoc] = useState<Document | null>(null);
  const [docPage, setDocPage] = useState(1);
  const [docPageSize, setDocPageSize] = useState(20);
  const [addCollabForm] = Form.useForm();
  const [editForm] = Form.useForm();
  const { message } = AntdApp.useApp();

  // 用户搜索（协作者添加）
  const [userOptions, setUserOptions] = useState<{ value: number; label: string }[]>([]);
  const [searching, setSearching] = useState(false);

  const handleUserSearch = useCallback(async (query: string) => {
    if (!query || query.length < 1) {
      setUserOptions([]);
      return;
    }
    setSearching(true);
    try {
      const users = await authApi.searchUsers(query);
      setUserOptions(users.map((u) => ({ value: u.id, label: `${u.username} (ID: ${u.id})` })));
    } catch {
      setUserOptions([]);
    } finally {
      setSearching(false);
    }
  }, []);

  const kbIdNum = parseInt(kbId || '0', 10);
  const kb = knowledgeBases.find((k) => k.id === kbIdNum);
  const documents = useKBStore((s) => s.documents[kbIdNum] || []);
  const docTotal = useKBStore((s) => s.docTotal[kbIdNum] || 0);
  const loading = useKBStore((s) => s.loadingDocs[kbIdNum] || false);

  useEffect(() => {
    if (kbIdNum > 0) {
      fetchKBs();
      fetchDocuments(kbIdNum, docPage, docPageSize);
    }
  }, [kbIdNum, fetchKBs, fetchDocuments, docPage, docPageSize]);

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
          fetchDocuments(kbIdNum, docPage, docPageSize);
        }
      });
      stopFns.push(stop);
    });
    return () => stopFns.forEach((fn) => fn());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingDocIds, kbIdNum]);

  const handleUpload = async (file: File, onSuccess?: (body: any) => void, onError?: (err: Error) => void) => {
    setUploading(true);
    setUploadProgress(0);
    try {
      const result = await documentApi.upload(kbIdNum, file, (loaded, total) => {
        setUploadProgress(Math.round((loaded / total) * 100));
      });
      message.success(t('kb.uploadSuccess'));
      onSuccess?.(result);
      setUploadModal(false);
      fetchDocuments(kbIdNum, docPage, docPageSize);
    } catch (e: any) {
      message.error(e.message || t('kb.uploadFailed'));
      onError?.(e);
      setUploadModal(false);
    } finally {
      setUploading(false);
      setUploadProgress(0);
    }
  };

  const handleReparse = async (docId: number) => {
    try {
      await reparseDocument(kbIdNum, docId);
      message.success(t('kb.reparsed'));
    } catch (e: any) {
      message.error(e.message || t('kb.operationFailed'));
    }
  };

  const handleDelete = async (docId: number) => {
    try {
      await deleteDocument(kbIdNum, docId);
      message.success(t('kb.deleteSuccess'));
    } catch (e: any) {
      message.error(e.message || t('kb.deleteFailed'));
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
      message.success(t('kb.updateSuccess'));
      setEditModal(false);
    } catch (e: any) {
      if (e.errorFields) return;
      message.error(e.message || t('kb.updateFailed'));
      setEditModal(false);
    }
  };

  const fetchCollaborators = async () => {
    setCollabLoading(true);
    try {
      const data = await kbApi.getCollaborators(kbIdNum);
      setCollaborators(data);
    } catch (e: any) {
      message.error(e.message || 'Failed to load collaborators');
    } finally {
      setCollabLoading(false);
    }
  };

  const handleOpenCollab = () => {
    setCollabModal(true);
    fetchCollaborators();
  };

  const handleAddCollaborator = async () => {
    try {
      const values = await addCollabForm.validateFields();
      await kbApi.addCollaborator(kbIdNum, values);
      message.success(t('kb.collaboratorAdded'));
      addCollabForm.resetFields();
      fetchCollaborators();
    } catch (e: any) {
      if (e.errorFields) return;
      message.error(e.message || t('kb.operationFailed'));
    }
  };

  const handleRemoveCollaborator = async (userId: number) => {
    try {
      await kbApi.removeCollaborator(kbIdNum, userId);
      message.success(t('kb.collaboratorRemoved'));
      fetchCollaborators();
    } catch (e: any) {
      message.error(e.message || t('kb.operationFailed'));
    }
  };

  const columns = [
    {
      title: t('kb.filename'),
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
      title: t('kb.type'),
      dataIndex: 'file_type',
      key: 'file_type',
      width: 80,
      render: (type: string) => <Tag>{type.toUpperCase()}</Tag>,
    },
    {
      title: t('kb.size'),
      dataIndex: 'file_size',
      key: 'file_size',
      width: 100,
      render: (size: number) => formatFileSize(size),
    },
    {
      title: t('kb.status'),
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
                  {t('kb.viewErrorDetails')}
                </Text>
              </Tooltip>
            )}
          </div>
        );
      },
    },
    {
      title: t('kb.chunkCount'),
      dataIndex: 'chunk_count',
      key: 'chunk_count',
      width: 80,
      render: (n: number) => n || 0,
    },
    {
      title: t('kb.uploadTime'),
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (t: string) => formatDateTime(t),
    },
    {
      title: t('kb.actions'),
      key: 'actions',
      width: 200,
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
            disabled={record.status === 'parsing' || record.status === 'embedding' || record.status === 'chunking'}
          >
            {t('kb.reparse')}
          </Button>
          <Popconfirm
            title={t('kb.deleteDocConfirmTitle')}
            description={t('kb.deleteDocConfirmDesc')}
            onConfirm={() => handleDelete(record.id)}
            okText={t('kb.delete')}
            cancelText={t('kb.cancel')}
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
            {t('kb.kb')}
          </a>
        </Breadcrumb.Item>
        <Breadcrumb.Item>{kb?.name || t('common.loading')}</Breadcrumb.Item>
      </Breadcrumb>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            {kb?.name || t('common.loading')}
          </Title>
          <Text type="secondary">{kb?.description || ''}</Text>
        </div>
        <Space>
          <Button icon={<Edit3 size={16} />} onClick={handleEditClick}>
            {t('kb.edit')}
          </Button>
          <Button icon={<Users size={16} />} onClick={handleOpenCollab}>
            {t('kb.collaborators')}
          </Button>
          <Button icon={<RefreshCw size={16} />} onClick={() => fetchDocuments(kbIdNum, docPage, docPageSize)} loading={loading}>
            {t('kb.refresh')}
          </Button>
          <Button type="primary" icon={<UploadIcon size={16} />} onClick={() => setUploadModal(true)}>
            {t('kb.uploadDocument')}
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
                {t('kb.noDocuments')}
                <br />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t('kb.uploadHint')}
                </Text>
              </span>
            }
          >
            <Button type="primary" icon={<UploadIcon size={14} />} onClick={() => setUploadModal(true)}>
              {t('kb.uploadFirstDoc')}
            </Button>
          </Empty>
        ) : (
          <Table
            dataSource={documents}
            columns={columns}
            rowKey="id"
            pagination={{
              current: docPage,
              pageSize: docPageSize,
              total: docTotal,
              showSizeChanger: true,
              onChange: (p, ps) => {
                setDocPage(p);
                setDocPageSize(ps);
              },
            }}
          />
        )}
      </Card>

      <Modal
        title={t('kb.uploadModalTitle')}
        open={uploadModal}
        onCancel={() => setUploadModal(false)}
        transitionName=""
        maskTransitionName=""
        footer={null}
      >
        <Upload.Dragger
          name="file"
          customRequest={({ file, onSuccess, onError }) => handleUpload(file as File, onSuccess, onError)}
          showUploadList={false}
          accept=".pdf,.docx,.md,.markdown,.txt"
          multiple={false}
          disabled={uploading}
        >
          <p className="ant-upload-drag-icon">
            <UploadIcon size={48} style={{ color: '#1677ff' }} />
          </p>
          <p className="ant-upload-text">
            {uploading ? t('kb.uploading') : t('kb.uploadDragText')}
          </p>
          <p className="ant-upload-hint">
            {t('kb.uploadDragHint')}
          </p>
        </Upload.Dragger>
        {uploading && uploadProgress > 0 && (
          <Progress percent={uploadProgress} style={{ marginTop: 16 }} />
        )}
      </Modal>

      <Modal
        title={t('kb.editKB')}
        open={editModal}
        onOk={handleEditSubmit}
        onCancel={() => setEditModal(false)}
        transitionName=""
        maskTransitionName=""
        okText={t('kb.save')}
        cancelText={t('kb.cancel')}
      >
        <Form form={editForm} layout="vertical">
          <Form.Item
            name="name"
            label={t('kb.kbNameLabel')}
            rules={[{ required: true, message: t('kb.kbNameRequired') }]}
          >
            <Input maxLength={100} placeholder={t('kb.kbNameInputPlaceholder')} />
          </Form.Item>
          <Form.Item name="description" label={t('kb.description')}>
            <Input.TextArea rows={3} maxLength={500} placeholder={t('kb.descriptionOptional')} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t('kb.collaborators')}
        open={collabModal}
        onCancel={() => { setCollabModal(false); addCollabForm.resetFields(); }}
        transitionName=""
        maskTransitionName=""
        footer={null}
        width={500}
      >
        <Divider orientation="left" style={{ fontSize: 13, marginTop: 0 }}>
          {t('kb.addCollaborator')}
        </Divider>
        <Form form={addCollabForm} layout="inline" style={{ marginBottom: 16 }}>
          <Form.Item
            name="user_id"
            rules={[{ required: true, message: t('kb.userIdRequired') }]}
          >
            <AutoComplete
              options={userOptions}
              onSearch={handleUserSearch}
              placeholder={t('kb.userSearchPlaceholder')}
              style={{ width: 200 }}
              notFoundContent={searching ? t('kb.searching') : t('kb.noUserFound')}
            />
          </Form.Item>
          <Form.Item
            name="permission"
            rules={[{ required: true, message: t('kb.permissionRequired') }]}
          >
            <Select style={{ width: 120 }} placeholder={t('kb.permission')}>
              <Select.Option value="read">{t('kb.permRead')}</Select.Option>
              <Select.Option value="write">{t('kb.permWrite')}</Select.Option>
              <Select.Option value="admin">{t('kb.permAdmin')}</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item>
            <Button type="primary" icon={<UserPlus size={14} />} onClick={handleAddCollaborator}>
              {t('kb.add')}
            </Button>
          </Form.Item>
        </Form>

        <Divider orientation="left" style={{ fontSize: 13 }}>
          {t('kb.currentCollaborators')}
        </Divider>
        {collabLoading ? (
          <Skeleton active paragraph={{ rows: 3 }} />
        ) : collaborators.length === 0 ? (
          <Empty description={t('kb.noCollaborators')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <List
            dataSource={collaborators}
            renderItem={(item: CollaboratorInfo) => (
              <List.Item
                actions={[
                  <Popconfirm
                    key="remove"
                    title={t('kb.removeCollaboratorConfirm')}
                    onConfirm={() => handleRemoveCollaborator(item.user_id)}
                    okText={t('kb.delete')}
                    cancelText={t('kb.cancel')}
                  >
                    <Button size="small" danger icon={<UserX size={14} />} />
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  avatar={<Avatar icon={<Users size={16} />} />}
                  title={item.username}
                  description={
                    <Tag color={item.permission === 'admin' ? 'red' : item.permission === 'write' ? 'blue' : 'default'}>
                      {item.permission === 'admin' ? t('kb.permAdmin') : item.permission === 'write' ? t('kb.permWrite') : t('kb.permRead')}
                    </Tag>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Modal>

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
