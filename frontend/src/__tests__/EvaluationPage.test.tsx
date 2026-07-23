import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import EvaluationPage from '../pages/EvaluationPage';

// Mock react-i18next - t 函数引用必须稳定以避免 useEffect 死循环
const stableT = (key: string, params?: any) => {
  if (params && params.id !== undefined) return `${key} ${params.id}`;
  return key;
};
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: stableT }),
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

// Mock i18n (避免触发真实初始化)
vi.mock('../i18n', () => ({
  globalT: (key: string) => key,
}));

// Mock API
const mockListRuns = vi.fn();
const mockTriggerEvaluation = vi.fn();
const mockDeleteRun = vi.fn();
const mockGetResults = vi.fn();

vi.mock('../api', () => ({
  evaluationApi: {
    listRuns: (...args: any[]) => mockListRuns(...args),
    triggerEvaluation: (...args: any[]) => mockTriggerEvaluation(...args),
    deleteRun: (...args: any[]) => mockDeleteRun(...args),
    getResults: (...args: any[]) => mockGetResults(...args),
  },
  kbApi: {
    list: vi.fn().mockResolvedValue({ items: [{ id: 1, name: 'TestKB' }] }),
  },
}));

// Mock antd App - message 引用必须稳定以避免 useEffect 死循环
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
  BarChart: {},
  BoxplotChart: {},
}));

vi.mock('echarts/components', () => ({
  GridComponent: {},
  TooltipComponent: {},
  LegendComponent: {},
  TitleComponent: {},
  MarkLineComponent: {},
  DataZoomComponent: {},
}));

vi.mock('echarts/renderers', () => ({
  CanvasRenderer: {},
}));

describe('EvaluationPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListRuns.mockResolvedValue({ items: [] });
  });

  it('should render page title (trend + history)', () => {
    render(
      <MemoryRouter>
        <EvaluationPage />
      </MemoryRouter>
    );
    expect(screen.getByText('evaluation.trend')).toBeInTheDocument();
    expect(screen.getByText('evaluation.history')).toBeInTheDocument();
  });

  it('should render refresh and trigger buttons', () => {
    render(
      <MemoryRouter>
        <EvaluationPage />
      </MemoryRouter>
    );
    expect(screen.getByText('evaluation.refresh')).toBeInTheDocument();
    expect(screen.getByText('evaluation.trigger')).toBeInTheDocument();
  });

  it('should show empty state when no runs', async () => {
    render(
      <MemoryRouter>
        <EvaluationPage />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText('evaluation.noRecords')).toBeInTheDocument();
    });
  });

  it('should render runs table when data is loaded', async () => {
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

    render(
      <MemoryRouter>
        <EvaluationPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      // KB 列应显示 kb name（比 ID 列更具体）
      expect(screen.getByText('TestKB')).toBeInTheDocument();
    });
  });

  it('should open trigger modal when trigger button clicked', async () => {
    render(
      <MemoryRouter>
        <EvaluationPage />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByText('evaluation.trigger'));

    await waitFor(() => {
      expect(screen.getByText('evaluation.triggerModalTitle')).toBeInTheDocument();
    });
    expect(screen.getByText('evaluation.selectKB')).toBeInTheDocument();
    expect(screen.getByText('evaluation.questionCount')).toBeInTheDocument();
  });

  it('should call listRuns on mount', async () => {
    render(
      <MemoryRouter>
        <EvaluationPage />
      </MemoryRouter>
    );
    await waitFor(() => {
      // Task 30: fetchRuns 现在传递 AbortSignal 作为第二个参数以支持取消请求
      // Task 44: 改为服务端分页，默认 page=1, page_size=20
      expect(mockListRuns).toHaveBeenCalledWith({ page: 1, page_size: 20 }, expect.anything());
    });
  });

  it('should call refresh on refresh button click', async () => {
    render(
      <MemoryRouter>
        <EvaluationPage />
      </MemoryRouter>
    );
    const initialCalls = mockListRuns.mock.calls.length;

    fireEvent.click(screen.getByText('evaluation.refresh'));

    await waitFor(() => {
      expect(mockListRuns.mock.calls.length).toBeGreaterThan(initialCalls);
    });
  });

  it('should show noData empty state when no completed runs with metrics', async () => {
    mockListRuns.mockResolvedValue({
      items: [
        {
          id: 1,
          knowledge_base_id: 1,
          status: 'pending',
          metrics: null,
          total_questions: 0,
          started_at: null,
          completed_at: null,
          created_at: '2026-07-01T00:00:00Z',
          error_message: null,
        },
      ],
    });

    render(
      <MemoryRouter>
        <EvaluationPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('evaluation.noData')).toBeInTheDocument();
    });
  });
});
