import { useMemo } from 'react';
import { Modal, Form, Select, Input } from 'antd';
import { useTranslation } from 'react-i18next';
import type { KnowledgeBase } from '../types';

interface NewSessionValues {
  kb_id?: number;
  title?: string;
}

interface Props {
  open: boolean;
  knowledgeBases: KnowledgeBase[];
  onSubmit: (values: NewSessionValues) => Promise<void>;
  onCancel: () => void;
  afterClose: () => void;
}

/**
 * 新建对话弹窗: 从 ChatPage 拆出 (Task 27.4)
 * 内部管理 form 实例, 提交时调用 onSubmit 传入 values, 由父组件发起实际创建.
 */
export default function NewSessionModal({
  open,
  knowledgeBases,
  onSubmit,
  onCancel,
  afterClose,
}: Props) {
  const { t } = useTranslation();
  const [form] = Form.useForm<NewSessionValues>();

  const kbOptions = useMemo(() => knowledgeBases.map((kb) => ({
    label: `${kb.name} (${kb.doc_count || 0} ${t('kb.documents', { count: kb.doc_count || 0 })})`,
    value: kb.id,
  })), [knowledgeBases, t]);

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      await onSubmit(values);
      form.resetFields();
    } catch {
      // 表单校验失败, 不关闭弹窗
    }
  };

  const handleCancel = () => {
    onCancel();
    form.resetFields();
  };

  return (
    <Modal
      title={t('chat.newChat')}
      open={open}
      onOk={handleOk}
      onCancel={handleCancel}
      afterClose={afterClose}
      destroyOnClose
      transitionName=""
      maskTransitionName=""
      okText={t('chat.create')}
      cancelText={t('chat.cancel')}
    >
      <Form form={form} layout="vertical">
        <Form.Item name="kb_id" label={t('chat.selectKB')}>
          <Select
            placeholder={t('chat.selectKBPlaceholder')}
            allowClear
            options={kbOptions}
          />
        </Form.Item>
        <Form.Item name="title" label={t('chat.sessionTitleOptional')}>
          <Input placeholder={t('chat.sessionTitleHint')} maxLength={100} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
