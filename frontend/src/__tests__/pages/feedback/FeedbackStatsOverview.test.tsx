import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import FeedbackStatsOverview from '../../../pages/feedback/FeedbackStatsOverview';

// Mock react-i18next - t 函数引用必须稳定
const stableT = (key: string) => key;
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: stableT }),
}));

// Mock feedbackApi
const mockGetStats = vi.fn();
vi.mock('../../../api/chat', () => ({
  feedbackApi: {
    getStats: (...args: any[]) => mockGetStats(...args),
  },
}));

// Mock antd App - message 引用稳定
const stableMessage = {
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
};
vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  return {
    ...(actual as any),
    App: Object.assign((actual as any).App, {
      useApp: () => ({ message: stableMessage }),
    }),
  };
});

// Mock errorReporter
vi.mock('../../../utils/errorReporter', () => ({
  getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));

describe('FeedbackStatsOverview', () => {
  const onStatsChange = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockGetStats.mockResolvedValue({
      total_feedback: 0,
      positive_rate: 0,
      negative_rate: 0,
      by_type: {},
    });
  });

  it('should render four stat cards on mount', () => {
    render(<FeedbackStatsOverview selectedKbId={undefined} onStatsChange={onStatsChange} />);
    expect(screen.getByText('feedback.totalFeedback')).toBeInTheDocument();
    expect(screen.getByText('feedback.positiveRate')).toBeInTheDocument();
    expect(screen.getByText('feedback.negativeRate')).toBeInTheDocument();
    expect(screen.getByText('feedback.byType')).toBeInTheDocument();
  });

  it('should call getStats on mount', async () => {
    render(<FeedbackStatsOverview selectedKbId={undefined} onStatsChange={onStatsChange} />);
    await waitFor(() => {
      expect(mockGetStats).toHaveBeenCalledWith(undefined);
    });
  });

  it('should call onStatsChange with fetched stats', async () => {
    const stats = {
      total_feedback: 10,
      positive_rate: 0.7,
      negative_rate: 0.3,
      by_type: { hallucination: 3 },
    };
    mockGetStats.mockResolvedValue(stats);

    render(<FeedbackStatsOverview selectedKbId={1} onStatsChange={onStatsChange} />);

    await waitFor(() => {
      expect(onStatsChange).toHaveBeenCalledWith(stats);
    });
  });

  it('should pass selectedKbId to getStats', async () => {
    render(<FeedbackStatsOverview selectedKbId={5} onStatsChange={onStatsChange} />);
    await waitFor(() => {
      expect(mockGetStats).toHaveBeenCalledWith(5);
    });
  });

  it('should show error message when getStats fails', async () => {
    mockGetStats.mockRejectedValue(new Error('stats failed'));

    render(<FeedbackStatsOverview selectedKbId={undefined} onStatsChange={onStatsChange} />);

    await waitFor(() => {
      expect(stableMessage.error).toHaveBeenCalledWith('stats failed');
    });
  });

  it('should fall back to t(feedback.loadStatsFailed) when error has no message', async () => {
    // getErrorMessage('') = String('') = '' (falsy) → 回退到 t(feedback.loadStatsFailed)
    mockGetStats.mockRejectedValue('');

    render(<FeedbackStatsOverview selectedKbId={undefined} onStatsChange={onStatsChange} />);

    await waitFor(() => {
      expect(stableMessage.error).toHaveBeenCalledWith('feedback.loadStatsFailed');
    });
  });

  it('should display total_feedback value when stats loaded', async () => {
    mockGetStats.mockResolvedValue({
      total_feedback: 42,
      positive_rate: 0.5,
      negative_rate: 0.5,
      by_type: { hallucination: 1, incomplete: 2 },
    });

    render(<FeedbackStatsOverview selectedKbId={undefined} onStatsChange={onStatsChange} />);

    await waitFor(() => {
      expect(screen.getByText('42')).toBeInTheDocument();
    });
  });

  it('should display positive rate as percentage (e.g. 70.0)', async () => {
    mockGetStats.mockResolvedValue({
      total_feedback: 10,
      positive_rate: 0.7,
      negative_rate: 0.3,
      by_type: {},
    });

    render(<FeedbackStatsOverview selectedKbId={undefined} onStatsChange={onStatsChange} />);

    await waitFor(() => {
      // antd Statistic 把整数部分单独显示
      expect(screen.getByText('70')).toBeInTheDocument();
    });
  });

  it('should display negative rate as percentage (e.g. 30.0)', async () => {
    mockGetStats.mockResolvedValue({
      total_feedback: 10,
      positive_rate: 0.7,
      negative_rate: 0.3,
      by_type: {},
    });

    render(<FeedbackStatsOverview selectedKbId={undefined} onStatsChange={onStatsChange} />);

    await waitFor(() => {
      expect(screen.getByText('30')).toBeInTheDocument();
    });
  });

  it('should display by_type count when stats has by_type', async () => {
    mockGetStats.mockResolvedValue({
      total_feedback: 5,
      positive_rate: 0.6,
      negative_rate: 0.4,
      by_type: { hallucination: 2, incomplete: 1, irrelevant: 1 },
    });

    render(<FeedbackStatsOverview selectedKbId={undefined} onStatsChange={onStatsChange} />);

    await waitFor(() => {
      expect(screen.getByText('3')).toBeInTheDocument();
    });
  });

  it('should display 0 for total_feedback when stats is null', () => {
    mockGetStats.mockResolvedValue(null as any);

    render(<FeedbackStatsOverview selectedKbId={undefined} onStatsChange={onStatsChange} />);

    // stats 为 null 时，所有 Statistic 都显示 0 (|| 0 保护)
    // total_feedback / positive_rate / negative_rate / by_type 均为 0
    const zeros = screen.getAllByText('0');
    expect(zeros.length).toBeGreaterThanOrEqual(1);
  });

  it('should re-fetch when selectedKbId changes', async () => {
    const { rerender } = render(
      <FeedbackStatsOverview selectedKbId={1} onStatsChange={onStatsChange} />,
    );
    await waitFor(() => {
      expect(mockGetStats).toHaveBeenCalledWith(1);
    });

    rerender(<FeedbackStatsOverview selectedKbId={2} onStatsChange={onStatsChange} />);

    await waitFor(() => {
      expect(mockGetStats).toHaveBeenCalledWith(2);
    });
  });
});
