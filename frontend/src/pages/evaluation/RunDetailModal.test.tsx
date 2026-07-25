/**
 * RunDetailModal 组件单元测试。
 *
 * 测试目的：覆盖详情弹窗的核心分支——
 *   1. Modal 打开/关闭（onClose 回调、selectedRun 缺失时仅渲染标题）
 *   2. 状态分支：pending / running / completed / failed / 未知状态（STATUS_MAP 回退）
 *   3. error_message 存在/缺失
 *   4. metrics 存在/缺失（MetricCard 渲染）
 *   5. started_at / completed_at 存在/缺失（formatDateTime vs '-'）
 *   6. resultsLoading → Skeleton vs Table
 *   7. hasResultData → 箱线图 Card 渲染/不渲染（renderMiniBar null 分支）
 *
 * 当前分支覆盖率仅 5.4%，本测试旨在覆盖上述所有分支。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import RunDetailModal from './RunDetailModal';
import type { EvaluationRunItem, EvaluationResultItem } from '../../api/evaluation';

// Stable t mock：id 参数附加后缀，便于断言标题渲染了正确的 run id
const { mockT } = vi.hoisted(() => ({
  mockT: (key: string, params?: { id?: number }) =>
    params && params.id !== undefined ? `${key}:${params.id}` : key,
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT }),
}));

// Mock formatDateTime 以获得确定性输出，避免 dayjs 时区漂移
vi.mock('../../utils/format', () => ({
  formatDateTime: (d: string) => `fmt:${d}`,
}));

// Mock echarts-for-react 避免 canvas 渲染；echarts/core 仅需存在（组件不调用 use）
vi.mock('echarts-for-react/lib/core', () => ({
  __esModule: true,
  default: () => <div data-testid="echarts-mock" />,
}));
vi.mock('echarts/core', () => ({
  __esModule: true,
  default: {},
  use: vi.fn(),
}));

const baseRun: EvaluationRunItem = {
  id: 42,
  knowledge_base_id: 1,
  status: 'completed',
  metrics: {
    faithfulness: 0.8,
    answer_relevancy: 0.7,
    context_precision: 0.6,
    context_recall: 0.5,
  },
  total_questions: 10,
  started_at: '2026-07-01T00:00:00Z',
  completed_at: '2026-07-01T01:00:00Z',
  created_at: '2026-07-01T00:00:00Z',
  error_message: null,
};

const baseResults: EvaluationResultItem[] = [
  {
    id: 1,
    question: 'Q1',
    ground_truth: 'GT1',
    generated_answer: 'GA1',
    contexts: [],
    faithfulness: 0.8,
    answer_relevancy: 0.7,
    context_precision: 0.6,
    context_recall: 0.5,
  },
  {
    id: 2,
    question: 'Q2',
    ground_truth: 'GT2',
    generated_answer: 'GA2',
    contexts: [],
    faithfulness: null,
    answer_relevancy: null,
    context_precision: null,
    context_recall: null,
  },
];

function renderModal(overrides: Partial<Parameters<typeof RunDetailModal>[0]> = {}) {
  const props: Parameters<typeof RunDetailModal>[0] = {
    open: true,
    selectedRun: baseRun,
    results: [],
    resultsLoading: false,
    prevRunMetrics: null,
    onClose: () => {},
    ...overrides,
  };
  return render(<RunDetailModal {...props} />);
}

describe('RunDetailModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should render modal title with run id when open and selectedRun provided', () => {
    renderModal();
    expect(screen.getByText('evaluation.detailTitle:42')).toBeDefined();
  });

  it('should not render descriptions body when selectedRun is null', () => {
    renderModal({ selectedRun: null });
    // 标题仍渲染（id 为 undefined → 回退为 key），但 Descriptions 不渲染
    expect(screen.queryByText('evaluation.detail.status')).toBeNull();
    expect(screen.queryByText('evaluation.detail.questionCount')).toBeNull();
  });

  it('should call onClose when close button clicked', () => {
    const onClose = vi.fn();
    renderModal({ onClose });
    const closeBtn = document.body.querySelector('.ant-modal-close') as HTMLElement;
    expect(closeBtn).toBeTruthy();
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalled();
  });

  it('should render completed status tag', () => {
    renderModal();
    expect(screen.getByText('evaluation.status.completed')).toBeDefined();
  });

  it('should render running status tag', () => {
    renderModal({ selectedRun: { ...baseRun, status: 'running' } });
    expect(screen.getByText('evaluation.status.running')).toBeDefined();
  });

  it('should render pending status tag', () => {
    renderModal({ selectedRun: { ...baseRun, status: 'pending' } });
    expect(screen.getByText('evaluation.status.pending')).toBeDefined();
  });

  it('should render failed status tag and error message', () => {
    renderModal({
      selectedRun: { ...baseRun, status: 'failed', error_message: 'boom fail' },
    });
    expect(screen.getByText('evaluation.status.failed')).toBeDefined();
    expect(screen.getByText('boom fail')).toBeDefined();
  });

  it('should render raw status text for unknown status', () => {
    renderModal({ selectedRun: { ...baseRun, status: 'weird' } });
    // STATUS_MAP 未命中 → 直接渲染原始 status 字符串
    expect(screen.getByText('weird')).toBeDefined();
  });

  it('should not render error label when error_message is null', () => {
    renderModal();
    expect(screen.queryByText('evaluation.detail.error')).toBeNull();
  });

  it('should render total_questions value', () => {
    renderModal();
    expect(screen.getByText('10')).toBeDefined();
  });

  it('should render formatted started_at when present', () => {
    renderModal();
    expect(screen.getByText('fmt:2026-07-01T00:00:00Z')).toBeDefined();
  });

  it('should render "-" for started_at when null', () => {
    renderModal({ selectedRun: { ...baseRun, started_at: null } });
    // completed_at 仍有值，证明仅 started_at 走 '-' 分支
    expect(screen.getByText('fmt:2026-07-01T01:00:00Z')).toBeDefined();
    expect(screen.getAllByText('-').length).toBeGreaterThan(0);
  });

  it('should render "-" for completed_at when null', () => {
    renderModal({ selectedRun: { ...baseRun, completed_at: null } });
    expect(screen.getByText('fmt:2026-07-01T00:00:00Z')).toBeDefined();
    expect(screen.getAllByText('-').length).toBeGreaterThan(0);
  });

  it('should render 4 MetricCards (meter role) when metrics present', () => {
    renderModal();
    expect(screen.getAllByRole('meter').length).toBe(4);
  });

  it('should not render MetricCards when metrics null', () => {
    renderModal({ selectedRun: { ...baseRun, metrics: null } });
    expect(screen.queryByRole('meter')).toBeNull();
  });

  it('should render Skeleton when resultsLoading is true', () => {
    renderModal({ resultsLoading: true });
    expect(document.body.querySelector('.ant-skeleton')).toBeTruthy();
    // loading 时不渲染 Table
    expect(document.body.querySelector('.ant-table')).toBeNull();
  });

  it('should render Table when resultsLoading is false', () => {
    renderModal({ results: baseResults });
    expect(document.body.querySelector('.ant-table')).toBeTruthy();
  });

  it('should render boxplot card when hasResultData and not loading', () => {
    renderModal({ results: baseResults });
    expect(screen.getByTestId('echarts-mock')).toBeDefined();
  });

  it('should not render boxplot card when no result data', () => {
    const emptyResults: EvaluationResultItem[] = [
      {
        id: 1,
        question: 'Q1',
        ground_truth: '',
        generated_answer: '',
        contexts: [],
        faithfulness: null,
        answer_relevancy: null,
        context_precision: null,
        context_recall: null,
      },
    ];
    renderModal({ results: emptyResults });
    expect(screen.queryByTestId('echarts-mock')).toBeNull();
  });

  it('should not render boxplot card when resultsLoading', () => {
    renderModal({ results: baseResults, resultsLoading: true });
    // loading 时走 Skeleton 分支，箱线图条件 !resultsLoading 为 false
    expect(screen.queryByTestId('echarts-mock')).toBeNull();
  });

  it('should render question rows in table', () => {
    renderModal({ results: baseResults });
    expect(screen.getByText('Q1')).toBeDefined();
    expect(screen.getByText('Q2')).toBeDefined();
  });

  it('should render perQuestionResults section heading', () => {
    renderModal();
    expect(screen.getByText('evaluation.perQuestionResults')).toBeDefined();
  });
});
