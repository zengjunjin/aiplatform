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
import { useChatStore } from '../store/chat';
import { useKBStore } from '../store/kb';
import dayjs from 'dayjs';

const { Title } = Typography;

export default function SessionsPage() {
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
      message.success('会话创建成功');
      setModalOpen(false);
      form.resetFields();
      navigate(`/chat/${session.id}`);
    } catch (e: any) {
      message.error(e.message || '创建失败');
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteSession(id);
      message.success('删除成功');
    } catch (e: any) {
      message.error(e.message || '删除失败');
    }
  };

  const getKBName = (kbId: number | null) => {
    if (!kbId) return '通用对话';
    const kb = knowledgeBases.find((k) => k.id === kbId);
    return kb?.name || `知识库 #${kbId}`;
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>
          我的对话
        </Title>
        <Button type="primary" icon={<Plus size={16} />} onClick={() => setModalOpen(true)}>
          新建对话
        </Button>
      </div>

      <Spin spinning={loading}>
        {sessions.length === 0 ? (
          <Empty description="暂无对话，点击上方按钮创建">
            <Button type="primary" onClick={() => setModalOpen(true)}>
              开始第一次对话
            </Button>
          </Empty>
        ) : (
          <List
            dataSource={sessions}
            renderItem={(session) => (
              <List.Item
                key={session.id}
                actions={[
                  <Popconfirm
                    key="delete"
                    title="确定删除该对话?"
                    onConfirm={() => handleDelete(session.id)}
                    okText="删除"
                    cancelText="取消"
                  >
                    <Button type="text" danger size="small" icon={<Trash2 size={14} />} />
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  avatar={<MessageSquare size={24} style={{ color: '#1677ff' }} />}
                  title={
                    <a
                      onClick={() => navigate(`/chat/${session.id}`)}
                      style={{ cursor: 'pointer' }}
                    >
                      {session.title || '新对话'}
                    </a>
                  }
                  description={
                    <Space size={12}>
                      <Tag color="blue">
                        <BookOpen size={12} style={{ marginRight: 4 }} />
                        {getKBName(session.kb_id)}
                      </Tag>
                      <span style={{ fontSize: 12, color: '#999' }}>
                        <Clock size={12} style={{ marginRight: 4, verticalAlign: 'middle' }} />
                        {dayjs(session.updated_at).format('YYYY-MM-DD HH:mm')}
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
        title="新建对话"
        open={modalOpen}
        onOk={handleCreate}
        onCancel={() => setModalOpen(false)}
        okText="创建"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="kb_id" label="选择知识库">
            <Select
              placeholder="选择一个知识库（可选）"
              allowClear
              options={knowledgeBases.map((kb) => ({
                label: kb.name,
                value: kb.id,
              }))}
            />
          </Form.Item>
          <Form.Item name="title" label="对话标题（可选）">
            <Input placeholder="留空将自动生成" maxLength={100} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
