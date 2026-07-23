import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Layout, App as AntdApp } from 'antd';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useShallow } from 'zustand/react/shallow';
import { useChatStore } from '../store/chat';
import { useKBStore } from '../store/kb';
import ChatInput from '../components/ChatInput';
import SessionSider from '../components/SessionSider';
import ReferencesDrawer from '../components/ReferencesDrawer';
import NewSessionModal from '../components/NewSessionModal';
import { systemApi } from '../api';
import type { MessageWithRefs, Reference } from '../types';
import type { ModelInfo } from '../api/system';
import { getErrorMessage } from '../utils/errorReporter';
import { ChatHeader, ChatMessagesArea, ChatModelSelector } from './ChatPage.parts';

/** 空消息数组的稳定引用，避免 selector 每次返回新数组导致重渲染 */
const EMPTY_MESSAGES: MessageWithRefs[] = [];

export default function ChatPage() {
  const { t } = useTranslation();
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const sessionIdNum = parseInt(sessionId || '0');

  // 精细化订阅: 仅订阅需要的状态片断, 避免整个 store 变化触发重渲染
  const sessions = useChatStore((s) => s.sessions);
  // 从 messagesById + messageOrder 组装有序消息数组, 使用 useShallow 做浅比较:
  // 流式更新只改变单条消息引用, 其余消息引用不变, 浅比较命中后避免不必要的重渲染
  const sessionMsgs = useChatStore(
    useShallow((s) => {
      const order = s.messageOrder[sessionIdNum] || [];
      const byId = s.messagesById[sessionIdNum] || {};
      const result: MessageWithRefs[] = [];
      for (let i = 0; i < order.length; i++) {
        const msg = byId[order[i]];
        if (msg) result.push(msg);
      }
      return result.length > 0 ? result : EMPTY_MESSAGES;
    })
  );
  const streaming = useChatStore((s) => s.streaming);
  const warnings = useChatStore((s) => s.warnings);
  const messagesError = useChatStore((s) => s.messagesError);
  // actions 引用稳定, 不会触发重渲染
  const fetchSessions = useChatStore((s) => s.fetchSessions);
  const fetchMessages = useChatStore((s) => s.fetchMessages);
  const sendMessage = useChatStore((s) => s.sendMessage);
  const stopStreaming = useChatStore((s) => s.stopStreaming);
  const createSession = useChatStore((s) => s.createSession);
  const deleteSession = useChatStore((s) => s.deleteSession);
  const clearWarnings = useChatStore((s) => s.clearWarnings);
  const clearMessagesError = useChatStore((s) => s.clearMessagesError);

  const knowledgeBases = useKBStore((s) => s.knowledgeBases);
  const fetchKBs = useKBStore((s) => s.fetchKBs);
  const [siderVisible, setSiderVisible] = useState(true);
  const [referencesVisible, setReferencesVisible] = useState(false);
  const [currentRefs, setCurrentRefs] = useState<Reference[]>([]);
  const [newSessionModal, setNewSessionModal] = useState(false);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { message } = AntdApp.useApp();

  // 模型选择器状态
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>(() => {
    const val = localStorage.getItem('chat-selected-model');
    // Task 70: typeof 校验防止 localStorage 被篡改为非 string 类型
    return typeof val === 'string' ? val : '';
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

  // 仅挂载时初始化默认模型，故意省略 selectedModel
  // 避免每次 selectedModel 变化时重新加载模型列表
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
      }
    }).catch(() => {
      // 模型列表加载失败不影响聊天功能
    });
    return () => { mounted = false; };
  }, [fetchSessions, fetchKBs]);

  // localStorage 写入下沉到独立 useEffect，避免 onChange 中重复写入
  useEffect(() => {
    if (selectedModel) {
      localStorage.setItem('chat-selected-model', selectedModel);
    }
  }, [selectedModel]);

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

  // Task 48: 监听 fetchMessages 错误上报, 通过 message.error 提示用户
  useEffect(() => {
    if (messagesError !== null && messagesError !== undefined) {
      message.error(getErrorMessage(messagesError) || t('chat.fetchMessagesFailed'));
      clearMessagesError();
    }
  }, [messagesError, message, clearMessagesError, t]);

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
  }, [sessionMsgs.length, scrollToBottom]);

  // 当 streaming 时, 用 IntersectionObserver 监听底部哨兵: 哨兵离开视口说明内容增长超过视口,
  // 自动滚动到最新内容. 相比 setInterval 200ms 轮询, 避免空闲帧浪费与不必要滚动.
  useEffect(() => {
    if (!isCurrentSessionStreaming) return;
    const sentinel = messagesEndRef.current;
    const root = scrollContainerRef.current;
    if (!sentinel || !root) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (!entry.isIntersecting) {
          // 哨兵离开视口: 内容已增长到视口外, 自动滚动到底
          sentinel.scrollIntoView({ behavior: 'auto' });
        }
      },
      { root, threshold: 0 },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [isCurrentSessionStreaming]);

  const handleSend = useCallback(async (content: string) => {
    if (streaming) {
      // 全局保护: 同时只允许一个 streaming
      message.warning(t('chat.alreadyStreaming'));
      return;
    }
    try {
      await sendMessage(sessionIdNum, content, selectedModel || undefined);
    } catch (e: unknown) {
      message.error(getErrorMessage(e) || t('chat.sendFailed'));
    }
  }, [streaming, sendMessage, sessionIdNum, selectedModel, message, t]);

  // NewSessionModal 提交回调: 由 NewSessionModal 内部完成表单校验后调用.
  // 校验失败时不进入此回调 (NewSessionModal handleOk catch 拦截).
  // 创建成功: 设置 pendingSessionId, 关闭弹窗, 等 afterClose 回调再导航.
  // 创建失败: 显示错误消息并关闭弹窗 (与原行为一致).
  const handleNewSessionSubmit = useCallback(async (values: { kb_id?: number; title?: string }) => {
    try {
      const session = await createSession(values.kb_id, values.title);
      pendingSessionId.current = session.id;
      setNewSessionModal(false);
    } catch (e: unknown) {
      message.error(getErrorMessage(e) || t('chat.createFailed'));
      setNewSessionModal(false);
    }
  }, [createSession, message, t]);

  const handleDeleteSession = useCallback(async (id: number) => {
    try {
      await deleteSession(id);
      if (id === sessionIdNum) {
        navigate('/chat');
      }
      message.success(t('chat.deleteSuccess'));
    } catch (e: unknown) {
      message.error(getErrorMessage(e) || t('chat.deleteFailed'));
    }
  }, [deleteSession, sessionIdNum, navigate, message, t]);

  // handleRegenerate 正常声明依赖: streaming 期间所有消息的 onRegenerate 为 undefined,
  // 故 handleRegenerate 引用变化不会触发 streaming 期间的额外重渲染 (Task 71 已改用默认 memo).
  const handleRegenerate = useCallback(() => {
    if (streaming) return; // 正在流式输出时禁止重新生成
    // 找到最后一条 user 消息
    for (let i = sessionMsgs.length - 1; i >= 0; i--) {
      if (sessionMsgs[i].role === 'user') {
        sendMessage(sessionIdNum, sessionMsgs[i].content, selectedModel || undefined);
        return;
      }
    }
  }, [streaming, sessionMsgs, sessionIdNum, selectedModel, sendMessage]);

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
      label: `${m.display_name} ${m.status === 'unhealthy' ? t('chat.modelOffline') : ''}`,
      value: m.name,
      disabled: m.status === 'unhealthy',
    })),
    [models, t]
  );

  // Task 39: 累计 token 统计 (input + output), 仅聚合 assistant 消息
  // 历史消息从后端读取 token 字段, 流式消息 done 事件未携带 token 故不计数 (下次 fetchMessages 时填充)
  const totalTokens = useMemo(() => {
    let input = 0;
    let output = 0;
    let hasAny = false;
    for (const msg of sessionMsgs) {
      if (msg.role !== 'assistant') continue;
      if (msg.token_input != null) {
        input += msg.token_input;
        hasAny = true;
      }
      if (msg.token_output != null) {
        output += msg.token_output;
        hasAny = true;
      }
    }
    return hasAny ? { input, output, total: input + output } : null;
  }, [sessionMsgs]);

  return (
    <Layout style={{ height: 'calc(100vh - 112px)' }}>
      {/* 左侧会话列表 */}
      <SessionSider
        siderVisible={siderVisible}
        sessions={sessions}
        sessionIdNum={sessionIdNum}
        onNavigate={(id) => navigate(`/chat/${id}`)}
        onDeleteSession={handleDeleteSession}
        onNewSessionClick={() => setNewSessionModal(true)}
        getKBName={getKBName}
      />

      <Layout>
        {/* 顶部栏 */}
        <ChatHeader
          onToggleSider={() => setSiderVisible(!siderVisible)}
          currentSession={currentSession}
          getKBName={getKBName}
          totalTokens={totalTokens}
        />

        {/* 消息列表 */}
        <ChatMessagesArea
          sessionMsgs={sessionMsgs}
          streaming={streaming}
          scrollContainerRef={scrollContainerRef}
          messagesEndRef={messagesEndRef}
          onRegenerate={handleRegenerate}
          onShowReferences={showReferences}
        />

        {/* 输入框 */}
        {/* 模型选择器 */}
        <ChatModelSelector
          selectedModel={selectedModel}
          onChange={setSelectedModel}
          modelOptions={modelOptions}
        />
        <ChatInput
          key={sessionIdNum}
          onSend={handleSend}
          onStop={stopStreaming}
          streaming={isCurrentSessionStreaming}
          kbName={currentSession?.kb_id ? getKBName(currentSession.kb_id) : undefined}
          modelName={models.find(m => m.name === selectedModel)?.display_name || t('chat.modelAuto')}
          placeholder={
            currentSession?.kb_id
              ? t('chat.inputPlaceholder')
              : t('chat.inputPlaceholderNoKB')
          }
        />
      </Layout>

      {/* 参考来源抽屉 */}
      <ReferencesDrawer
        open={referencesVisible}
        refs={currentRefs}
        onClose={() => setReferencesVisible(false)}
      />

      {/* 新建对话弹窗 */}
      <NewSessionModal
        open={newSessionModal}
        knowledgeBases={knowledgeBases}
        onSubmit={handleNewSessionSubmit}
        onCancel={() => setNewSessionModal(false)}
        afterClose={() => {
          if (pendingSessionId.current) {
            navigate(`/chat/${pendingSessionId.current}`);
            pendingSessionId.current = null;
          }
        }}
      />
    </Layout>
  );
}
