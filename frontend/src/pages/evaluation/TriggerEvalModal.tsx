import { useMemo } from 'react';
import { Modal, Form, Select, InputNumber, Card, Space, Typography } from 'antd';
import { Clock, Coins, Info } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { isFormValidationError } from '../../utils/errorReporter';

const { Text } = Typography;

// Task 58: 评估耗时与 token 估算系数
// 基准：每题约 3 秒、约 1500 tokens（输入+输出）
const ESTIMATE_SECONDS_PER_QUESTION = 3;
const ESTIMATE_TOKENS_PER_QUESTION = 1500;

export interface TriggerEvalValues {
  kb_id: number;
  num_questions: number;
}

interface TriggerEvalModalProps {
  open: boolean;
  kbs: { id: number; name: string }[];
  /** 返回 true 表示触发成功（父组件已处理 toast + 关闭 modal + 进度面板） */
  onTrigger: (values: TriggerEvalValues) => Promise<boolean>;
  onCancel: () => void;
}

/**
 * Task 4.1: 从 EvaluationPage 抽出的触发评估弹窗。
 * 内部维护 Form 实例与实时估算面板；通过 onTrigger 回调把表单值传给父组件。
 * Task 5.6: kbOptions 用 useMemo 缓存。
 */
export default function TriggerEvalModal({ open, kbs, onTrigger, onCancel }: TriggerEvalModalProps) {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  // Task 58: 监听 num_questions 字段实时计算估算
  const numQuestionsValue = Form.useWatch('num_questions', form) as number | undefined;

  // Task 58: 实时估算（基于 num_questions 字段）
  const estimate = useMemo(() => {
    const n = typeof numQuestionsValue === 'number' && numQuestionsValue > 0 ? numQuestionsValue : 50;
    const totalSeconds = n * ESTIMATE_SECONDS_PER_QUESTION;
    const minutes = Math.max(1, Math.round(totalSeconds / 60));
    const tokensK = Math.max(1, Math.round((n * ESTIMATE_TOKENS_PER_QUESTION) / 1000));
    return { n, minutes, tokensK };
  }, [numQuestionsValue]);

  // Task 5.6: kbOptions useMemo 缓存，避免每次渲染新建数组
  const kbOptions = useMemo(
    () => kbs.map((kb) => ({ label: kb.name, value: kb.id })),
    [kbs],
  );

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      const ok = await onTrigger({
        kb_id: values.kb_id,
        num_questions: values.num_questions || 50,
      });
      if (ok) {
        form.resetFields();
      }
    } catch (e) {
      if (isFormValidationError(e)) return;
      // 其他错误由父组件 onTrigger 内部处理 toast，这里吞掉避免 antd Modal 抛 reject
    }
  };

  const handleCancel = () => {
    onCancel();
    form.resetFields();
  };

  return (
    <Modal
      title={t('evaluation.triggerModalTitle')}
      open={open}
      onOk={handleOk}
      onCancel={handleCancel}
      transitionName=""
      maskTransitionName=""
      okText={t('evaluation.startEval')}
      cancelText={t('common.cancel')}
      centered
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="kb_id"
          label={t('evaluation.selectKB')}
          rules={[{ required: true, message: t('evaluation.selectKBRequired') }]}
        >
          <Select
            placeholder={t('evaluation.selectKBPlaceholder')}
            options={kbOptions}
          />
        </Form.Item>
        <Form.Item
          name="num_questions"
          label={t('evaluation.questionCount')}
          initialValue={50}
        >
          <InputNumber min={5} max={200} style={{ width: '100%' }} />
        </Form.Item>
        {/* Task 58: 实时估算面板 */}
        <Card
          size="small"
          style={{
            marginBottom: 12,
            background: 'var(--bg-tertiary)',
            border: '1px dashed var(--border-color)',
          }}
          styles={{ body: { padding: 12 } }}
        >
          <Space size={24} wrap>
            <Space size={6}>
              <Clock size={14} color="var(--accent-primary)" />
              <Text style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                {t('evaluation.estimateTime')}:
              </Text>
              <Text strong style={{ fontSize: 12, color: 'var(--accent-primary)' }}>
                {t('evaluation.estimateTimeValue', { minutes: estimate.minutes })}
              </Text>
            </Space>
            <Space size={6}>
              <Coins size={14} color="var(--accent-secondary)" />
              <Text style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                {t('evaluation.estimateTokens')}:
              </Text>
              <Text strong style={{ fontSize: 12, color: 'var(--accent-secondary)' }}>
                {t('evaluation.estimateTokensValue', { tokens: estimate.tokensK })}
              </Text>
            </Space>
          </Space>
          <div style={{ marginTop: 8, display: 'flex', alignItems: 'flex-start', gap: 4 }}>
            <Info size={12} color="var(--text-tertiary)" style={{ flexShrink: 0, marginTop: 2 }} />
            <Text style={{ fontSize: 11, color: 'var(--text-tertiary)', lineHeight: 1.5 }}>
              {t('evaluation.estimateHint')}
            </Text>
          </div>
        </Card>
      </Form>
    </Modal>
  );
}
