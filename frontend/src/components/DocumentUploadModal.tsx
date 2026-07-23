import { useState } from 'react';
import { Modal, Upload, Progress, App as AntdApp } from 'antd';
import { Upload as UploadIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { documentApi } from '../api';
import { getErrorMessage } from '../utils/errorReporter';

interface Props {
  open: boolean;
  kbId: number;
  onClose: () => void;
  onUploaded: () => void;
}

/**
 * 文档上传 Modal: 从 KnowledgeBaseDetailPage 拆出 (Task 27.1)
 * 内部维护 uploading/uploadProgress 状态, 上传成功后调用 onUploaded 通知父组件刷新列表.
 */
export default function DocumentUploadModal({ open, kbId, onClose, onUploaded }: Props) {
  const { t } = useTranslation();
  const { message } = AntdApp.useApp();
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);

  const handleUpload = async (
    file: File,
    onSuccess?: (body: unknown) => void,
    onError?: (err: Error) => void,
  ) => {
    setUploading(true);
    setUploadProgress(0);
    try {
      const result = await documentApi.upload(kbId, file, (loaded, total) => {
        setUploadProgress(Math.round((loaded / total) * 100));
      });
      message.success(t('kb.uploadSuccess'));
      onSuccess?.(result);
      onClose();
      onUploaded();
    } catch (e: unknown) {
      const errObj = e instanceof Error ? e : new Error(getErrorMessage(e));
      message.error(errObj.message || t('kb.uploadFailed'));
      onError?.(errObj);
      onClose();
    } finally {
      setUploading(false);
      setUploadProgress(0);
    }
  };

  return (
    <Modal
      title={t('kb.uploadModalTitle')}
      open={open}
      onCancel={onClose}
      transitionName=""
      maskTransitionName=""
      footer={null}
    >
      <Upload.Dragger
        name="file"
        customRequest={({ file, onSuccess, onError }) =>
          handleUpload(file as File, onSuccess, onError)
        }
        showUploadList={false}
        accept=".pdf,.docx,.md,.markdown,.txt"
        multiple={false}
        disabled={uploading}
      >
        <p className="ant-upload-drag-icon">
          <UploadIcon size={48} style={{ color: 'var(--accent-primary)' }} />
        </p>
        <p className="ant-upload-text">
          {uploading ? t('kb.uploading') : t('kb.uploadDragText')}
        </p>
        <p className="ant-upload-hint">{t('kb.uploadDragHint')}</p>
      </Upload.Dragger>
      {uploading && uploadProgress > 0 && (
        <Progress percent={uploadProgress} style={{ marginTop: 16 }} />
      )}
    </Modal>
  );
}
