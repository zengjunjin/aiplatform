/**
 * KnowledgeBaseDetailPage 子组件与 Hook（Task 6.3 SubTask 6.3.3 拆分）
 *
 * 从 KnowledgeBaseDetailPage.tsx 提取的独立单元：
 * 1. useDocumentProgressPolling - 文档进度轮询 Hook（含 AbortController + cleanup）
 * 2. DocumentStatusCell - 5 阶段状态列渲染（pending/parsing/chunking/embedding/done/failed）
 * 3. EditKBModal - 编辑知识库元信息弹窗
 *
 * 设计原则：
 * - 子组件不直接访问 store，所有数据通过 props 传递（单向数据流）
 * - Hook 返回 ref + progressMap，调用方通过 ref 读取最新值避免重渲染
 * - columns 定义保留在主文件（依赖 handlers/t/formatHelpers，提取后收益低）
 */
import { useEffect, useRef, useState } from 'react';
import type { MutableRefObject } from 'react';
import {
  Form,
  Input,
  Modal,
  Progress,
  Steps,
  Tag,
  Tooltip,
  Typography,
  Space,
} from 'antd';
import { AlertCircle, CheckCircle, Clock } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { FormInstance } from 'antd';
import type { Document, DocumentProgress } from '../types';
import { getStatusColor, getStatusTextKey } from '../utils/format';

const { Text } = Typography;

// 5 阶段流水线（与后端 document_task.py 状态一致）
const STAGES = ['pending', 'parsing', 'chunking', 'embedding', 'done'] as const;

/**
 * 文档进度轮询 Hook。
 *
 * 职责：
 * - 监听 pendingDocIds 变化，启动/停止轮询
 * - 维护 progressMap state 与 progressMapRef（ref 用于 columns 渲染时读取最新值）
 * - 通过 AbortController 在卸载/重置时取消进行中的 getProgress 请求
 *
 * 注意：本 hook 不直接订阅 store，由调用方传入 pendingDocIds 与 pollProgress 函数。
 * 这样保证 hook 纯粹性，便于单测。
 *
 * @param pendingDocIds 仍处于处理中的文档 ID 列表
 * @param pollProgress  store 的轮询函数
 * @param onDocFinished 文档完成时的回调（通常触发 fetchDocuments 刷新列表）
 * @returns progressMap state + progressMapRef
 */
export function useDocumentProgressPolling(
  pendingDocIds: number[],
  pollProgress: (
    docId: number,
    onUpdate: (p: DocumentProgress) => void,
    signal: AbortSignal,
  ) => () => void,
  onDocFinished: () => void,
) {
  const [progressMap, setProgressMap] = useState<Record<number, DocumentProgress>>({});
  // Task 21: 通过 ref 读取最新的 progressMap，避免轮询更新导致 columns 频繁重建
  const progressMapRef = useRef(progressMap);
  progressMapRef.current = progressMap;

  // Task 52: useRef + 手动比较替代 pendingDocIds.join(',') 依赖, 移除 eslint-disable.
  // ID 集合不变时 (如 fetchDocuments 后 doc 对象引用变化但 pending ID 集合不变) 不重新触发轮询.
  // 通过 ref 管理清理函数, 使 effect 不返回 cleanup, 避免 docPage/docPageSize 等依赖变化时
  // cleanup 误取消正在进行的轮询.
  const prevPendingKeyRef = useRef('');
  const pollCleanupRef = useRef<(() => void) | null>(null);

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
            onDocFinished();
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
  }, [pendingDocIds, pollProgress, onDocFinished]);

  // 组件卸载时清理轮询
  useEffect(() => {
    return () => {
      pollCleanupRef.current?.();
    };
  }, []);

  return { progressMap, progressMapRef };
}

interface DocumentStatusCellProps {
  record: Document;
  // ref 而非 value：避免每次 progress 更新都重建 columns（Task 21）
  progressMapRef: MutableRefObject<Record<number, DocumentProgress>>;
}

/**
 * 文档状态列渲染单元。
 *
 * 显示规则：
 * - pending/parsing/chunking/embedding: 5 阶段 Steps + 进度条
 * - done: Steps 全部 finish
 * - failed: 红色 Tag + 错误详情 Tooltip
 */
export function DocumentStatusCell({ record, progressMapRef }: DocumentStatusCellProps) {
  const { t } = useTranslation();
  const progress = progressMapRef.current[record.id];
  const currentStatus = progress?.status || record.status;
  const statusText = getStatusTextKey(currentStatus);
  const statusColor = getStatusColor(currentStatus);
  const progressVal = progress?.progress || 0;

  const StatusIcon = currentStatus === 'failed' ? AlertCircle : currentStatus === 'done' ? CheckCircle : Clock;

  // Task 38: 5 阶段 Stepper - pending → parsing → chunking → embedding → done
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
}

interface EditKBModalProps {
  open: boolean;
  form: FormInstance;
  initialName?: string;
  initialDescription?: string;
  onCancel: () => void;
  onSubmit: () => Promise<void>;
}

/**
 * 编辑知识库元信息弹窗。
 *
 * 提交逻辑由父组件控制（onSubmit），便于复用 + 单测。
 * 表单校验失败（isFormValidationError）静默返回，其他错误抛给父组件处理。
 */
export function EditKBModal({
  open,
  form,
  initialName = '',
  initialDescription = '',
  onCancel,
  onSubmit,
}: EditKBModalProps) {
  const { t } = useTranslation();

  // open 状态变化时同步初始值
  useEffect(() => {
    if (open) {
      form.setFieldsValue({
        name: initialName,
        description: initialDescription,
      });
    }
  }, [open, form, initialName, initialDescription]);

  return (
    <Modal
      title={t('kb.editKB')}
      open={open}
      onOk={onSubmit}
      onCancel={onCancel}
      transitionName=""
      maskTransitionName=""
      okText={t('kb.save')}
      cancelText={t('kb.cancel')}
    >
      <Form form={form} layout="vertical">
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
  );
}
