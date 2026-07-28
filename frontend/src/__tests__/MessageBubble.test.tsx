import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MessageBubble } from '../components/MessageBubble';
import { useChatStore } from '../store/chat';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string, params?: any) => {
    if (params && params.count !== undefined) return `${key} ${params.count}`;
    if (params && params.input !== undefined) return `${key} ${params.input}/${params.output}`;
    if (params && params.s !== undefined) return `${key} ${params.s}s`;
    if (params && params.ms !== undefined) return `${key} ${params.ms}ms`;
    return key;
  }}),
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

// Mock i18n 模块以避免初始化依赖
vi.mock('../i18n', () => ({
  globalT: (key: string, params?: any) => {
    if (params && params.count !== undefined) return `${key} ${params.count}`;
    return key;
  },
}));

// vi.hoisted 确保 mock 变量在 vi.mock factory 中可用
const { msgSuccess, msgError, msgWarning } = vi.hoisted(() => ({
  msgSuccess: vi.fn(),
  msgError: vi.fn(),
  msgWarning: vi.fn(),
}));

// Mock antd App
vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  return {
    ...(actual as any),
    App: Object.assign((actual as any).App, {
      useApp: () => ({ message: { success: msgSuccess, error: msgError, warning: msgWarning } }),
    }),
  };
});

// Mock format utils with trackable copyToClipboard
const { copyMock } = vi.hoisted(() => ({
  copyMock: vi.fn().mockResolvedValue(true),
}));

vi.mock('../utils/format', async () => {
  const actual = await vi.importActual('../utils/format');
  return {
    ...(actual as any),
    formatTime: (d: string) => d ? '2024-01-01' : '',
    copyToClipboard: copyMock,
  };
});

// Mock feedback API (getFeedback 被追踪以验证缓存)
// vi.hoisted 确保 mock 变量在 vi.mock factory 中可用 (vi.mock 会被提升到文件顶部)
const { getFeedbackMock, submitFeedbackMock } = vi.hoisted(() => ({
  getFeedbackMock: vi.fn().mockResolvedValue(null),
  submitFeedbackMock: vi.fn(),
}));
vi.mock('../api/chat', () => ({
  feedbackApi: {
    getFeedback: getFeedbackMock,
    submitFeedback: submitFeedbackMock,
  },
  default: {
    listSessions: vi.fn(),
    createSession: vi.fn(),
    deleteSession: vi.fn(),
    getSession: vi.fn(),
  },
  streamChat: vi.fn(),
}));

// Mock FeedbackModal to simplify testing
vi.mock('../components/FeedbackModal', () => ({
  __esModule: true,
  default: ({ open }: { open: boolean }) =>
    open ? <div data-testid="feedback-modal-mock" /> : null,
}));

