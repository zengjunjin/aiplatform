import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import {
  Button,
  Table,
  Tag,
  Space,
  Typography,
  Modal,
  Progress,
  Popconfirm,
  App as AntdApp,
  Tooltip,
  Card,
  Skeleton,
  Empty,
  Form,
  Input,
  Steps,
} from 'antd';
import { useShallow } from 'zustand/react/shallow';
import {
  RefreshCw,
  Trash2,
  FileText,
  AlertCircle,
  CheckCircle,
  Clock,
  Eye,
  Upload as UploadIcon,
} from 'lucide-react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useKBStore } from '../store/kb';
import { formatFileSize, formatDateTime, getStatusColor, getStatusTextKey } from '../utils/format';
import type { Document, DocumentProgress } from '../types';
import DocumentPreviewModal from '../components/DocumentPreviewModal';
import DocumentUploadModal from '../components/DocumentUploadModal';
import KBCollaboratorModal from '../components/KBCollaboratorModal';
import KBBreadcrumbHeader from '../components/KBBreadcrumbHeader';
import { getErrorMessage, isFormValidationError } from '../utils/errorReporter';
import { useApiToast } from '../hooks/useApiToast';

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
  const [progressMap, setProgressMap] = useState<Record<number, DocumentProgress>>({});
  // Task 21: 通过 ref 读取最新的 progressMap，避免轮询更新导致 columns 频繁重建
  const progressMapRef = useRef(progressMap);
  progressMapRef.current = progressMap;
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

  // Task 52: useRef + 手动比较替代 pendingDocIds.join(',') 依赖, 移除 eslint-disable.
  // ID 集合不变时 (如 fetchDocuments 后 doc 对象引用变化但 pending ID 集合不变) 不重新触发轮询.
  // 通过 ref 管理清理函数, 使 effect 不返回 cleanup, 避免 docPage/docPageSize 等依赖变化时
  // cleanup 误取消正在进行的轮询.
  const prevPendingKeyRef = useRef('');
  const pollCleanupRef = useRef<(() => void) | null>(null);

  // Task 30: pollProgress 传入 signal，卸载时 abort 取消轮询中的 getProgress 请求
  useEffect(() => {
    const currentKey = pendingDocIds.join(',');
    // 手动值比较: ID 集合不变时跳过轮询重建
    if (currentKey === prevPendingKeyRef.current) return;
    prevPendingKeyRef.current = currentKey;

    // 清理上一次轮询
    pollCleanupRef.current?.();
    pollCleanupRef.current = null;

    if (pendingDocIds.length === 0) return;
    const controller = new AbortController();
    const stopFns: (() => void)[] = [];
    pendingDocIds.forEach((docId) => {
      const stop = pollProgress(
        docId,
        (p) => {
          setProgressMap((prev) => ({ ...prev, [docId]: p }));
          if (p.status === 'done' || p.status === 'failed') {
            fetchDocuments(kbIdNum, docPage, docPageSize);
          }
        },
        controller.signal,
      );
      stopFns.push(stop);
    });
    pollCleanupRef.current = () => {
      controller.abort();
      stopFns.forEach((fn) => fn());
    };
  }, [pendingDocIds, kbIdNum, pollProgress, fetchDocuments, docPage, docPageSize]);

  // 组件卸载时清理轮询
  useEffect(() => {
    return () => {
      pollCleanupRef.current?.();
    };
  }, []);

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
      render: (_: unknown, record: Document) => {
        const progress = progressMapRef.current[record.id];
        const currentStatus = progress?.status || record.status;
        const statusText = getStatusTextKey(currentStatus);
        const statusColor = getStatusColor(currentStatus);
        const progressVal = progress?.progress || 0;

        const StatusIcon = currentStatus === 'failed' ? AlertCircle : currentStatus === 'done' ? CheckCircle : Clock;

        // Task 38: 5 阶段 Stepper - pending → parsing → chunking → embedding → done
        // 当前阶段索引 + 进度条; failed 状态用红色 Tag 单独展示.
        const STAGES = ['pending', 'parsing', 'chunking', 'embedding', 'done'] as const;
        const stageIndex = STAGES.indexOf(currentStatus as typeof STAGES[number]);
        const isInPipeline = stageIndex >= 0 && stageIndex < STAGES.length - 1 && currentStatus !== 'failed';

        return (
          <div>
            <Space style={{ marginBottom: 4 }}>
              <Tag color={statusColor} icon={<StatusIcon size={12} />}>
                {statusText}
              </Tag>
            </Space>
            {isInPipeline ? (
              <>
                <Steps
                  size="small"
                  current={stageIndex}
                  style={{ marginTop: 4, maxWidth: 280 }}
                  items={STAGES.map((s) => ({
                    title: getStatusTextKey(s),
                  }))}
                />
                <Progress percent={progressVal} size="small" style={{ marginTop: 4, width: 280 }} />
              </>
            ) : currentStatus === 'done' ? (
              <Steps
                size="small"
                current={STAGES.length - 1}
                status="finish"
                style={{ marginTop: 4, maxWidth: 280 }}
                items={STAGES.map((s) => ({
                  title: getStatusTextKey(s),
                }))}
              />
            ) : null}
            {currentStatus === 'failed' && record.error_message && (
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
