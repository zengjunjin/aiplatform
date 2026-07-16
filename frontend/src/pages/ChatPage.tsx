import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Layout, Button, Tag, Drawer, Empty, Breadcrumb, Card, Modal, Form, Select, Input, App as AntdApp } from 'antd';
import { Send, BookOpen, Plus, Trash2, Menu, FileText, Sparkles } from 'lucide-react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useChatStore } from '../store/chat';
import { useKBStore } from '../store/kb';
import { MessageBubble } from '../components/MessageBubble';
import ChatInput from '../components/ChatInput';
import { formatDateTime, truncate } from '../utils/format';
import { systemApi } from '../api';
import type { Reference } from '../types';
import type { ModelInfo } from '../api/system';

const { Sider, Content } = Layout;

/** 空消息数组的稳定引用，避免 selector 每次返回新数组导致重渲染 */
const EMPTY_MESSAGES: never[] = [];

export default function ChatPage() {
  const { t } = useTranslation();
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const sessionIdNum = parseInt(sessionId || '0');

  // 精细化订阅: 仅订阅需要的状态片断, 避免整个 store 变化触发重渲染
  const sessions = useChatStore((s) => s.sessions);
  // 使用空数组常量作为 fallback，避免每次 selector 返回新引用导致重渲染
  const sessionMsgs = useChatStore((s) => s.messages[sessionIdNum]) ?? EMPTY_MESSAGES;
  const streaming = useChatStore((s) => s.streaming);
  const warnings = useChatStore((s) => s.warnings);
  // actions 引用稳定, 不会触发重渲染
  const fetchSessions = useChatStore((s) => s.fetchSessions);
  const fetchMessages = useChatStore((s) => s.fetchMessages);
  const sendMessage = useChatStore((s) => s.sendMessage);
  const stopStreaming = useChatStore((s) => s.stopStreaming);
  const createSession = useChatStore((s) => s.createSession);
  const deleteSession = useChatStore((s) => s.deleteSession);
  const clearWarnings = useChatStore((s) => s.clearWarnings);

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

  // 模型选择器状态
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>(() => {
    return localStorage.getItem('chat-selected-model') || '';
  });

  const pendingSessionId = useRef<number | null>(null);

  const currentSession = useMemo(
    () => sessions.find((s) => s.id === sessionIdNum),
    [sessions, sessionIdNum]
  );

  // 判断当前会话是否正在 streaming (streaming 是全局状态, 切换会话时不应影响其他会话的 UI)
  const isCurrentSessionStreaming = useMemo(
    () => sessionMsgs.length > 0 && sessionMsgs[sessionMsgs.length - 1].isStreaming === true,
    [sessionMsgs]
  );

  // 加载数据
  useEffect(() => {
    let mounted = true;
    fetchSessions();
    fetchKBs();
    // 加载可用模型列表
    systemApi.listModels().then((res) => {
      if (!mounted) return;
      setModels(res.models || []);
      // 如果当前没有选中模型，使用默认模型
      if (!selectedModel && res.default_model) {
        setSelectedModel(res.default_model);
        localStorage.setItem('chat-selected-model', res.default_model);
      }
    }).catch(() => {
      // 模型列表加载失败不影响聊天功能
    });
    return () => { mounted = false; };
  }, [fetchSessions, fetchKBs]);

  // 切换会话时自动中断旧 SSE 流，防止 streaming 状态卡死
  useEffect(() => {
    stopStreaming();
  }, [sessionIdNum, stopStreaming]);

  useEffect(() => {
    if (sessionIdNum > 0) {
      fetchMessages(sessionIdNum);
    }
  }, [sessionIdNum, fetchMessages]);

  // 显示后端推送的警告消息
  useEffect(() => {
    if (warnings.length > 0) {
      warnings.forEach((w) => {
        message.warning(w);
      });
      clearWarnings();
    }
  }, [warnings, message, clearWarnings]);

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

  const handleSend = useCallback(async (content: string) => {
    if (streaming) return; // 全局保护: 同时只允许一个 streaming
    try {
      await sendMessage(sessionIdNum, content, selectedModel || undefined);
    } catch (e: any) {
      message.error(e.message || t('chat.sendFailed'));
    }
  }, [streaming, sendMessage, sessionIdNum, selectedModel, message, t]);

  const handleNewSession = useCallback(async () => {
    try {
      const values = await form.validateFields();
      const session = await createSession(values.kb_id, values.title);
      pendingSessionId.current = session.id;
      // 关闭弹窗，不在这里导航，等 afterClose 回调再导航
      setNewSessionModal(false);
      form.resetFields();
    } catch (e: any) {
      if (e.errorFields) return; // 表单验证错误，不关闭弹窗
      message.error(e.message || t('chat.createFailed'));
      setNewSessionModal(false); // 创建失败时关闭弹窗
    }
  }, [form, createSession, message, t]);

  const handleDeleteSession = useCallback(async (id: number) => {
    try {
      await deleteSession(id);
      if (id === sessionIdNum) {
        navigate('/chat');
      }
      message.success(t('chat.deleteSuccess'));
    } catch (e: any) {
      message.error(e.message || t('chat.deleteFailed'));
    }
  }, [deleteSession, sessionIdNum, navigate, message, t]);

  const handleRegenerate = useCallback(() => {
    if (streaming) return; // 正在流式输出时禁止重新生成
    // 找到最后一条 user 消息
    for (let i = sessionMsgs.length - 1; i >= 0; i--) {
      if (sessionMsgs[i].role === 'user') {
        sendMessage(sessionIdNum, sessionMsgs[i].content, selectedModel || undefined);
        return;
      }
    }
  }, [streaming, sessionMsgs, sendMessage, sessionIdNum, selectedModel]);

  const getKBName = useCallback((kbId: number | null) => {
    if (!kbId) return t('chat.generalChat');
    const kb = knowledgeBases.find((k) => k.id === kbId);
    return kb?.name || t('chat.knowledgeBaseLabel', { kbId });
  }, [t, knowledgeBases]);

  const showReferences = useCallback((refs: Reference[]) => {
    setCurrentRefs(refs);
    setReferencesVisible(true);
  }, []);

  // 模型选择器 options 派生数据, 仅在 models 变化时重新计算
  const modelOptions = useMemo(
    () => models.map((m) => ({
      label: `${m.display_name} ${m.status === 'unhealthy' ? '(离线)' : ''}`,
      value: m.name,
      disabled: m.status === 'unhealthy',
    })),
    [models]
  );

  return (
    <Layout style={{ height: 'calc(100vh - 112px)' }}>
      {/* 左侧会话列表 */}
      <Sider
        width={280}
        style={{ background: 'var(--bg-secondary)', borderRight: '1px solid var(--border-color)' }}
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
            {t('chat.newChat')}
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
                    {s.title || t('chat.newSession')}
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
              <a onClick={() => navigate('/chat')} style={{ cursor: 'pointer' }}>{t('chat.chat')}</a>
            </Breadcrumb.Item>
            <Breadcrumb.Item>
              {currentSession?.title || t('chat.loading')}
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
            background: 'var(--bg-tertiary)',
          }}
        >
          {sessionMsgs.length === 0 ? (
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              minHeight: 400,
              padding: '40px 0',
            }}>
              <div
                style={{
                  width: 72,
                  height: 72,
                  borderRadius: 20,
                  background: 'linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f093fb 100%)',
                  backgroundSize: '200% 200%',
                  animation: 'logoGradient 4s ease infinite',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  marginBottom: 24,
                  boxShadow: '0 8px 32px rgba(102, 126, 234, 0.25)',
                }}
              >
                <Sparkles size={36} color="#ffffff" strokeWidth={1.5} />
              </div>
              <h2 style={{ fontSize: 22, fontWeight: 600, color: 'var(--text-primary)', margin: '0 0 8px 0' }}>
                {t('chat.startFirstChat')}
              </h2>
              <p style={{ fontSize: 14, color: 'var(--text-secondary)', margin: '0 0 32px 0' }}>
                {t('chat.selectKBAndAsk')}
              </p>
              <div style={{
                width: '100%',
                maxWidth: 600,
                padding: '24px',
                background: 'var(--bg-secondary)',
                borderRadius: 'var(--radius-lg)',
                boxShadow: 'var(--shadow-md)',
                border: '1px solid var(--border-color)',
              }}>
                <p style={{ fontSize: 13, color: 'var(--text-tertiary)', textAlign: 'center', margin: 0 }}>
                  Ask anything about your knowledge base
                </p>
              </div>
            </div>
          ) : (
            <div style={{ maxWidth: 900, margin: '0 auto' }}>
              {sessionMsgs.map((msg, idx) => (
                <div key={msg.id || `msg-${idx}`} className="message-bubble-enter">
                  <MessageBubble
                    role={msg.role}
                    content={msg.content}
                    messageId={msg.id}
                    isStreaming={msg.isStreaming}
                    references={msg.references}
                    createdAt={msg.created_at}
                    onRegenerate={
                      msg.role === 'assistant' && !msg.isStreaming && !streaming && idx === sessionMsgs.length - 1
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
                        {t('chat.viewReferencesCount', { count: msg.references.length })}
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
        {/* 模型选择器 */}
        <div style={{ padding: '8px 24px 0', background: 'var(--bg-secondary)', borderTop: '1px solid var(--border-color)' }}>
          <div style={{ maxWidth: 900, margin: '0 auto', display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 13, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>模型:</span>
            <Select
              value={selectedModel || undefined}
              onChange={(val) => {
                setSelectedModel(val);
                localStorage.setItem('chat-selected-model', val);
              }}
              placeholder="自动选择"
              style={{ minWidth: 200 }}
              size="small"
              allowClear
              options={modelOptions}
            />
          </div>
        </div>
        <ChatInput
          key={sessionIdNum}
          onSend={handleSend}
          onStop={stopStreaming}
          streaming={isCurrentSessionStreaming}
          kbName={currentSession?.kb_id ? getKBName(currentSession.kb_id) : undefined}
          modelName={models.find(m => m.name === selectedModel)?.display_name || '自动选择'}
          placeholder={
            currentSession?.kb_id
              ? t('chat.inputPlaceholder')
              : t('chat.inputPlaceholderNoKB')
          }
        />
      </Layout>

      {/* 参考来源抽屉 */}
      <Drawer
        title={t('chat.references')}
        placement="right"
        onClose={() => setReferencesVisible(false)}
        open={referencesVisible}
        width={420}
      >
        {currentRefs.map((ref, i) => (
          <Card key={i} size="small" style={{ marginBottom: 12 }}>
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

      {/* 新建对话弹窗 */}
      <Modal
        title={t('chat.newChat')}
        open={newSessionModal}
        onOk={handleNewSession}
        onCancel={() => setNewSessionModal(false)}
        afterClose={() => {
          if (pendingSessionId.current) {
            navigate(`/chat/${pendingSessionId.current}`);
            pendingSessionId.current = null;
          }
        }}
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
              options={knowledgeBases.map((kb) => ({
                label: `${kb.name} (${kb.doc_count || 0} ${t('kb.documents', { count: kb.doc_count || 0 })})`,
                value: kb.id,
              }))}
            />
          </Form.Item>
          <Form.Item name="title" label={t('chat.sessionTitleOptional')}>
            <Input placeholder={t('chat.sessionTitleHint')} maxLength={100} />
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  );
}
