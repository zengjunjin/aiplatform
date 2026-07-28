import { useState, useRef, useEffect } from 'react';
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
 *
 * Task 20 (P1-FE-06): 使用 AbortController, Modal 关闭/卸载时取消进行中的上传,
 * 避免后端继续处理已废弃的请求, 也避免取消后仍触发 setState。
 */
export default function DocumentUploadModal({ open, kbId, onClose, onUploaded }: Props) {
  const { t } = useTranslation();
  const { message } = AntdApp.useApp();
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  // 当前进行中的上传对应的 AbortController (单文件上传, 同一时刻最多一个)
  const abortControllerRef = useRef<AbortController | null>(null);

  const handleUpload = async (
    file: File,
    onSuccess?: (body: unknown) => void,
    onError?: (err: Error) => void,
  ) => {
    setUploading(true);
    setUploadProgress(0);
    // 为本次上传创建独立的 AbortController, 保存到 ref 供 onCancel / 卸载时 abort
    const controller = new AbortController();
    abortControllerRef.current = controller;
    try {
      const result = await documentApi.upload(kbId, file, (loaded, total) => {
        setUploadProgress(Math.round((loaded / total) * 100));
      }, controller.signal);
      // 主动 abort 后不应继续执行后续逻辑
      if (controller.signal.aborted) return;
      message.success(t('kb.uploadSuccess'));
      onSuccess?.(result);
      onClose();
      onUploaded();
    } catch (e: unknown) {
      // 主动 abort: 静默退出, 不弹错误 toast
      if (controller.signal.aborted) return;
      const errObj = e instanceof Error ? e : new Error(getErrorMessage(e));
      message.error(errObj.message || t('kb.uploadFailed'));
      onError?.(errObj);
      onClose();
    } finally {
      // 仅当 ref 仍指向当前 controller 时才清理 (避免覆盖后续上传的 controller)
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
      }
      setUploading(false);
      setUploadProgress(0);
    }
  };

  // Modal 关闭 / 组件卸载时取消进行中的上传
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
    };
  }, []);

  const handleCancel = () => {
    // 用户主动关闭 Modal: 取消进行中的上传
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    onClose();
  };

  return (
    <Modal
      title={t('kb.uploadModalTitle')}
      open={open}
      onCancel={handleCancel}
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
