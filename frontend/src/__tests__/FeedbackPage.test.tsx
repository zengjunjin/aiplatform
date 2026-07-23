import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import FeedbackPage from '../pages/FeedbackPage';

// Mock react-i18next - t 函数引用必须稳定
const stableT = (key: string, params?: any) => {
  if (params && params.count !== undefined) return `${key} ${params.count}`;
  return key;
};
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: stableT }),
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

vi.mock('../i18n', () => ({
  globalT: (key: string) => key,
}));

// Mock API
const mockGetStats = vi.fn();
const mockGetLowRated = vi.fn();
const mockGetAnalysis = vi.fn();

vi.mock('../api/chat', () => ({
  feedbackApi: {
    getStats: (...args: any[]) => mockGetStats(...args),
    getLowRated: (...args: any[]) => mockGetLowRated(...args),
    getAnalysis: (...args: any[]) => mockGetAnalysis(...args),
  },
}));

// Mock echarts-for-react 避免 canvas 渲染
vi.mock('echarts-for-react/lib/core', () => ({
  __esModule: true,
  default: () => <div data-testid="echarts-mock" />,
}));

vi.mock('echarts/core', () => ({
  __esModule: true,
  default: { use: vi.fn() },
  use: vi.fn(),
}));

vi.mock('echarts/charts', () => ({
  BarChart: {},
  LineChart: {},
  HeatmapChart: {},
}));

vi.mock('echarts/components', () => ({
  GridComponent: {},
  TooltipComponent: {},
  LegendComponent: {},
  TitleComponent: {},
  CalendarComponent: {},
  VisualMapComponent: {},
}));

vi.mock('echarts/renderers', () => ({
  CanvasRenderer: {},
}));

vi.mock('../api', () => ({
  kbApi: {
    list: vi.fn().mockResolvedValue({ items: [{ id: 1, name: 'TestKB' }] }),
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

describe('FeedbackPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetStats.mockResolvedValue({
      total_feedback: 0,
      positive_rate: 0.0,
      negative_rate: 0.0,
      by_type: {},
    });
    mockGetLowRated.mockResolvedValue({ items: [], total: 0 });
    mockGetAnalysis.mockResolvedValue({
      period: { start: '2026-07-01T00:00:00Z', end: '2026-07-08T00:00:00Z' },
      stats: { total_feedback: 0, positive_rate: 0, negative_rate: 0, by_type: {} },
      low_rated_count: 0,
      failure_patterns: {},
      suggestions: [],
      low_rated_samples: [],
    });
  });

  it('should render the page title', () => {
    render(
      <MemoryRouter>
        <FeedbackPage />
      </MemoryRouter>
    );
    expect(screen.getByText('feedback.title')).toBeInTheDocument();
  });

  it('should render the four stats cards', () => {
    render(
      <MemoryRouter>
        <FeedbackPage />
      </MemoryRouter>
    );
    expect(screen.getByText('feedback.totalFeedback')).toBeInTheDocument();
    expect(screen.getByText('feedback.positiveRate')).toBeInTheDocument();
    expect(screen.getByText('feedback.negativeRate')).toBeInTheDocument();
    expect(screen.getByText('feedback.byType')).toBeInTheDocument();
  });

  it('should render the low-rated answers section', () => {
    render(
      <MemoryRouter>
        <FeedbackPage />
      </MemoryRouter>
    );
    expect(screen.getByText('feedback.lowRatedAnswers')).toBeInTheDocument();
  });

  it('should show empty state when no feedbacks', async () => {
    render(
      <MemoryRouter>
        <FeedbackPage />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText('feedback.noFeedbackData')).toBeInTheDocument();
    });
  });

  it('should call getStats on mount', async () => {
    render(
      <MemoryRouter>
        <FeedbackPage />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(mockGetStats).toHaveBeenCalled();
    });
  });

  it('should call getLowRated on mount', async () => {
    render(
      <MemoryRouter>
        <FeedbackPage />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalled();
    });
  });

  it('should render feedback rows when data is loaded', async () => {
    mockGetLowRated.mockResolvedValue({
      items: [
        {
          id: 42,
          message_id: 100,
          rating: -1,
          comment: 'bad answer',
          feedback_type: 'hallucination',
          created_at: '2026-07-01T00:00:00Z',
          question: '什么是 RAG？',
          answer: 'RAG 是错误的回答',
          session_id: 1,
          kb_id: 5,
        },
      ],
      total: 1,
    });

    render(
      <MemoryRouter>
        <FeedbackPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      // 通过 comment 列显示的内容
      expect(screen.getByText('bad answer')).toBeInTheDocument();
    });
    // 问题列也应显示
    expect(screen.getByText('什么是 RAG？')).toBeInTheDocument();
  });

  it('should render type distribution chart when stats has by_type', async () => {
    mockGetStats.mockResolvedValue({
      total_feedback: 5,
      positive_rate: 0.6,
      negative_rate: 0.4,
      by_type: {
        hallucination: 2,
        incomplete: 1,
      },
    });

    render(
      <MemoryRouter>
        <FeedbackPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      // 类型分布卡片标题应渲染
      expect(screen.getByText('feedback.typeDistribution')).toBeInTheDocument();
      // 每日堆叠柱状图卡片标题应渲染
      expect(screen.getByText('feedback.dailyFeedbackTrend')).toBeInTheDocument();
    });
  });

  it('should display positive rate and negative rate as percentage', async () => {
    mockGetStats.mockResolvedValue({
      total_feedback: 10,
      positive_rate: 0.7,
      negative_rate: 0.3,
      by_type: {},
    });

    render(
      <MemoryRouter>
        <FeedbackPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      // antd Statistic 把数值分成整数和小数部分用不同 span 显示
      // 0.7 * 100 = 70.0 → 整数部分 "70"
      const positiveInt = screen.getByText('70');
      expect(positiveInt).toBeInTheDocument();
    });
    // 0.3 * 100 = 30.0
    expect(screen.getByText('30')).toBeInTheDocument();
  });
});
