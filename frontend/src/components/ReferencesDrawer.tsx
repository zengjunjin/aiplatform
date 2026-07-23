import { Drawer, Tag, Card } from 'antd';
import { FileText } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { Reference } from '../types';

interface Props {
  open: boolean;
  refs: Reference[];
  onClose: () => void;
}

/**
 * 参考来源抽屉: 从 ChatPage 拆出 (Task 27.4)
 * 纯展示组件, refs 由父组件传入.
 */
export default function ReferencesDrawer({ open, refs, onClose }: Props) {
  const { t } = useTranslation();

  return (
    <Drawer
      title={t('chat.references')}
      placement="right"
      onClose={onClose}
      open={open}
      width={420}
    >
      {refs.map((ref, i) => (
        <Card key={ref.chunk_id || `${ref.doc_id}-${i}`} size="small" style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <Tag color="blue">[{i + 1}]</Tag>
            <FileText size={14} style={{ color: 'var(--accent-primary)' }} />
            <span style={{ fontWeight: 600 }}>{ref.filename}</span>
            {ref.page && <Tag color="orange">{t('chat.page', { num: ref.page })}</Tag>}
          </div>
          <div
            style={{
              fontSize: 13,
              color: 'var(--text-secondary)',
              background: 'var(--bg-tertiary)',
              padding: 10,
              borderRadius: 6,
              lineHeight: 1.7,
              borderLeft: '3px solid #1677ff',
            }}
          >
            {ref.snippet}
          </div>
          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-tertiary)' }}>
            {t('chat.relevance')}: {(ref.score * 100).toFixed(1)}%
          </div>
        </Card>
      ))}
    </Drawer>
  );
}
