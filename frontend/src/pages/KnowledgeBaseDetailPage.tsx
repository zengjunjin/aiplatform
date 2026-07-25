import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Button,
  Table,
  Tag,
  Space,
  Typography,
  Popconfirm,
  App as AntdApp,
  Card,
  Skeleton,
  Empty,
  Form,
} from 'antd';
import { useShallow } from 'zustand/react/shallow';
import {
  RefreshCw,
  Trash2,
  FileText,
  Eye,
  Upload as UploadIcon,
} from 'lucide-react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useKBStore } from '../store/kb';
import { formatFileSize, formatDateTime } from '../utils/format';
import type { Document } from '../types';
import DocumentPreviewModal from '../components/DocumentPreviewModal';
import DocumentUploadModal from '../components/DocumentUploadModal';
import KBCollaboratorModal from '../components/KBCollaboratorModal';
import KBBreadcrumbHeader from '../components/KBBreadcrumbHeader';
import { getErrorMessage, isFormValidationError } from '../utils/errorReporter';
import { useApiToast } from '../hooks/useApiToast';
import { useDocumentProgressPolling, DocumentStatusCell, EditKBModal } from './KnowledgeBaseDetailPage.parts';

const { Text } = Typography;

export default function KnowledgeBaseDetailPage() {
  const { t } = useTranslation();
  const { kbId } = useParams<{ kbId: string }>();
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
  const [previewDoc, setPreviewDoc] = useState<Document | null>(null);
  const [docPage, setDocPage] = useState(1);
  const [docPageSize, setDocPageSize] = useState(20);
  const [editForm] = Form.useForm();
  const { message } = AntdApp.useApp();
  const { runWithToast } = useApiToast();

  const kbIdNum = parseInt(kbId || '0', 10);
  const kb = knowledgeBases.find((k) => k.id === kbIdNum);
  // useShallow: documents 数组元素引用不变时, 返回旧引用避免重渲染
  // (fetchDocuments 后即使 doc 对象引用全变, useShallow 也会做浅比较决定是否触发更新)
  const documents = useKBStore(
    useShallow((s) => s.documents[kbIdNum] || [])
  );
  const docTotal = useKBStore((s) => s.docTotal[kbIdNum] || 0);
  const loading = useKBStore((s) => s.loadingDocs[kbIdNum] || false);

  // Task 30: mount 时创建 AbortController，卸载时取消 fetchKBs/fetchDocuments
  useEffect(() => {
    if (kbIdNum <= 0) return;
    const controller = new AbortController();
    fetchKBs(controller.signal);
    fetchDocuments(kbIdNum, docPage, docPageSize, controller.signal);
    return () => controller.abort();
  }, [kbIdNum, fetchKBs, fetchDocuments, docPage, docPageSize]);

  // pendingDocIds: 仍处于处理中 (非 done/failed) 的文档 ID 数组, 用 useMemo 缓存避免每次 render 重算
  const pendingDocIds = useMemo(
    () => documents.filter((d) => d.status !== 'done' && d.status !== 'failed').map((d) => d.id),
    [documents]
  );

  // 文档完成时刷新列表（useCallback 保证 hook 内 effect 依赖稳定）
  const handleDocFinished = useCallback(() => {
    fetchDocuments(kbIdNum, docPage, docPageSize);
  }, [fetchDocuments, kbIdNum, docPage, docPageSize]);

  // Task 6.3: 轮询逻辑提取到 useDocumentProgressPolling hook（见 KnowledgeBaseDetailPage.parts.tsx）
  // progressMap 用于 columns deps 触发 Table 重渲染；progressMapRef 用于渲染时读取最新值
  const { progressMap, progressMapRef } = useDocumentProgressPolling(
    pendingDocIds,
    pollProgress,
    handleDocFinished,
  );

  const handleReparse = useCallback(async (docId: number, force: boolean = false) => {
    await runWithToast(() => reparseDocument(kbIdNum, docId, force), {
      successKey: 'kb.reparsed',
      errorKey: 'kb.operationFailed',
    });
  }, [runWithToast, reparseDocument, kbIdNum]);

  const handleDelete = useCallback(async (docId: number) => {
    await runWithToast(() => deleteDocument(kbIdNum, docId), {
      successKey: 'kb.deleteSuccess',
      errorKey: 'kb.deleteFailed',
    });
  }, [runWithToast, deleteDocument, kbIdNum]);

  // Task 6.3: 表单初始值由 EditKBModal 内部 useEffect 根据 initialName/initialDescription 设置
  const handleEditClick = () => setEditModal(true);

  const handleEditSubmit = async () => {
    try {
      const values = await editForm.validateFields();
      await updateKB(kbIdNum, values.name, values.description || '');
      message.success(t('kb.updateSuccess'));
      setEditModal(false);
    } catch (e: unknown) {
      if (isFormValidationError(e)) return;
      message.error(getErrorMessage(e) || t('kb.updateFailed'));
      setEditModal(false);
    }
  };

  const refreshDocuments = () => fetchDocuments(kbIdNum, docPage, docPageSize);

  const columns = useMemo(() => [
    {
      title: t('kb.filename'),
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
      width: 320,
      render: (_: unknown, record: Document) => (
        <DocumentStatusCell record={record} progressMapRef={progressMapRef} />
      ),
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
            onClick={() => handleReparse(record.id, record.status === 'parsing' || record.status === 'embedding' || record.status === 'chunking')}
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
            <Button size="small" danger icon={<Trash2 size={14} />} aria-label={t('kb.delete')} />
          </Popconfirm>
        </Space>
      ),
    },
  // eslint-disable-next-line react-hooks/exhaustive-deps -- progressMapRef 是 ref，不应作为依赖
  ], [t, progressMap, handleReparse, handleDelete, setPreviewDoc]);

  return (
    <div>
      <KBBreadcrumbHeader
        kb={kb}
        loading={loading}
        onEditClick={handleEditClick}
        onCollabClick={() => setCollabModal(true)}
        onRefreshClick={refreshDocuments}
        onUploadClick={() => setUploadModal(true)}
      />

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

      <DocumentUploadModal
        open={uploadModal}
        kbId={kbIdNum}
        onClose={() => setUploadModal(false)}
        onUploaded={refreshDocuments}
      />

      <EditKBModal
        open={editModal}
        form={editForm}
        initialName={kb?.name || ''}
        initialDescription={kb?.description || ''}
        onCancel={() => setEditModal(false)}
        onSubmit={handleEditSubmit}
      />

      <KBCollaboratorModal
        open={collabModal}
        kbId={kbIdNum}
        onClose={() => setCollabModal(false)}
      />

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
