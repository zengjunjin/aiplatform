import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import FeedbackModal from '../../components/FeedbackModal';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// Mock antd App.useApp
vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  return {
    ...(actual as any),
    App: Object.assign((actual as any).App, {
      useApp: () => ({
        message: {
          success: vi.fn(),
          error: vi.fn(),
          warning: vi.fn(),
        },
      }),
    }),
  };
});

// Mock feedbackApi - vi.hoisted ensures mock is available in vi.mock factory (hoisted)
const { submitFeedbackMock } = vi.hoisted(() => ({
  submitFeedbackMock: vi.fn(),
}));
vi.mock('../../api/chat', () => ({
  feedbackApi: {
    submitFeedback: submitFeedbackMock,
  },
}));

describe('FeedbackModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should render modal title and feedback type options when open', () => {
    render(
      <FeedbackModal
        open={true}
        messageId={1}
        onClose={() => {}}
        onSubmitted={() => {}}
      />
    );
    expect(screen.getByText('chat.feedbackTitle')).toBeInTheDocument();
    expect(screen.getByText('chat.feedbackTypeLabel')).toBeInTheDocument();
    expect(screen.getByText('chat.feedbackType.faithfulnessIssue')).toBeInTheDocument();
    expect(screen.getByText('chat.feedbackType.other')).toBeInTheDocument();
  });

  it('should render comment label and textarea', () => {
    render(
      <FeedbackModal
        open={true}
        messageId={1}
        onClose={() => {}}
        onSubmitted={() => {}}
      />
    );
    expect(screen.getByText('chat.feedbackCommentLabel')).toBeInTheDocument();
    // Textarea should exist
    const textarea = screen.getByRole('textbox');
    expect(textarea).toBeTruthy();
  });

  it('should render confirm and cancel buttons', () => {
    render(
      <FeedbackModal
        open={true}
        messageId={1}
        onClose={() => {}}
        onSubmitted={() => {}}
      />
    );
    expect(screen.getByText('common.confirm')).toBeInTheDocument();
    expect(screen.getByText('common.cancel')).toBeInTheDocument();
  });

  it('should call onClose when cancel button clicked', () => {
    const onClose = vi.fn();
    render(
      <FeedbackModal
        open={true}
        messageId={1}
        onClose={onClose}
        onSubmitted={() => {}}
      />
    );
    fireEvent.click(screen.getByText('common.cancel'));
    expect(onClose).toHaveBeenCalled();
  });

  it('should submit feedback and call onSubmitted on success', async () => {
    const mockFeedback = { id: 1, message_id: 1, rating: -1, comment: 'bad', feedback_type: 'other' };
    submitFeedbackMock.mockResolvedValue(mockFeedback);
    const onSubmitted = vi.fn();
    const onClose = vi.fn();

    render(
      <FeedbackModal
        open={true}
        messageId={10}
        onClose={onClose}
        onSubmitted={onSubmitted}
      />
    );

    // Click confirm button
    fireEvent.click(screen.getByText('common.confirm'));

    await waitFor(() => {
      expect(submitFeedbackMock).toHaveBeenCalledWith(10, {
        rating: -1,
        comment: undefined,
        feedback_type: undefined,
      });
    });

    await waitFor(() => {
      expect(onSubmitted).toHaveBeenCalledWith(mockFeedback);
      expect(onClose).toHaveBeenCalled();
    });
  });

  it('should not submit when messageId is missing', async () => {
    render(
      <FeedbackModal
        open={true}
        messageId={undefined}
        onClose={() => {}}
        onSubmitted={() => {}}
      />
    );

    fireEvent.click(screen.getByText('common.confirm'));

    // Wait a tick to ensure no call
    await new Promise((r) => setTimeout(r, 50));
    expect(submitFeedbackMock).not.toHaveBeenCalled();
  });

  it('should handle submit failure gracefully', async () => {
    submitFeedbackMock.mockRejectedValue(new Error('network error'));
    const onSubmitted = vi.fn();
    const onClose = vi.fn();

    render(
      <FeedbackModal
        open={true}
        messageId={1}
        onClose={onClose}
        onSubmitted={onSubmitted}
      />
    );

    fireEvent.click(screen.getByText('common.confirm'));

    await waitFor(() => {
      expect(submitFeedbackMock).toHaveBeenCalled();
    });

    // onSubmitted should not be called on failure
    await new Promise((r) => setTimeout(r, 50));
    expect(onSubmitted).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('should allow selecting feedback type radio option', () => {
    render(
      <FeedbackModal
        open={true}
        messageId={1}
        onClose={() => {}}
        onSubmitted={() => {}}
      />
    );
    const radioInputs = screen.getAllByRole('radio');
    expect(radioInputs.length).toBeGreaterThan(0);
    // Click first radio
    if (radioInputs[0]) {
      fireEvent.click(radioInputs[0]);
    }
  });

  it('should allow typing in comment textarea', () => {
    render(
      <FeedbackModal
        open={true}
        messageId={1}
        onClose={() => {}}
        onSubmitted={() => {}}
      />
    );
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    if (textarea) {
      fireEvent.change(textarea, { target: { value: 'This is a comment' } });
      expect(textarea.value).toBe('This is a comment');
    }
  });

  it('should submit with comment and feedback_type when provided', async () => {
    submitFeedbackMock.mockResolvedValue({ id: 1 });
    const onSubmitted = vi.fn();

    render(
      <FeedbackModal
        open={true}
        messageId={5}
        onClose={() => {}}
        onSubmitted={onSubmitted}
      />
    );

    // Select first radio option
    const radioInputs = screen.getAllByRole('radio');
    if (radioInputs[0]) {
      fireEvent.click(radioInputs[0]);
    }

    // Type comment
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    if (textarea) {
      fireEvent.change(textarea, { target: { value: 'My comment' } });
    }

    fireEvent.click(screen.getByText('common.confirm'));

    await waitFor(() => {
      expect(submitFeedbackMock).toHaveBeenCalledWith(5, expect.objectContaining({
        rating: -1,
        comment: 'My comment',
      }));
    });
  });
});
