import { useState, useEffect, useCallback } from 'react';
import { Modal, Space, Button, Typography, Spin, Skeleton, App as AntdApp, Tag } from 'antd';
import { ChevronLeft, ChevronRight, FileText } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { documentApi } from '../api';
import type { DocumentPreviewData } from '../api/documents';

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
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<DocumentPreviewData | null>(null);
  const [page, setPage] = useState(1);
  const { message } = AntdApp.useApp();

  const fetchPreview = useCallback(
    async (p: number) => {
      setLoading(true);
      try {
        const result = await documentApi.preview(docId, p, PAGE_SIZE);
        setData(result);
        setPage(result.page);
      } catch (e: any) {
        message.error(e.message || '预览失败');
        setData(null);
      } finally {
        setLoading(false);
      }
    },
    [docId, message],
  );

  useEffect(() => {
    if (open && docId > 0) {
      setPage(1);
      fetchPreview(1);
    }
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
          <FileText size={18} style={{ color: '#1677ff' }} />
          <span>{filename}</span>
          <Tag>{fileType.toUpperCase()}</Tag>
        </Space>
      }
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
            <Spin size="large" tip="加载中..." />
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
                  background: '#fafafa',
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
            borderTop: '1px solid #f0f0f0',
          }}
        >
          <Button
            icon={<ChevronLeft size={14} />}
            onClick={handlePrev}
            disabled={page <= 1 || loading}
            size="small"
          />
          <Text type="secondary" style={{ fontSize: 13 }}>
            {page} / {data.total_pages} 页 ({data.total_lines} 行)
          </Text>
          <Button
            icon={<ChevronRight size={14} />}
            onClick={handleNext}
            disabled={page >= data.total_pages || loading}
            size="small"
          />
        </div>
      )}
    </Modal>
  );
}