import { useState, useEffect } from 'react';
import {
  Card,
  Button,
  Modal,
  Form,
  Input,
  Space,
  Typography,
  Empty,
  Popconfirm,
  Tag,
  App as AntdApp,
  Spin,
} from 'antd';
import { Plus, Trash2, FileText, Clock } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useKBStore } from '../store/kb';
import { formatRelativeTime } from '../utils/format';

const { Title, Text } = Typography;
const { TextArea } = Input;

export default function KnowledgeBasesPage() {
  const { t } = useTranslation();
  // 精细化订阅
  const knowledgeBases = useKBStore((s) => s.knowledgeBases);
  const loading = useKBStore((s) => s.loading);
  const fetchKBs = useKBStore((s) => s.fetchKBs);
  const createKB = useKBStore((s) => s.createKB);
  const deleteKB = useKBStore((s) => s.deleteKB);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();

  useEffect(() => {
    fetchKBs();
  }, [fetchKBs]);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      await createKB(values.name, values.description || '');
      message.success(t('kb.createSuccess'));
      setModalOpen(false);
      form.resetFields();
    } catch (e: any) {
      message.error(e.message || t('kb.createFailed'));
    }
  };

  const handleDelete = async (id: number, name: string) => {
    try {
      await deleteKB(id);
      message.success(t('kb.deleteSuccess'));
    } catch (e: any) {
      message.error(e.message || t('kb.deleteFailed'));
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>
          {t('kb.myKnowledgeBases')}
        </Title>
        <Button type="primary" icon={<Plus size={16} />} onClick={() => setModalOpen(true)}>
          {t('kb.newKnowledgeBase')}
        </Button>
      </div>

      <Spin spinning={loading}>
        {knowledgeBases.length === 0 ? (
          <Empty description={t('kb.noKBs')}>
            <Button type="primary" onClick={() => setModalOpen(true)}>
              {t('kb.createFirstKB')}
            </Button>
          </Empty>
        ) : (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
              gap: 16,
            }}
          >
            {knowledgeBases.map((kb) => {
              const gradients = [
                'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
                'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
                'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
                'linear-gradient(135deg, #fa709a 0%, #fee140 100%)',
                'linear-gradient(135deg, #a18cd1 0%, #fbc2eb 100%)',
              ];
              const gradientIndex = kb.name.length % gradients.length;
              return (
                <Card
                  key={kb.id}
                  hoverable
                  onClick={() => navigate(`/knowledge-bases/${kb.id}`)}
                  style={{
                    cursor: 'pointer',
                    overflow: 'hidden',
                    padding: 0,
                    transition: 'all var(--transition-base)',
                  }}
                  bodyStyle={{ padding: 0 }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.transform = 'translateY(-4px)';
                    e.currentTarget.style.boxShadow = 'var(--shadow-lg)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = 'translateY(0)';
                    e.currentTarget.style.boxShadow = '';
                  }}
                >
                  {/* Gradient Header Bar */}
                  <div
                    style={{
                      height: 80,
                      background: gradients[gradientIndex],
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
                        handleDelete(kb.id, kb.name);
                      }}
                      okText={t('kb.delete')}
                      cancelText={t('kb.cancel')}
                    >
                      <Button
                        type="text"
                        size="small"
                        icon={<Trash2 size={14} color="#fff" />}
                        onClick={(e) => e.stopPropagation()}
                        style={{ opacity: 0.8 }}
                      />
                    </Popconfirm>
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </Spin>

      <Modal
        title={t('kb.newKnowledgeBase')}
        open={modalOpen}
        onOk={handleCreate}
        onCancel={() => setModalOpen(false)}
        okText={t('kb.create')}
        cancelText={t('kb.cancel')}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label={t('kb.kbName')}
            rules={[{ required: true, message: t('kb.kbNameRequired') }]}
          >
            <Input placeholder={t('kb.kbNamePlaceholder')} maxLength={100} />
          </Form.Item>
          <Form.Item name="description" label={t('kb.description')}>
            <TextArea rows={3} placeholder={t('kb.descriptionPlaceholder')} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
