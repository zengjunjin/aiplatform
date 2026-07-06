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
import { useKBStore } from '../store/kb';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { TextArea } = Input;

export default function KnowledgeBasesPage() {
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
      message.success('知识库创建成功');
      setModalOpen(false);
      form.resetFields();
    } catch (e: any) {
      message.error(e.message || '创建失败');
    }
  };

  const handleDelete = async (id: number, name: string) => {
    try {
      await deleteKB(id);
      message.success('删除成功');
    } catch (e: any) {
      message.error(e.message || '删除失败');
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>
          我的知识库
        </Title>
        <Button type="primary" icon={<Plus size={16} />} onClick={() => setModalOpen(true)}>
          新建知识库
        </Button>
      </div>

      <Spin spinning={loading}>
        {knowledgeBases.length === 0 ? (
          <Empty description="暂无知识库，点击上方按钮创建">
            <Button type="primary" onClick={() => setModalOpen(true)}>
              创建第一个知识库
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
            {knowledgeBases.map((kb) => (
              <Card
                key={kb.id}
                hoverable
                onClick={() => navigate(`/knowledge-bases/${kb.id}`)}
                style={{ cursor: 'pointer' }}
              >
                <Card.Meta
                  title={
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Text strong style={{ fontSize: 16 }}>{kb.name}</Text>
                      <Popconfirm
                        title="确定删除该知识库?"
                        description="删除后所有文档和数据将永久丢失，无法恢复"
                        onConfirm={(e) => {
                          e?.stopPropagation();
                          handleDelete(kb.id, kb.name);
                        }}
                        okText="删除"
                        cancelText="取消"
                      >
                        <Button
                          type="text"
                          danger
                          size="small"
                          icon={<Trash2 size={14} />}
                          onClick={(e) => e.stopPropagation()}
                        />
                      </Popconfirm>
                    </div>
                  }
                  description={
                    <div>
                      <div style={{ marginBottom: 12, minHeight: 40 }}>
                        {kb.description || <Text type="secondary">无描述</Text>}
                      </div>
                      <Space size={12}>
                        <Tag color="blue">
                          <FileText size={12} style={{ marginRight: 4 }} />
                          {kb.doc_count || 0} 文档
                        </Tag>
                        <Tag color="green">
                          {kb.chunk_count || 0} 分块
                        </Tag>
                      </Space>
                      <div style={{ marginTop: 12, fontSize: 12, color: '#999' }}>
                        <Clock size={12} style={{ marginRight: 4, verticalAlign: 'middle' }} />
                        更新于 {dayjs(kb.updated_at).format('YYYY-MM-DD HH:mm')}
                      </div>
                    </div>
                  }
                />
              </Card>
            ))}
          </div>
        )}
      </Spin>

      <Modal
        title="新建知识库"
        open={modalOpen}
        onOk={handleCreate}
        onCancel={() => setModalOpen(false)}
        okText="创建"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="知识库名称"
            rules={[{ required: true, message: '请输入知识库名称' }]}
          >
            <Input placeholder="例如：产品手册知识库" maxLength={100} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <TextArea rows={3} placeholder="简要描述这个知识库的用途" maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
