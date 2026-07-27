import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import dayjs from 'dayjs';
import LowRatedTable from '../../../pages/feedback/LowRatedTable';

// Mock react-i18next - t 函数引用必须稳定
const stableT = (key: string, params?: any) => {
  if (params && params.count !== undefined) return `${key} ${params.count}`;
  return key;
};
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: stableT }),
}));

// Mock feedbackApi
const mockGetLowRated = vi.fn();
vi.mock('../../../api/chat', () => ({
  feedbackApi: {
    getLowRated: (...args: any[]) => mockGetLowRated(...args),
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

const mockFeedbacks = [
  {
    id: 42,
    message_id: 100,
    rating: -1,
    comment: 'bad answer',
    feedback_type: 'hallucination',
    created_at: '2026-07-01T10:00:00Z',
    question: '什么是 RAG？',
    answer: 'RAG 是错误的回答',
    session_id: 1,
    kb_id: 5,
  },
  {
    id: 43,
    message_id: 101,
    rating: -1,
    comment: null,
    feedback_type: null,
    created_at: '2026-07-02T10:00:00Z',
    question: '',
    answer: '另一个回答',
    session_id: 1,
    kb_id: null,
  },
];

describe('LowRatedTable', () => {
  const onFeedbacksChange = vi.fn();
  const onPageChange = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockGetLowRated.mockResolvedValue({ items: [], total: 0 });
  });

  const defaultProps = {
    selectedKbId: undefined,
    dateRange: null as [dayjs.Dayjs, dayjs.Dayjs] | null,
    selectedType: undefined,
    page: 1,
    pageSize: 20,
    onPageChange,
    onFeedbacksChange,
  };

  it('should render the card title', () => {
    render(<LowRatedTable {...defaultProps} />);
    expect(screen.getByText('feedback.lowRatedAnswers')).toBeInTheDocument();
  });

  it('should call getLowRated on mount', async () => {
    render(<LowRatedTable {...defaultProps} />);
    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalled();
    });
  });

  it('should pass filters to getLowRated', async () => {
    const dateRange: [dayjs.Dayjs, dayjs.Dayjs] = [
      dayjs('2026-07-01T00:00:00Z'),
      dayjs('2026-07-08T00:00:00Z'),
    ];
    render(
      <LowRatedTable
        {...defaultProps}
        selectedKbId={3}
        dateRange={dateRange}
        selectedType="hallucination"
        page={2}
        pageSize={50}
      />,
    );

    await waitFor(() => {
      const params = mockGetLowRated.mock.calls[0][0];
      expect(params.kb_id).toBe(3);
      expect(params.start_date).toBe(dateRange[0].toISOString());
      expect(params.end_date).toBe(dateRange[1].toISOString());
      expect(params.feedback_type).toBe('hallucination');
      expect(params.page).toBe(2);
      expect(params.page_size).toBe(50);
    });
  });

  it('should call onFeedbacksChange with fetched items', async () => {
    mockGetLowRated.mockResolvedValue({ items: mockFeedbacks, total: 2 });

    render(<LowRatedTable {...defaultProps} />);

    await waitFor(() => {
      expect(onFeedbacksChange).toHaveBeenCalledWith(mockFeedbacks);
    });
  });

  it('should render feedback rows when data is loaded', async () => {
    mockGetLowRated.mockResolvedValue({ items: mockFeedbacks, total: 2 });

    render(<LowRatedTable {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByText('bad answer')).toBeInTheDocument();
      expect(screen.getByText('什么是 RAG？')).toBeInTheDocument();
    });
  });

  it('should render empty state when no feedbacks', async () => {
    mockGetLowRated.mockResolvedValue({ items: [], total: 0 });

    render(<LowRatedTable {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByText('feedback.noFeedbackData')).toBeInTheDocument();
    });
  });

  it('should show error message when fetch fails', async () => {
    mockGetLowRated.mockRejectedValue(new Error('fetch failed'));

    render(<LowRatedTable {...defaultProps} />);

    await waitFor(() => {
      expect(stableMessage.error).toHaveBeenCalledWith('fetch failed');
    });
  });

  it('should fall back to t(feedback.loadFeedbacksFailed) when error has no message', async () => {
    // getErrorMessage('') = String('') = '' (falsy) → 回退到 t(feedback.loadFeedbacksFailed)
    mockGetLowRated.mockRejectedValue('');

    render(<LowRatedTable {...defaultProps} />);

    await waitFor(() => {
      expect(stableMessage.error).toHaveBeenCalledWith('feedback.loadFeedbacksFailed');
    });
  });

  it('should render ID column header', async () => {
    mockGetLowRated.mockResolvedValue({ items: mockFeedbacks, total: 2 });

    render(<LowRatedTable {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByText('ID')).toBeInTheDocument();
    });
  });

  it('should render feedback_type tag with translated label', async () => {
    mockGetLowRated.mockResolvedValue({ items: [mockFeedbacks[0]], total: 1 });

    render(<LowRatedTable {...defaultProps} />);

    await waitFor(() => {
      // hallucination → t('chat.feedbackType.hallucination')
      expect(screen.getByText('chat.feedbackType.hallucination')).toBeInTheDocument();
    });
  });

  it('should render N/A tag when feedback_type is null', async () => {
    mockGetLowRated.mockResolvedValue({ items: [mockFeedbacks[1]], total: 1 });

    render(<LowRatedTable {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByText('feedback.na')).toBeInTheDocument();
    });
  });

  it('should render "-" for null comment', async () => {
    mockGetLowRated.mockResolvedValue({ items: [mockFeedbacks[1]], total: 1 });

    render(<LowRatedTable {...defaultProps} />);

    await waitFor(() => {
      // comment 列对 null 返回 '-'
      const dashes = screen.getAllByText('-');
      expect(dashes.length).toBeGreaterThan(0);
    });
  });

  it('should render "-" for null kb_id', async () => {
    mockGetLowRated.mockResolvedValue({ items: [mockFeedbacks[1]], total: 1 });

    render(<LowRatedTable {...defaultProps} />);

    await waitFor(() => {
      // kb_id 列对 null 返回 '-'，comment 列对 null 也返回 '-'，可能有多个
      const dashes = screen.getAllByText('-');
      expect(dashes.length).toBeGreaterThanOrEqual(1);
    });
  });

  it('should render "#5" for kb_id=5', async () => {
    mockGetLowRated.mockResolvedValue({ items: [mockFeedbacks[0]], total: 1 });

    render(<LowRatedTable {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByText('#5')).toBeInTheDocument();
    });
  });

  it('should render formatted time', async () => {
    // 使用不带 Z 的本地时间字符串，避免时区转换差异
    const localTime = '2026-07-01T10:00:00';
    mockGetLowRated.mockResolvedValue({
      items: [{ ...mockFeedbacks[0], created_at: localTime }],
      total: 1,
    });

    render(<LowRatedTable {...defaultProps} />);

    await waitFor(() => {
      // dayjs('2026-07-01T10:00:00').format('YYYY-MM-DD HH:mm') = '2026-07-01 10:00'
      expect(screen.getByText('2026-07-01 10:00')).toBeInTheDocument();
    });
  });

  it('should render totalItems count in pagination', async () => {
    mockGetLowRated.mockResolvedValue({ items: mockFeedbacks, total: 2 });

    render(<LowRatedTable {...defaultProps} />);

    await waitFor(() => {
      // showTotal → t('feedback.totalItems', { count: 2 }) → 'feedback.totalItems 2'
      expect(screen.getByText('feedback.totalItems 2')).toBeInTheDocument();
    });
  });

  it('should call onPageChange when clicking next page', async () => {
    mockGetLowRated.mockResolvedValue({ items: mockFeedbacks, total: 50 });

    const { container } = render(<LowRatedTable {...defaultProps} page={1} pageSize={20} />);

    await waitFor(() => {
      expect(screen.getByText('bad answer')).toBeInTheDocument();
    });

    // 点击 "下一页" 按钮
    const nextBtn = container.querySelector('.ant-pagination-next')!;
    expect(nextBtn).toBeInTheDocument();
    fireEvent.click(nextBtn);

    expect(onPageChange).toHaveBeenCalledWith(2);
  });

  it('should expand row to show question/answer/comment', async () => {
    mockGetLowRated.mockResolvedValue({ items: [mockFeedbacks[0]], total: 1 });

    const { container } = render(<LowRatedTable {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByText('bad answer')).toBeInTheDocument();
    });

    // 点击展开行
    const expandBtn = container.querySelector('.ant-table-row-expand-icon')!;
    fireEvent.click(expandBtn);

    await waitFor(() => {
      // 展开后应渲染系统回答卡片标题
      expect(screen.getAllByText('feedback.question').length).toBeGreaterThan(0);
      expect(screen.getByText('feedback.systemAnswer')).toBeInTheDocument();
      expect(screen.getByText('feedback.userFeedback')).toBeInTheDocument();
    });
  });

  it('should not render userFeedback card when comment is null (expanded row)', async () => {
    mockGetLowRated.mockResolvedValue({ items: [mockFeedbacks[1]], total: 1 });

    const { container } = render(<LowRatedTable {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByText('另一个回答')).toBeInTheDocument();
    });

    fireEvent.click(container.querySelector('.ant-table-row-expand-icon')!);

    await waitFor(() => {
      expect(screen.getByText('feedback.noQuestion')).toBeInTheDocument();
      // comment 为 null，不应渲染 userFeedback 卡片标题
      expect(screen.queryByText('feedback.userFeedback')).not.toBeInTheDocument();
    });
  });

  it('should re-fetch when page changes', async () => {
    const { rerender } = render(<LowRatedTable {...defaultProps} page={1} />);

    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalledTimes(1);
    });

    rerender(<LowRatedTable {...defaultProps} page={2} />);

    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalledTimes(2);
      expect(mockGetLowRated.mock.calls[1][0].page).toBe(2);
    });
  });

  it('should re-fetch when selectedKbId changes', async () => {
    const { rerender } = render(<LowRatedTable {...defaultProps} selectedKbId={1} />);

    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalledWith(expect.objectContaining({ kb_id: 1 }));
    });

    rerender(<LowRatedTable {...defaultProps} selectedKbId={2} />);

    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalledWith(expect.objectContaining({ kb_id: 2 }));
    });
  });

  it('should re-fetch when selectedType changes', async () => {
    const { rerender } = render(<LowRatedTable {...defaultProps} selectedType="hallucination" />);

    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalledWith(expect.objectContaining({ feedback_type: 'hallucination' }));
    });

    rerender(<LowRatedTable {...defaultProps} selectedType="incomplete" />);

    await waitFor(() => {
      expect(mockGetLowRated).toHaveBeenCalledWith(expect.objectContaining({ feedback_type: 'incomplete' }));
    });
  });
});
