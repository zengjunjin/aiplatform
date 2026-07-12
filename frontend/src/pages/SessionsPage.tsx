import { useState, useEffect } from 'react';
import {
  List,
  Button,
  Space,
  Typography,
  Empty,
  Popconfirm,
  Tag,
  App as AntdApp,
  Spin,
  Modal,
  Select,
  Input,
  Form,
} from 'antd';
import {
  Plus,
  Trash2,
  MessageSquare,
  Clock,
  BookOpen,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useChatStore } from '../store/chat';
import { useKBStore } from '../store/kb';
import { formatRelativeTime } from '../utils/format';

const { Title } = Typography;

export default function SessionsPage() {
  const { t } = useTranslation();
  // 精细化订阅
  const sessions = useChatStore((s) => s.sessions);
  const loading = useChatStore((s) => s.loading);
  const fetchSessions = useChatStore((s) => s.fetchSessions);
  const createSession = useChatStore((s) => s.createSession);
  const deleteSession = useChatStore((s) => s.deleteSession);

  const knowledgeBases = useKBStore((s) => s.knowledgeBases);
  const fetchKBs = useKBStore((s) => s.fetchKBs);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();

  useEffect(() => {
    fetchSessions();
    fetchKBs();
  }, [fetchSessions, fetchKBs]);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      const session = await createSession(values.kb_id, values.title);
      message.success(t('session.createSuccess'));
      setModalOpen(false);
      form.resetFields();
      setTimeout(() => {
        navigate(`/chat/${session.id}`);
      }, 0);
    } catch (e: any) {
      if (e.errorFields) return;
      message.error(e.message || t('session.createFailed'));
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteSession(id);
      message.success(t('session.deleteSuccess'));
    } catch (e: any) {
      message.error(e.message || t('session.deleteFailed'));
    }
  };

  const getKBName = (kbId: number | null) => {
    if (!kbId) return t('session.generalChat');
    const kb = knowledgeBases.find((k) => k.id === kbId);
    return kb?.name || t('session.kbLabel', { kbId });
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>
          {t('session.mySessions')}
        </Title>
        <Button type="primary" icon={<Plus size={16} />} onClick={() => setModalOpen(true)}>
          {t('session.newSession')}
        </Button>
      </div>

      <Spin spinning={loading}>
        {sessions.length === 0 ? (
          <Empty description={t('session.noSessions')}>
            <Button type="primary" onClick={() => setModalOpen(true)}>
              {t('session.startFirstSession')}
            </Button>
          </Empty>
        ) : (
          <List
            dataSource={sessions}
            renderItem={(session) => (
              <List.Item
                key={session.id}
                onClick={() => navigate(`/chat/${session.id}`)}
                style={{
                  cursor: 'pointer',
                  padding: '12px 16px',
                  borderRadius: 'var(--radius-md)',
                  transition: 'all var(--transition-base)',
                  borderBottom: '1px solid var(--border-color)',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'var(--bg-tertiary)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'transparent';
                }}
                actions={[
                  <Popconfirm
                    key="delete"
                    title={t('session.deleteConfirmTitle')}
                    onConfirm={() => handleDelete(session.id)}
                    okText={t('session.delete')}
                    cancelText={t('session.cancel')}
                  >
                    <Button type="text" danger size="small" icon={<Trash2 size={14} />} />
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  avatar={<MessageSquare size={24} style={{ color: '#1677ff' }} />}
                  title={
                    <span style={{ fontWeight: 500, fontSize: 14, color: 'var(--text-primary)' }}>
                      {session.title || t('session.newSessionTitle')}
                    </span>
                  }
                  description={
                    <Space size={12}>
                      <Tag color="blue">
                        <BookOpen size={12} style={{ marginRight: 4 }} />
                        {getKBName(session.kb_id)}
                      </Tag>
                      <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
                        <Clock size={12} style={{ marginRight: 4, verticalAlign: 'middle' }} />
                        {formatRelativeTime(session.updated_at)}
                      </span>
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Spin>

      <Modal
        title={t('session.newSession')}
        open={modalOpen}
        onOk={handleCreate}
        onCancel={() => setModalOpen(false)}
        okText={t('session.create')}
        cancelText={t('session.cancel')}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="kb_id" label={t('session.selectKB')}>
            <Select
              placeholder={t('session.selectKBPlaceholder')}
              allowClear
              options={knowledgeBases.map((kb) => ({
                label: kb.name,
                value: kb.id,
              }))}
            />
          </Form.Item>
          <Form.Item name="title" label={t('session.sessionTitleOptional')}>
            <Input placeholder={t('session.sessionTitleHint')} maxLength={100} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
