import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DashboardPage from '../pages/DashboardPage';

// Mock react-i18next - t 函数引用必须稳定
const stableT = (key: string) => key;
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: stableT }),
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

// Mock i18n
vi.mock('../i18n', () => ({
  globalT: (key: string) => key,
}));

// Mock API
const mockListSessions = vi.fn();
const mockSystemStatus = vi.fn();
const mockKbList = vi.fn();
const mockListRuns = vi.fn();
const mockFeedbackGetStats = vi.fn();
const mockSystemListModels = vi.fn();

vi.mock('../api', () => ({
  kbApi: {
    list: (...args: any[]) => mockKbList(...args),
  },
  systemApi: {
    status: (...args: any[]) => mockSystemStatus(...args),
    listModels: (...args: any[]) => mockSystemListModels(...args),
  },
  evaluationApi: {
    listRuns: (...args: any[]) => mockListRuns(...args),
  },
}));

vi.mock('../api/chat', () => ({
  chatApi: {
    listSessions: (...args: any[]) => mockListSessions(...args),
  },
  feedbackApi: {
    getStats: (...args: any[]) => mockFeedbackGetStats(...args),
  },
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
  LineChart: {},
  PieChart: {},
}));

vi.mock('echarts/components', () => ({
  GridComponent: {},
  TooltipComponent: {},
  LegendComponent: {},
  TitleComponent: {},
  DataZoomComponent: {},
}));

vi.mock('echarts/renderers', () => ({
  CanvasRenderer: {},
}));

const healthyStatus = {
  status: 'ok',
  postgresql: 'up',
  redis: 'up',
  ollama: 'up',
  qdrant: 'up',
  celery: 'up',
};

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // 默认成功响应
    mockListSessions.mockResolvedValue({ items: [], total: 0 });
    mockSystemStatus.mockResolvedValue(healthyStatus);
    mockKbList.mockResolvedValue({ items: [] });
    mockListRuns.mockResolvedValue({ items: [] });
    mockFeedbackGetStats.mockResolvedValue({
      total_feedback: 0,
      positive_rate: 0,
      negative_rate: 0,
      by_type: {},
    });
    mockSystemListModels.mockResolvedValue({ models: [], default_model: 'ollama' });
  });

  it('should render KPI section with today chats and health status', async () => {
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('dashboard.todayChats')).toBeInTheDocument();
    });
    expect(screen.getByText('dashboard.healthStatus')).toBeInTheDocument();
  });

  it('should render 4 chart cards', async () => {
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('dashboard.docTrend')).toBeInTheDocument();
    });
    expect(screen.getByText('dashboard.evalTrend')).toBeInTheDocument();
    expect(screen.getByText('dashboard.feedbackRatio')).toBeInTheDocument();
    expect(screen.getByText('dashboard.modelHealth')).toBeInTheDocument();
  });

  it('should call all 6 APIs in parallel on mount', async () => {
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockListSessions).toHaveBeenCalled();
      expect(mockSystemStatus).toHaveBeenCalled();
      expect(mockKbList).toHaveBeenCalled();
      expect(mockListRuns).toHaveBeenCalled();
      expect(mockFeedbackGetStats).toHaveBeenCalled();
      expect(mockSystemListModels).toHaveBeenCalled();
    });
  });

  it('should render echarts when data is available', async () => {
    mockKbList.mockResolvedValue({
      items: [
        {
          id: 1,
          name: 'TestKB',
          doc_count: 10,
          chunk_count: 100,
          created_at: new Date().toISOString(),
        },
      ],
    });
    mockListRuns.mockResolvedValue({
      items: [
        {
          id: 1,
          knowledge_base_id: 1,
          status: 'completed',
          metrics: {
            faithfulness: 0.8,
            answer_relevancy: 0.7,
            context_precision: 0.9,
            context_recall: 0.6,
          },
          total_questions: 10,
          started_at: '2026-07-01T00:00:00Z',
          completed_at: '2026-07-01T01:00:00Z',
          created_at: '2026-07-01T00:00:00Z',
          error_message: null,
        },
      ],
    });
    mockFeedbackGetStats.mockResolvedValue({
      total_feedback: 10,
      positive_rate: 0.7,
      negative_rate: 0.3,
      by_type: {},
    });

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      // 至少 3 个 echarts-mock（docTrend、evalTrend、feedbackRatio）
      const charts = screen.getAllByTestId('echarts-mock');
      expect(charts.length).toBeGreaterThanOrEqual(3);
    });
  });

  it('should not block rendering when one API fails (Promise.allSettled)', async () => {
    // 单个 API 失败
    mockSystemStatus.mockRejectedValue(new Error('Network error'));
    // 其他 API 成功
    mockKbList.mockResolvedValue({
      items: [
        {
          id: 1,
          name: 'TestKB',
          doc_count: 5,
          chunk_count: 50,
          created_at: new Date().toISOString(),
        },
      ],
    });

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    );

    // 系统健康 API 失败，但其他图表仍渲染
    await waitFor(() => {
      expect(screen.getByText('dashboard.docTrend')).toBeInTheDocument();
    });
    expect(screen.getByText('dashboard.evalTrend')).toBeInTheDocument();
    expect(screen.getByText('dashboard.feedbackRatio')).toBeInTheDocument();
    expect(screen.getByText('dashboard.modelHealth')).toBeInTheDocument();
  });

  it('should display healthy tag when system is healthy', async () => {
    mockSystemStatus.mockResolvedValue(healthyStatus);

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      // 健康状态徽章
      expect(screen.getByText('system.status.healthy')).toBeInTheDocument();
    });
  });

  it('should display unhealthy tag when system is unhealthy', async () => {
    mockSystemStatus.mockResolvedValue({
      ...healthyStatus,
      redis: 'down',
    });

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('system.status.unhealthy')).toBeInTheDocument();
    });
  });

  it('should show empty state when no data available', async () => {
    // 所有数据为空
    mockKbList.mockResolvedValue({ items: [] });
    mockListRuns.mockResolvedValue({ items: [] });
    mockFeedbackGetStats.mockResolvedValue({
      total_feedback: 0,
      positive_rate: 0,
      negative_rate: 0,
      by_type: {},
    });
    mockSystemListModels.mockResolvedValue({ models: [], default_model: 'ollama' });

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      // 多个空状态
      const emptyTexts = screen.getAllByText('common.noData');
      expect(emptyTexts.length).toBeGreaterThanOrEqual(3);
    });
  });

  it('should render available models when models data loaded', async () => {
    mockSystemListModels.mockResolvedValue({
      models: [
        {
          name: 'ollama:llama3',
          display_name: 'Llama 3 (本地)',
          source: 'local',
          status: 'healthy',
        },
        {
          name: 'ollama:qwen2',
          display_name: 'Qwen 2 (本地)',
          source: 'local',
          status: 'healthy',
        },
      ],
      default_model: 'ollama',
    });

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('Llama 3 (本地)')).toBeInTheDocument();
      expect(screen.getByText('Qwen 2 (本地)')).toBeInTheDocument();
    });
  });
});
