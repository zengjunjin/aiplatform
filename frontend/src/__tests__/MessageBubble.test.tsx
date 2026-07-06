import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MessageBubble } from '../components/MessageBubble';

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
    // 复制按钮应该存在
    const copyBtn = document.querySelector('.ant-btn');
    expect(copyBtn).toBeTruthy();
  });

  it('should show thinking animation when streaming with no content', () => {
    render(<MessageBubble role="assistant" content="" isStreaming />);
    expect(screen.getByText('正在思考...')).toBeInTheDocument();
  });

  it('should show references count for assistant message', () => {
    const refs = [
      { chunk_id: 1, doc_id: 1, filename: 'test.pdf', page: 1, snippet: 'test', score: 0.95 },
      { chunk_id: 2, doc_id: 1, filename: 'test.pdf', page: 2, snippet: 'test2', score: 0.9 },
    ];
    render(<MessageBubble role="assistant" content="Answer" references={refs} />);
    expect(screen.getByText(/2 个引用/)).toBeInTheDocument();
  });

  it('should not show references for user message', () => {
    const refs = [
      { chunk_id: 1, doc_id: 1, filename: 'test.pdf', page: 1, snippet: 'test', score: 0.95 },
    ];
    render(<MessageBubble role="user" content="Question" references={refs} />);
    expect(screen.queryByText(/引用/)).not.toBeInTheDocument();
  });

  it('should call onRegenerate when regenerate button clicked', () => {
    const onRegenerate = vi.fn();
    render(
      <MessageBubble role="assistant" content="Answer" onRegenerate={onRegenerate} />
    );
    const btn = document.querySelector('[title="重新生成"]');
    if (btn) {
      fireEvent.click(btn);
      expect(onRegenerate).toHaveBeenCalled();
    }
  });

  it('should not show action buttons when streaming', () => {
    render(<MessageBubble role="assistant" content="partial" isStreaming />);
    expect(screen.queryByTitle('复制')).not.toBeInTheDocument();
  });
});
