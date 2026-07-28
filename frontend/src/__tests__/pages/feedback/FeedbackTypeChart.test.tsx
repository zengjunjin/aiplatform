import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import FeedbackTypeChart from '../../../pages/feedback/FeedbackTypeChart';
import type { FeedbackStats, FeedbackDetail } from '../../../api/chat';

// Mock react-i18next - t 函数引用必须稳定
const stableT = (key: string) => key;
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: stableT }),
}));

// Mock echarts-for-react 避免 canvas 渲染
vi.mock('echarts-for-react/lib/core', () => ({
  __esModule: true,
  default: (props: any) => (
    <div data-testid="echarts-mock" aria-label={props['aria-label'] || ''} />
  ),
}));

vi.mock('echarts/core', () => ({
  __esModule: true,
  default: { use: vi.fn() },
  use: vi.fn(),
}));

const mockStats: FeedbackStats = {
  total_feedback: 5,
  positive_rate: 0.6,
  negative_rate: 0.4,
  by_type: {
    faithfulness_issue: 2,
    incompleteness: 1,
    irrelevant: 1,
    faithfulness_issue: 1,
  },
};

const mockFeedbacks: FeedbackDetail[] = [
  {
    id: 1,
    message_id: 100,
    rating: -1,
    comment: 'bad',
    feedback_type: 'faithfulness_issue',
    created_at: '2026-07-01T00:00:00Z',
    question: 'q1',
    answer: 'a1',
    session_id: 1,
    kb_id: 1,
  },
  {
    id: 2,
    message_id: 101,
    rating: -1,
    comment: null,
    feedback_type: 'incompleteness',
    created_at: '2026-07-02T00:00:00Z',
    question: 'q2',
    answer: 'a2',
    session_id: 1,
    kb_id: 1,
  },
];

describe('FeedbackTypeChart', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should render nothing when stats is null', () => {
    const { container } = render(
      <FeedbackTypeChart stats={null} feedbacks={[]} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('should render nothing when stats.by_type is empty', () => {
    const { container } = render(
      <FeedbackTypeChart
        stats={{ total_feedback: 0, positive_rate: 0, negative_rate: 0, by_type: {} }}
        feedbacks={[]}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('should render type distribution card title when stats has by_type', () => {
    render(<FeedbackTypeChart stats={mockStats} feedbacks={[]} />);
    expect(screen.getByText('feedback.typeDistribution')).toBeInTheDocument();
  });

  it('should render daily feedback trend card title', () => {
    render(<FeedbackTypeChart stats={mockStats} feedbacks={[]} />);
    expect(screen.getByText('feedback.dailyFeedbackTrend')).toBeInTheDocument();
  });

  it('should render two ECharts when stats and feedbacks present', () => {
    render(<FeedbackTypeChart stats={mockStats} feedbacks={mockFeedbacks} />);
    const charts = screen.getAllByTestId('echarts-mock');
    expect(charts).toHaveLength(2);
  });

  it('should render only one ECharts (no daily stacked) when feedbacks is empty', () => {
    render(<FeedbackTypeChart stats={mockStats} feedbacks={[]} />);
    const charts = screen.getAllByTestId('echarts-mock');
    // typeBarOption 总是渲染，dailyStackedOption 为 null → Empty
    expect(charts).toHaveLength(1);
    // Empty 占位应渲染
    expect(screen.getByText('common.noData')).toBeInTheDocument();
  });

  it('should render Empty when feedbacks is null', () => {
    render(<FeedbackTypeChart stats={mockStats} feedbacks={null as any} />);
    expect(screen.getByText('common.noData')).toBeInTheDocument();
  });

  it('should render Empty when feedbacks is empty array', () => {
    render(<FeedbackTypeChart stats={mockStats} feedbacks={[]} />);
    expect(screen.getByText('common.noData')).toBeInTheDocument();
  });

  it('should render daily stacked chart with aria-label', () => {
    render(<FeedbackTypeChart stats={mockStats} feedbacks={mockFeedbacks} />);
    const labeled = screen
      .getAllByTestId('echarts-mock')
      .find((el) => el.getAttribute('aria-label') === 'feedback.dailyFeedbackTrend');
    expect(labeled).toBeInTheDocument();
  });

  it('should handle feedback with null feedback_type (defaults to other)', () => {
    const fbs: FeedbackDetail[] = [
      {
        ...mockFeedbacks[0],
        feedback_type: null,
      },
    ];
    // 不应崩溃
    const { container } = render(<FeedbackTypeChart stats={mockStats} feedbacks={fbs} />);
    expect(container.querySelectorAll('[data-testid="echarts-mock"]').length).toBeGreaterThan(0);
  });

  it('should handle feedback with unknown feedback_type', () => {
    const fbs: FeedbackDetail[] = [
      {
        ...mockFeedbacks[0],
        feedback_type: 'unknown_type',
      },
    ];
    const { container } = render(<FeedbackTypeChart stats={mockStats} feedbacks={fbs} />);
    expect(container.querySelectorAll('[data-testid="echarts-mock"]').length).toBeGreaterThan(0);
  });

  it('should re-render properly when stats changes', () => {
    const { rerender } = render(<FeedbackTypeChart stats={mockStats} feedbacks={[]} />);
    expect(screen.getByText('feedback.typeDistribution')).toBeInTheDocument();

    const newStats: FeedbackStats = {
      total_feedback: 3,
      positive_rate: 0.5,
      negative_rate: 0.5,
      by_type: { verbosity: 2 },
    };
    rerender(<FeedbackTypeChart stats={newStats} feedbacks={[]} />);
    expect(screen.getByText('feedback.typeDistribution')).toBeInTheDocument();
  });

  it('should switch from null to populated stats', () => {
    const { container, rerender } = render(
      <FeedbackTypeChart stats={null} feedbacks={[]} />,
    );
    expect(container.firstChild).toBeNull();

    rerender(<FeedbackTypeChart stats={mockStats} feedbacks={mockFeedbacks} />);
    expect(screen.getByText('feedback.typeDistribution')).toBeInTheDocument();
    expect(screen.getAllByTestId('echarts-mock')).toHaveLength(2);
  });
});
