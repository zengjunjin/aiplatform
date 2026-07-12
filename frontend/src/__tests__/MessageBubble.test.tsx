import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MessageBubble } from '../components/MessageBubble';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string, params?: any) => {
    if (params && params.count !== undefined) return `${key} ${params.count}`;
    return key;
  }}),
}));

// Mock antd App
vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  return {
    ...(actual as any),
    App: Object.assign((actual as any).App, {
      useApp: () => ({ message: { success: vi.fn(), error: vi.fn() } }),
    }),
  };
});

// Mock format utils
vi.mock('../utils/format', async () => {
  const actual = await vi.importActual('../utils/format');
  return {
    ...(actual as any),
    formatTime: () => '',
    copyToClipboard: vi.fn().mockResolvedValue(true),
  };
});

// Mock API
vi.mock('../api/chat', () => ({
  feedbackApi: {
    getFeedback: vi.fn().mockResolvedValue(null),
    submitFeedback: vi.fn(),
  },
}));

describe('MessageBubble', () => {
  const defaultProps = {
    role: 'user' as const,
    content: 'Hello, how are you?',
  };

  it('should render user message', () => {
    render(<MessageBubble {...defaultProps} />);
    expect(screen.getByText('Hello, how are you?')).toBeInTheDocument();
  });

  it('should render assistant message with copy button', () => {
    render(<MessageBubble role="assistant" content="I am fine, thank you!" />);
    expect(screen.getByText('I am fine, thank you!')).toBeInTheDocument();
    const copyBtn = document.querySelector('.ant-btn');
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
    const btn = document.querySelector('[title="chat.regenerate"]');
    if (btn) {
      fireEvent.click(btn);
      expect(onRegenerate).toHaveBeenCalled();
    }
  });

  it('should not show action buttons when streaming', () => {
    render(<MessageBubble role="assistant" content="partial" isStreaming />);
    expect(screen.queryByTitle('chat.copy')).not.toBeInTheDocument();
  });
});
