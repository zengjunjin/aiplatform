import { useState, useEffect, useRef, useCallback } from 'react';
import { Layout, Button, Tag, Drawer, Empty, Breadcrumb, Card, Modal, Form, Select, Input, App as AntdApp } from 'antd';
import { Send, BookOpen, Plus, Trash2, Menu, FileText } from 'lucide-react';
import { useParams, useNavigate } from 'react-router-dom';
import { useChatStore } from '../store/chat';
import { useKBStore } from '../store/kb';
import { MessageBubble } from '../components/MessageBubble';
import ChatInput from '../components/ChatInput';
import { formatDateTime, truncate } from '../utils/format';
import type { Reference } from '../types';

const { Sider, Content } = Layout;

export default function ChatPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const sessionIdNum = parseInt(sessionId || '0');

  // 精细化订阅: 仅订阅需要的状态片断, 避免整个 store 变化触发重渲染
  const sessions = useChatStore((s) => s.sessions);
  const sessionMsgs = useChatStore((s) => s.messages[sessionIdNum] || []);
  const streaming = useChatStore((s) => s.streaming);
  // actions 引用稳定, 不会触发重渲染
  const fetchSessions = useChatStore((s) => s.fetchSessions);
  const fetchMessages = useChatStore((s) => s.fetchMessages);
  const sendMessage = useChatStore((s) => s.sendMessage);
  const stopStreaming = useChatStore((s) => s.stopStreaming);
  const createSession = useChatStore((s) => s.createSession);
  const deleteSession = useChatStore((s) => s.deleteSession);

  const knowledgeBases = useKBStore((s) => s.knowledgeBases);
  const fetchKBs = useKBStore((s) => s.fetchKBs);
  const [siderVisible, setSiderVisible] = useState(true);
  const [referencesVisible, setReferencesVisible] = useState(false);
  const [currentRefs, setCurrentRefs] = useState<Reference[]>([]);
  const [newSessionModal, setNewSessionModal] = useState(false);
  const [form] = Form.useForm();
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { message } = AntdApp.useApp();

  const currentSession = sessions.find((s) => s.id === sessionIdNum);

  // 判断当前会话是否正在 streaming (streaming 是全局状态, 切换会话时不应影响其他会话的 UI)
  const isCurrentSessionStreaming =
    sessionMsgs.length > 0 && sessionMsgs[sessionMsgs.length - 1].isStreaming === true;

  // 加载数据
  useEffect(() => {
    fetchSessions();
    fetchKBs();
  }, [fetchSessions, fetchKBs]);

  useEffect(() => {
    if (sessionIdNum > 0) {
      fetchMessages(sessionIdNum);
    }
  }, [sessionIdNum, fetchMessages]);

  // 自动滚动: 监听消息内容变化 (不只是数量)
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    // 监听最后一条消息的内容变化
    const lastMsg = sessionMsgs[sessionMsgs.length - 1];
    if (lastMsg) {
      scrollToBottom();
    }
  }, [sessionMsgs, scrollToBottom]);

  // 当 streaming 时, 定时滚动 (流式内容更新不会触发 useEffect)
  useEffect(() => {
    if (!isCurrentSessionStreaming) return;
    const interval = setInterval(() => {
      scrollToBottom();
    }, 200);
    return () => clearInterval(interval);
  }, [isCurrentSessionStreaming, scrollToBottom]);

  const handleSend = async (content: string) => {
    if (streaming) return; // 全局保护: 同时只允许一个 streaming
    try {
      await sendMessage(sessionIdNum, content);
    } catch (e: any) {
      message.error(e.message || '发送失败');
    }
  };

  const handleNewSession = async () => {
    try {
      const values = await form.validateFields();
      const session = await createSession(values.kb_id, values.title);
      setNewSessionModal(false);
      form.resetFields();
      navigate(`/chat/${session.id}`);
    } catch (e: any) {
      if (e.errorFields) return; // 表单验证错误
      message.error(e.message || '创建失败');
    }
  };

  const handleDeleteSession = async (id: number) => {
    try {
      await deleteSession(id);
      if (id === sessionIdNum) {
        navigate('/chat');
      }
      message.success('删除成功');
    } catch (e: any) {
      message.error(e.message || '删除失败');
    }
  };

  const handleRegenerate = () => {
    // 找到最后一条 user 消息
    for (let i = sessionMsgs.length - 1; i >= 0; i--) {
      if (sessionMsgs[i].role === 'user') {
        sendMessage(sessionIdNum, sessionMsgs[i].content);
        return;
      }
    }
  };

  const getKBName = (kbId: number | null) => {
    if (!kbId) return '通用对话';
    const kb = knowledgeBases.find((k) => k.id === kbId);
    return kb?.name || `知识库 #${kbId}`;
  };

  const showReferences = (refs: Reference[]) => {
    setCurrentRefs(refs);
    setReferencesVisible(true);
  };

  return (
    <Layout style={{ height: 'calc(100vh - 112px)' }}>
      {/* 左侧会话列表 */}
      <Sider
        width={280}
        style={{ background: '#fafafa', borderRight: '1px solid #f0f0f0' }}
        trigger={null}
        collapsible
        collapsed={!siderVisible}
        collapsedWidth={0}
      >
        <div style={{ padding: 16, borderBottom: '1px solid #f0f0f0' }}>
          <Button
            type="primary"
            icon={<Plus size={16} />}
            block
            onClick={() => setNewSessionModal(true)}
          >
            新建对话
          </Button>
        </div>
        <div style={{ overflow: 'auto', height: 'calc(100% - 60px)' }}>
          {sessions.map((s) => (
            <div
              key={s.id}
              onClick={() => navigate(`/chat/${s.id}`)}
              style={{
                padding: '10px 16px',
                cursor: 'pointer',
                background: s.id === sessionIdNum ? '#e6f4ff' : 'transparent',
                borderLeft: s.id === sessionIdNum ? '3px solid #1677ff' : '3px solid transparent',
                transition: 'background 0.2s',
              }}
              onMouseEnter={(e) => {
                if (s.id !== sessionIdNum) e.currentTarget.style.background = '#f0f0f0';
              }}
              onMouseLeave={(e) => {
                if (s.id !== sessionIdNum) e.currentTarget.style.background = 'transparent';
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ flex: 1, overflow: 'hidden' }}>
                  <div
                    style={{
                      fontWeight: s.id === sessionIdNum ? 600 : 400,
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      fontSize: 14,
                    }}
                  >
                    {s.title || '新对话'}
                  </div>
                  <div style={{ fontSize: 12, color: '#999', marginTop: 2 }}>
                    {getKBName(s.kb_id)}
                  </div>
                </div>
                <Button
                  type="text"
                  danger
                  size="small"
                  icon={<Trash2 size={14} />}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDeleteSession(s.id);
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </Sider>

      <Layout>
        {/* 顶部栏 */}
        <div
          style={{
            padding: '0 16px',
            height: 52,
            display: 'flex',
            alignItems: 'center',
            borderBottom: '1px solid #f0f0f0',
            background: '#fff',
          }}
        >
          <Button
            type="text"
            icon={<Menu size={18} />}
            onClick={() => setSiderVisible(!siderVisible)}
          />
          <Breadcrumb style={{ marginLeft: 12 }}>
            <Breadcrumb.Item>
              <a onClick={() => navigate('/chat')} style={{ cursor: 'pointer' }}>对话</a>
            </Breadcrumb.Item>
            <Breadcrumb.Item>
              {currentSession?.title || '加载中...'}
            </Breadcrumb.Item>
          </Breadcrumb>
          {currentSession?.kb_id && (
            <Tag color="blue" style={{ marginLeft: 'auto' }}>
              <BookOpen size={12} style={{ marginRight: 4 }} />
              {getKBName(currentSession.kb_id)}
            </Tag>
          )}
        </div>

        {/* 消息列表 */}
        <Content
          ref={scrollContainerRef as any}
          style={{
            padding: '16px 24px',
            overflow: 'auto',
            background: '#f5f5f5',
          }}
        >
          {sessionMsgs.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '80px 0' }}>
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  <span style={{ color: '#999' }}>
                    开始你的第一次对话吧
                    <br />
                    <span style={{ fontSize: 12 }}>
                      选择一个知识库,然后输入你的问题
                    </span>
                  </span>
                }
              />
            </div>
          ) : (
            <div style={{ maxWidth: 900, margin: '0 auto' }}>
              {sessionMsgs.map((msg, idx) => (
                <div key={msg.id || `msg-${idx}`} className="message-fade-in">
                  <MessageBubble
                    role={msg.role}
                    content={msg.content}
                    isStreaming={msg.isStreaming}
                    references={msg.references}
                    createdAt={msg.created_at}
                    onRegenerate={
                      msg.role === 'assistant' && !msg.isStreaming && idx === sessionMsgs.length - 1
                        ? handleRegenerate
                        : undefined
                    }
                  />
                  {msg.references && msg.references.length > 0 && !msg.isStreaming && (
                    <div style={{ marginLeft: 48, marginBottom: 16 }}>
                      <Tag
                        color="blue"
                        style={{ cursor: 'pointer' }}
                        onClick={() => showReferences(msg.references!)}
                      >
                        📚 查看参考来源 ({msg.references.length})
                      </Tag>
                    </div>
                  )}
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>
          )}
        </Content>

        {/* 输入框 */}
        <ChatInput
          onSend={handleSend}
          onStop={stopStreaming}
          streaming={isCurrentSessionStreaming}
          kbName={currentSession?.kb_id ? getKBName(currentSession.kb_id) : undefined}
          modelName={'Qwen2.5-7B'}
          placeholder={
            currentSession?.kb_id
              ? '输入你的问题，Enter 发送，Shift+Enter 换行'
              : '提示: 创建对话时选择知识库可获得更准确的回答'
          }
        />
      </Layout>

      {/* 参考来源抽屉 */}
      <Drawer
        title="参考来源"
        placement="right"
        onClose={() => setReferencesVisible(false)}
        open={referencesVisible}
        width={420}
      >
        {currentRefs.map((ref, i) => (
          <Card key={i} size="small" style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <Tag color="blue">[{i + 1}]</Tag>
              <FileText size={14} style={{ color: '#1677ff' }} />
              <span style={{ fontWeight: 600 }}>{ref.filename}</span>
              {ref.page && <Tag color="orange">页 {ref.page}</Tag>}
            </div>
            <div
              style={{
                fontSize: 13,
                color: '#666',
                background: '#fafafa',
                padding: 10,
                borderRadius: 6,
                lineHeight: 1.7,
                borderLeft: '3px solid #1677ff',
              }}
            >
              {ref.snippet}
            </div>
            <div style={{ marginTop: 8, fontSize: 12, color: '#999' }}>
              相关度: {(ref.score * 100).toFixed(1)}%
            </div>
          </Card>
        ))}
      </Drawer>

      {/* 新建对话弹窗 */}
      <Modal
        title="新建对话"
        open={newSessionModal}
        onOk={handleNewSession}
        onCancel={() => setNewSessionModal(false)}
        okText="创建"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="kb_id" label="选择知识库">
            <Select
              placeholder="选择一个知识库（可选，不选则通用对话）"
              allowClear
              options={knowledgeBases.map((kb) => ({
                label: `${kb.name} (${kb.doc_count || 0} 文档)`,
                value: kb.id,
              }))}
            />
          </Form.Item>
          <Form.Item name="title" label="对话标题（可选）">
            <Input placeholder="留空将根据首条消息自动生成" maxLength={100} />
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  );
}
