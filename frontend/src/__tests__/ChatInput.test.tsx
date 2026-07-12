import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ChatInput from '../components/ChatInput';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe('ChatInput', () => {
  const defaultProps = {
    onSend: vi.fn(),
    onStop: vi.fn(),
    streaming: false,
  };

  it('should render input and send button', () => {
    render(<ChatInput {...defaultProps} />);
    expect(screen.getByPlaceholderText('chat.inputPlaceholder')).toBeInTheDocument();
    expect(screen.getByText('chat.send')).toBeInTheDocument();
  });

  it('should call onSend when send button clicked', () => {
    render(<ChatInput {...defaultProps} />);
    const textarea = screen.getByPlaceholderText('chat.inputPlaceholder') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'Hello' } });

    const sendBtn = screen.getByText('chat.send');
    fireEvent.click(sendBtn);

    expect(defaultProps.onSend).toHaveBeenCalledWith('Hello');
    expect(textarea.value).toBe('');
  });

  it('should disable send button when input is empty', () => {
    render(<ChatInput {...defaultProps} />);
    const sendBtn = screen.getByRole('button', { name: /chat.send/i });
    expect(sendBtn).toBeDisabled();
  });

  it('should show stop button when streaming', () => {
    render(<ChatInput {...defaultProps} streaming />);
    expect(screen.getByText('chat.stop')).toBeInTheDocument();
    expect(screen.queryByText('chat.send')).not.toBeInTheDocument();
  });

  it('should call onStop when stop button clicked', () => {
    render(<ChatInput {...defaultProps} streaming />);
    const stopBtn = screen.getByText('chat.stop');
    fireEvent.click(stopBtn);
    expect(defaultProps.onStop).toHaveBeenCalled();
  });

  it('should disable input when disabled prop is true', () => {
    render(<ChatInput {...defaultProps} disabled />);
    const textarea = screen.getByPlaceholderText('chat.inputPlaceholder') as HTMLTextAreaElement;
    expect(textarea).toBeDisabled();
  });

  it('should show character count', () => {
    render(<ChatInput {...defaultProps} />);
    const textarea = screen.getByPlaceholderText('chat.inputPlaceholder') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'hello' } });
    expect(screen.getByText(/5 \/ 2000/)).toBeInTheDocument();
  });
});
