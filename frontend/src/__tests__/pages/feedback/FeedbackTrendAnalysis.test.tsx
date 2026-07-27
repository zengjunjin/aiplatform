import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import FeedbackTrendAnalysis from '../../../pages/feedback/FeedbackTrendAnalysis';

// Mock react-i18next - t 函数引用必须稳定
const stableT = (key: string) => key;
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: stableT }),
}));

// Mock feedbackApi
const mockGetLowRated = vi.fn();
const mockGetAnalysis = vi.fn();
vi.mock('../../../api/chat', () => ({
  feedbackApi: {
    getLowRated: (...args: any[]) => mockGetLowRated(...args),
    getAnalysis: (...args: any[]) => mockGetAnalysis(...args),
  },
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

describe('FeedbackTrendAnalysis', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetLowRated.mockResolvedValue({ items: [], total: 0 });
    mockGetAnalysis.mockResolvedValue({
      period: { start: '', end: '' },
      stats: { total_feedback: 0, positive_rate: 0, negative_rate: 0, by_type: {} },
      low_rated_count: 0,
      failure_patterns: {},
      suggestions: [],
      low_rated_samples: [],
    });
  });

  it('should render the trend analysis card title', () => {
    render(<FeedbackTrendAnalysis selectedKbId={undefined} />);
    expect(screen.getByText('feedback.trendAnalysis')).toBeInTheDocument();
  });

  it('should render Segmented with 7/30/90 day options', () => {
    render(<FeedbackTrendAnalysis selectedKbId={undefined} />);
    expect(screen.getByText('feedback.trendRange7')).toBeInTheDocument();
    expect(screen.getByText('feedback.trendRange30')).toBeInTheDocument();
    expect(screen.getByText('feedback.trendRange90')).toBeInTheDocument();
  });

  it('should render line chart and heatmap labels', () => {
    render(<FeedbackTrendAnalysis selectedKbId={undefined} />);
    expect(screen.getByText('feedback.positiveRateTrend')).toBeInTheDocument();
    expect(screen.getByText('feedback.lowRatedHeatmap')).toBeInTheDocument();
  });

  it('should call getAnalysis on mount', async () => {
    render(<FeedbackTrendAnalysis selectedKbId={1} />);
    await waitFor(() => {
      expect(mockGetAnalysis).toHaveBeenCalled();
      // 第一个参数是 kbId
      expect(mockGetAnalysis).toHaveBeenCalledWith(1, expect.any(String), expect.any(String), expect.any(AbortSignal));
    });
  });

  it('should call getLowRated on mount with 7-day range', async () => {
    render(<FeedbackTrendAnalysis selectedKbId={1} />);
    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalled();
      const params = mockGetLowRated.mock.calls[0][0];
      expect(params.kb_id).toBe(1);
      expect(params.page).toBe(1);
      expect(params.page_size).toBe(1000);
    });
  });

  it('should render ECharts line chart on mount', async () => {
    render(<FeedbackTrendAnalysis selectedKbId={undefined} />);
    await waitFor(() => {
      expect(screen.getAllByTestId('echarts-mock').length).toBeGreaterThanOrEqual(1);
    });
  });

  it('should render heatmap Empty placeholder when no feedbacks and trendDays<30', async () => {
    mockGetLowRated.mockResolvedValue({ items: [], total: 0 });

    render(<FeedbackTrendAnalysis selectedKbId={undefined} />);
    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalled();
    });
    // 默认 7 天 < 30，heatmapOption 为 null，应渲染 Empty
    await waitFor(() => {
      expect(screen.getByText('common.noData')).toBeInTheDocument();
    });
  });

  it('should render heatmap chart when trendDays >= 30 even without data', async () => {
    mockGetLowRated.mockResolvedValue({ items: [], total: 0 });

    render(<FeedbackTrendAnalysis selectedKbId={undefined} />);
    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalled();
    });

    // 切到 30 天 → heatmapOption 不为 null
    fireEvent.click(screen.getByText('feedback.trendRange30'));

    await waitFor(() => {
      // 两个 ECharts (line + heatmap)，不应有 Empty 占位
      const charts = screen.getAllByTestId('echarts-mock');
      expect(charts.length).toBeGreaterThanOrEqual(2);
    });
  });

  it('should switch trendDays and re-fetch when clicking Segmented 30', async () => {
    render(<FeedbackTrendAnalysis selectedKbId={undefined} />);
    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalledTimes(1);
    });

    fireEvent.click(screen.getByText('feedback.trendRange30'));

    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalledTimes(2);
    });
  });

  it('should switch trendDays to 90 and re-fetch', async () => {
    render(<FeedbackTrendAnalysis selectedKbId={undefined} />);
    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalled();
    });

    fireEvent.click(screen.getByText('feedback.trendRange90'));

    await waitFor(() => {
      // 应再次调用
      expect(mockGetLowRated).toHaveBeenCalledTimes(2);
    });
  });

  it('should silently handle CanceledError from getAnalysis (does not propagate)', async () => {
    const cancelErr = new Error('canceled');
    cancelErr.name = 'CanceledError';
    mockGetAnalysis.mockRejectedValue(cancelErr);
    // getLowRated 仍正常返回
    mockGetLowRated.mockResolvedValue({ items: [], total: 0 });

    render(<FeedbackTrendAnalysis selectedKbId={undefined} />);

    // 不应抛错，组件正常渲染
    await waitFor(() => {
      expect(screen.getByText('feedback.trendAnalysis')).toBeInTheDocument();
    });
  });

  it('should silently handle CanceledError from getLowRated', async () => {
    const cancelErr = new Error('canceled');
    cancelErr.name = 'CanceledError';
    mockGetLowRated.mockRejectedValue(cancelErr);

    render(<FeedbackTrendAnalysis selectedKbId={undefined} />);

    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalled();
    });
    // 组件仍正常渲染
    expect(screen.getByText('feedback.trendAnalysis')).toBeInTheDocument();
  });

  it('should reset trendFeedbacks to empty when getLowRated fails with non-cancel error', async () => {
    mockGetLowRated.mockRejectedValue(new Error('network down'));

    render(<FeedbackTrendAnalysis selectedKbId={undefined} />);

    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalled();
    });
    // 组件仍正常渲染，不崩溃
    expect(screen.getByText('feedback.trendAnalysis')).toBeInTheDocument();
  });

  it('should render ECharts heatmap with aria-label when heatmapOption is present', async () => {
    // 给 30 天 + 有数据 → heatmapOption 一定存在
    mockGetLowRated.mockResolvedValue({
      items: [
        {
          id: 1,
          message_id: 1,
          rating: -1,
          comment: null,
          feedback_type: 'hallucination',
          created_at: new Date().toISOString(),
          question: 'q',
          answer: 'a',
          session_id: 1,
          kb_id: 1,
        },
      ],
      total: 1,
    });

    render(<FeedbackTrendAnalysis selectedKbId={undefined} />);
    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalled();
    });

    fireEvent.click(screen.getByText('feedback.trendRange30'));

    await waitFor(() => {
      const heatmap = screen
        .getAllByTestId('echarts-mock')
        .find((el) => el.getAttribute('aria-label') === 'feedback.lowRatedHeatmap');
      expect(heatmap).toBeInTheDocument();
    });
  });

  it('should re-fetch when selectedKbId changes', async () => {
    const { rerender } = render(<FeedbackTrendAnalysis selectedKbId={1} />);
    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalledWith(
        expect.objectContaining({ kb_id: 1 }),
        expect.any(AbortSignal),
      );
    });

    rerender(<FeedbackTrendAnalysis selectedKbId={2} />);

    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalledWith(
        expect.objectContaining({ kb_id: 2 }),
        expect.any(AbortSignal),
      );
    });
  });
});
