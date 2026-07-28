import { useState, useEffect, useCallback, useRef } from 'react';
import { Modal, Space, Button, Typography, Spin, Skeleton, App as AntdApp, Tag } from 'antd';
import { ChevronLeft, ChevronRight, FileText } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { useTranslation } from 'react-i18next';
import { documentApi } from '../api';
import type { DocumentPreviewData } from '../api/documents';
import { getErrorMessage } from '../utils/errorReporter';

const { Text } = Typography;

interface DocumentPreviewModalProps {
  open: boolean;
  docId: number;
  filename: string;
  fileType: string;
  onClose: () => void;
}

const PAGE_SIZE = 50;

export default function DocumentPreviewModal({
  open,
  docId,
  filename,
  fileType,
  onClose,
}: DocumentPreviewModalProps) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<DocumentPreviewData | null>(null);
  const [page, setPage] = useState(1);
  const { message } = AntdApp.useApp();
  // Task 23 (P1-FE-09): ref 持有当前进行中的 AbortController, 翻页/卸载时 abort 上一次请求
  const abortControllerRef = useRef<AbortController | null>(null);

  const fetchPreview = useCallback(
    async (p: number) => {
      // 取消上一次进行中的请求 (翻页场景)
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      const controller = new AbortController();
      abortControllerRef.current = controller;
      setLoading(true);
      try {
        const result = await documentApi.preview(docId, p, PAGE_SIZE, controller.signal);
        if (controller.signal.aborted) return;
        setData(result);
        setPage(result.page);
      } catch (e: unknown) {
        if (controller.signal.aborted) return;
        message.error(getErrorMessage(e) || t('documentPreview.loadFailed'));
        setData(null);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    },
    [docId, message, t],
  );

  // Task 23 (P1-FE-09): AbortController 防止组件卸载后 setState
  useEffect(() => {
    if (!open || docId <= 0) return;
    setPage(1);
    fetchPreview(1);
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
    };
  }, [open, docId, fetchPreview]);

  const handlePrev = () => {
    if (data && page > 1) {
      fetchPreview(page - 1);
    }
  };

  const handleNext = () => {
    if (data && page < data.total_pages) {
      fetchPreview(page + 1);
    }
  };

  const isMarkdown = fileType === 'md' || fileType === 'markdown';

  return (
    <Modal
      title={
        <Space>
          <FileText size={18} style={{ color: 'var(--accent-primary)' }} />
          <span>{filename}</span>
          <Tag>{fileType.toUpperCase()}</Tag>
        </Space>
      }
      transitionName=""
      maskTransitionName=""
      open={open}
      onCancel={onClose}
      footer={null}
      width={800}
      style={{ top: 20 }}
      destroyOnClose
    >
      <div style={{ minHeight: 400, maxHeight: '60vh', overflow: 'auto' }}>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 60 }}>
            <Spin size="large" tip={t('common.loading')} />
          </div>
        ) : data ? (
          <div>
            {isMarkdown ? (
              <div style={{ padding: '0 8px' }}>
                <ReactMarkdown>{data.content}</ReactMarkdown>
              </div>
            ) : (
              <pre
                style={{
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  fontFamily: 'monospace',
                  fontSize: 13,
                  lineHeight: 1.7,
                  padding: '8px 12px',
                  margin: 0,
                  background: 'var(--bg-tertiary)',
                  borderRadius: 4,
                }}
              >
                {data.content}
              </pre>
            )}
          </div>
        ) : (
          <Skeleton active paragraph={{ rows: 10 }} />
        )}
      </div>

      {data && data.total_pages > 0 && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            gap: 12,
            marginTop: 16,
            paddingTop: 12,
            borderTop: '1px solid var(--border-color)',
          }}
        >
          <Button
            icon={<ChevronLeft size={14} />}
            onClick={handlePrev}
            disabled={page <= 1 || loading}
            size="small"
            aria-label={t('documentPreview.prevPage')}
          />
          <Text type="secondary" style={{ fontSize: 13 }}>
            {t('documentPreview.pageInfo', { page, total: data.total_pages, lines: data.total_lines })}
          </Text>
          <Button
            icon={<ChevronRight size={14} />}
            onClick={handleNext}
            disabled={page >= data.total_pages || loading}
            size="small"
            aria-label={t('documentPreview.nextPage')}
          />
        </div>
      )}
    </Modal>
  );
}