describe('MessageBubble', () => {
  const defaultProps = {
    role: 'user' as const,
    content: 'Hello, how are you?',
  };

  beforeEach(() => {
    // 重置 chatStore 的 feedback 缓存, 避免测试间相互干扰
    useChatStore.setState({
      feedbackByMessageId: {},
      _fetchingFeedback: {},
    });
    getFeedbackMock.mockClear();
    getFeedbackMock.mockResolvedValue(null);
    submitFeedbackMock.mockClear();
    copyMock.mockClear();
    copyMock.mockResolvedValue(true);
    msgSuccess.mockClear();
    msgError.mockClear();
  });

  it('should render user message', () => {
    render(<MessageBubble {...defaultProps} />);
    expect(screen.getByText('Hello, how are you?')).toBeInTheDocument();
  });

  it('should render assistant message with copy button', () => {
    render(<MessageBubble role="assistant" content="I am fine, thank you!" />);
    expect(screen.getByText('I am fine, thank you!')).toBeInTheDocument();
    const copyBtn = screen.getByRole('button', { name: 'chat.copy' });
    expect(copyBtn).toBeTruthy();
  });

  it('should show thinking animation when streaming with no content', () => {
    render(<MessageBubble role="assistant" content="" isStreaming />);
    expect(screen.getByText('chat.thinking')).toBeInTheDocument();
  });

  it('should show references count for assistant message', () => {
    const refs = [
      { chunk_id: 1, doc_id: 1, filename: 'test.pdf', page: 1, snippet: 'test', score: 0.95 },
      { chunk_id: 2, doc_id: 1, filename: 'test.pdf', page: 2, snippet: 'test2', score: 0.9 },
    ];
    render(<MessageBubble role="assistant" content="Answer" references={refs} />);
    expect(screen.getByText(/chat.referencesCount 2/)).toBeInTheDocument();
  });

  it('should not show references for user message', () => {
    const refs = [
      { chunk_id: 1, doc_id: 1, filename: 'test.pdf', page: 1, snippet: 'test', score: 0.95 },
    ];
    render(<MessageBubble role="user" content="Question" references={refs} />);
    expect(screen.queryByText(/chat.referencesCount/)).not.toBeInTheDocument();
  });

  it('should call onRegenerate when regenerate button clicked', () => {
    const onRegenerate = vi.fn();
    render(
      <MessageBubble role="assistant" content="Answer" onRegenerate={onRegenerate} />
    );
    const btn = screen.getByRole('button', { name: 'chat.regenerate' });
    if (btn) {
      fireEvent.click(btn);
      expect(onRegenerate).toHaveBeenCalled();
    }
  });

  it('should not show action buttons when streaming', () => {
    render(<MessageBubble role="assistant" content="partial" isStreaming />);
    expect(screen.queryByTitle('chat.copy')).not.toBeInTheDocument();
  });

  it('should not trigger feedback fetch for user messages', () => {
    render(<MessageBubble role="user" content="Question" messageId={100} />);
    expect(getFeedbackMock).not.toHaveBeenCalled();
  });

  it('should not trigger feedback fetch when streaming', () => {
    render(<MessageBubble role="assistant" content="partial" messageId={101} isStreaming />);
    expect(getFeedbackMock).not.toHaveBeenCalled();
  });

  it('should not trigger feedback fetch when messageId is missing', () => {
    render(<MessageBubble role="assistant" content="Answer" />);
    expect(getFeedbackMock).not.toHaveBeenCalled();
  });

  it('Task 22: should not re-request feedback for same messageId (cache hit)', async () => {
    // 首次挂载: 触发拉取
    const { unmount } = render(<MessageBubble role="assistant" content="Answer 1" messageId={42} />);
    expect(getFeedbackMock).toHaveBeenCalledTimes(1);
    expect(getFeedbackMock).toHaveBeenCalledWith(42, expect.any(AbortSignal));

    // 等待异步拉取完成并写入缓存
    await vi.waitFor(() => {
      expect(useChatStore.getState().feedbackByMessageId[42]).not.toBeUndefined();
    });

    // 卸载后重新挂载: 命中缓存不应再次拉取
    unmount();
    render(<MessageBubble role="assistant" content="Answer 1" messageId={42} />);
    expect(getFeedbackMock).toHaveBeenCalledTimes(1);
  });

  it('Task 22: should request feedback for different messageIds', () => {
    render(<MessageBubble role="assistant" content="Answer A" messageId={201} />);
    render(<MessageBubble role="assistant" content="Answer B" messageId={202} />);
    expect(getFeedbackMock).toHaveBeenCalledWith(201, expect.any(AbortSignal));
    expect(getFeedbackMock).toHaveBeenCalledWith(202, expect.any(AbortSignal));
    expect(getFeedbackMock).toHaveBeenCalledTimes(2);
  });

  it('should show success message on copy success', async () => {
    copyMock.mockResolvedValue(true);
    render(<MessageBubble role="assistant" content="Copy me" messageId={1} />);
    const copyBtn = screen.getByRole('button', { name: 'chat.copy' });
    if (copyBtn) {
      fireEvent.click(copyBtn);
      await waitFor(() => {
        expect(msgSuccess).toHaveBeenCalledWith('chat.copied');
      });
    }
  });

  it('should show error message on copy failure', async () => {
    copyMock.mockResolvedValue(false);
    render(<MessageBubble role="assistant" content="Copy me" messageId={1} />);
    const copyBtn = screen.getByRole('button', { name: 'chat.copy' });
    if (copyBtn) {
      fireEvent.click(copyBtn);
      await waitFor(() => {
        expect(msgError).toHaveBeenCalledWith('chat.copyFailed');
      });
    }
  });

  it('should handle like button click and submit positive feedback', async () => {
    submitFeedbackMock.mockResolvedValue({ message_id: 1, rating: 1, comment: null, feedback_type: null });
    render(<MessageBubble role="assistant" content="Answer" messageId={1} />);
    const likeBtn = screen.getByRole('button', { name: 'chat.like' });
    if (likeBtn) {
      fireEvent.click(likeBtn);
      await waitFor(() => {
        expect(submitFeedbackMock).toHaveBeenCalledWith(1, { rating: 1 });
        expect(msgSuccess).toHaveBeenCalledWith('chat.feedbackThanks');
      });
    }
  });

  it('should handle like button error', async () => {
    submitFeedbackMock.mockRejectedValue(new Error('Network error'));
    render(<MessageBubble role="assistant" content="Answer" messageId={1} />);
    const likeBtn = screen.getByRole('button', { name: 'chat.like' });
    if (likeBtn) {
      fireEvent.click(likeBtn);
      await waitFor(() => {
        expect(msgError).toHaveBeenCalledWith('chat.feedbackFailed');
      });
    }
  });

  it('should open feedback modal on dislike button click', () => {
    render(<MessageBubble role="assistant" content="Answer" messageId={1} />);
    const dislikeBtn = screen.getByRole('button', { name: 'chat.dislike' });
    if (dislikeBtn) {
      fireEvent.click(dislikeBtn);
      expect(screen.getByTestId('feedback-modal-mock')).toBeInTheDocument();
    }
  });

  it('should render token chips when tokenInput or tokenOutput provided', () => {
    render(<MessageBubble role="assistant" content="Answer" messageId={1} tokenInput={100} tokenOutput={50} />);
    expect(screen.getByText(/chat.tokens/)).toBeInTheDocument();
  });

  it('should render latency chip in seconds when latencyMs >= 1000', () => {
    render(<MessageBubble role="assistant" content="Answer" messageId={1} latencyMs={1500} />);
    expect(screen.getByText(/chat.latencySeconds/)).toBeInTheDocument();
  });

  it('should render latency chip in milliseconds when latencyMs < 1000', () => {
    render(<MessageBubble role="assistant" content="Answer" messageId={1} latencyMs={500} />);
    expect(screen.getByText(/chat.latencyMillis/)).toBeInTheDocument();
  });

  it('should render createdAt time when provided', () => {
    render(<MessageBubble role="assistant" content="Answer" createdAt="2024-06-01T12:00:00Z" />);
    expect(screen.getByText('2024-01-01')).toBeInTheDocument();
  });

  it('should render empty content without streaming (no thinking dots, no content)', () => {
    render(<MessageBubble role="assistant" content="" />);
    expect(screen.queryByText('chat.thinking')).not.toBeInTheDocument();
  });
});
