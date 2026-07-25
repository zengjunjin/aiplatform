import { Button, Card, Popconfirm, Space, Tag, Typography } from 'antd';
import { Trash2, FileText, Clock } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { formatRelativeTime } from '../utils/format';
import type { KnowledgeBase } from '../types';

const { Text } = Typography;

const KB_GRADIENTS = [
  'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
  'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
  'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
  'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
  'linear-gradient(135deg, #fa709a 0%, #fee140 100%)',
  'linear-gradient(135deg, #a18cd1 0%, #fbc2eb 100%)',
];

// ===== KBCard: 单个知识库卡片 (渐变头部 + 描述 + 文档/chunk 统计 + 删除) =====
export interface KBCardProps {
  kb: KnowledgeBase;
  onNavigate: (id: number) => void;
  onDelete: (id: number, name: string) => void;
}

export function KBCard({ kb, onNavigate, onDelete }: KBCardProps) {
  const { t } = useTranslation();
  const gradientIndex = kb.name.length % KB_GRADIENTS.length;

  return (
    <Card
      key={kb.id}
      hoverable
      role="button"
      tabIndex={0}
      onClick={() => onNavigate(kb.id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onNavigate(kb.id);
        }
      }}
      style={{
        cursor: 'pointer',
        overflow: 'hidden',
        padding: 0,
      }}
      styles={{ body: { padding: 0 } }}
      className="kb-card-hoverable"
    >
      {/* Gradient Header Bar */}
      <div
        style={{
          height: 80,
          background: KB_GRADIENTS[gradientIndex],
          display: 'flex',
          alignItems: 'flex-end',
          padding: '16px 20px',
        }}
      >
        <Text strong style={{ fontSize: 18, color: '#fff', textShadow: '0 1px 2px rgba(0,0,0,0.2)' }}>
          {kb.name}
        </Text>
      </div>
      {/* Card Body */}
      <div style={{ padding: '16px 20px' }}>
        <div style={{ marginBottom: 12, minHeight: 36 }}>
          {kb.description ? (
            <Text style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
              {kb.description}
            </Text>
          ) : (
            <Text type="secondary" style={{ fontSize: 13 }}>{t('kb.noDescription')}</Text>
          )}
        </div>
        <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: 12, marginBottom: 8 }}>
          <Space size={16}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <FileText size={16} style={{ color: 'var(--accent-primary)' }} />
              <Text strong style={{ fontSize: 14, color: 'var(--text-primary)' }}>{kb.doc_count || 0}</Text>
              <Text style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>{t('kb.documents', { count: kb.doc_count || 0 })}</Text>
            </div>
            <Tag color="green" style={{ borderRadius: 'var(--radius-sm)' }}>
              {t('kb.chunks', { count: kb.chunk_count || 0 })}
            </Tag>
          </Space>
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: 4 }}>
          <Clock size={12} />
          {formatRelativeTime(kb.updated_at)}
        </div>
      </div>
      {/* Delete Button */}
      <div style={{ position: 'absolute', top: 12, right: 12 }}>
        <Popconfirm
          title={t('kb.deleteConfirmTitle')}
          description={t('kb.deleteConfirmDesc')}
          onConfirm={(e) => {
            e?.stopPropagation();
            onDelete(kb.id, kb.name);
          }}
          okText={t('kb.delete')}
          cancelText={t('kb.cancel')}
        >
          <Button
            type="text"
            size="small"
            icon={<Trash2 size={14} color="#fff" />}
            aria-label={t('kb.delete')}
            onClick={(e) => e.stopPropagation()}
            style={{ opacity: 0.8 }}
          />
        </Popconfirm>
      </div>
    </Card>
  );
}
