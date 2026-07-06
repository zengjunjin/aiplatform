import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ChatInput from '../components/ChatInput';

describe('ChatInput', () => {
  const defaultProps = {
    onSend: vi.fn(),
    onStop: vi.fn(),
    streaming: false,
  };

  it('should render input and send button', () => {
    render(<ChatInput {...defaultProps} />);
    expect(screen.getByPlaceholderText(/Enter 发送/)).toBeInTheDocument();
    expect(screen.getByText('发送')).toBeInTheDocument();
  });

  it('should call onSend when send button clicked', () => {
    render(<ChatInput {...defaultProps} />);
    const textarea = screen.getByPlaceholderText(/Enter 发送/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'Hello' } });

    const sendBtn = screen.getByText('发送');
    fireEvent.click(sendBtn);

    expect(defaultProps.onSend).toHaveBeenCalledWith('Hello');
    expect(textarea.value).toBe('');
  });

  it('should disable send button when input is empty', () => {
    render(<ChatInput {...defaultProps} />);
    const sendBtn = screen.getByRole('button', { name: /发送/i });
    expect(sendBtn).toBeDisabled();
  });

  it('should show stop button when streaming', () => {
    render(<ChatInput {...defaultProps} streaming />);
    expect(screen.getByText('停止')).toBeInTheDocument();
    expect(screen.queryByText('发送')).not.toBeInTheDocument();
  });

  it('should call onStop when stop button clicked', () => {
    render(<ChatInput {...defaultProps} streaming />);
    const stopBtn = screen.getByText('停止');
    fireEvent.click(stopBtn);
    expect(defaultProps.onStop).toHaveBeenCalled();
  });

  it('should disable input when disabled prop is true', () => {
    render(<ChatInput {...defaultProps} disabled />);
    const textarea = screen.getByPlaceholderText(/Enter 发送/) as HTMLTextAreaElement;
    expect(textarea).toBeDisabled();
  });

  it('should show character count', () => {
    render(<ChatInput {...defaultProps} />);
    const textarea = screen.getByPlaceholderText(/Enter 发送/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'hello' } });
    expect(screen.getByText(/5 \/ 2000/)).toBeInTheDocument();
  });
});
