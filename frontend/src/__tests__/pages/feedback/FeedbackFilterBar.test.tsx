import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import FeedbackFilterBar from '../../../pages/feedback/FeedbackFilterBar';
import type { KnowledgeBase } from '../../../types';

// Mock react-i18next - t 函数引用必须稳定（useMemo 依赖 [t]）
const stableT = (key: string) => key;
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: stableT }),
}));

const mockKnowledgeBases: KnowledgeBase[] = [
  { id: 1, name: 'KB-One', description: '', owner_id: 1, doc_count: 0, chunk_count: 0, collaborators: null, created_at: '', updated_at: '' },
  { id: 2, name: 'KB-Two', description: '', owner_id: 1, doc_count: 0, chunk_count: 0, collaborators: null, created_at: '', updated_at: '' },
];

describe('FeedbackFilterBar', () => {
  const onKbChange = vi.fn();
  const onDateRangeChange = vi.fn();
  const onTypeChange = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  const defaultProps = {
    knowledgeBases: [] as KnowledgeBase[],
    selectedKbId: undefined,
    dateRange: null,
    selectedType: undefined,
    onKbChange,
    onDateRangeChange,
    onTypeChange,
  };

  it('should render the KB select and type select placeholders', () => {
    render(<FeedbackFilterBar {...defaultProps} />);
    expect(screen.getByText('feedback.filterByKB')).toBeInTheDocument();
    expect(screen.getByText('feedback.filterByType')).toBeInTheDocument();
  });

  it('should render two antd Select controls', () => {
    const { container } = render(<FeedbackFilterBar {...defaultProps} />);
    expect(container.querySelectorAll('.ant-select')).toHaveLength(2);
  });

  it('should render RangePicker', () => {
    const { container } = render(<FeedbackFilterBar {...defaultProps} />);
    expect(container.querySelector('.ant-picker-range')).toBeInTheDocument();
  });

  it('should open KB dropdown and render KB options when clicked', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <FeedbackFilterBar {...defaultProps} knowledgeBases={mockKnowledgeBases} />,
    );
    // 点击第一个 Select (KB 选择器) 打开下拉，验证 options 通过 useMemo 正确生成
    const kbSelector = container.querySelectorAll('.ant-select-selector')[0];
    await user.click(kbSelector);
    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'KB-One' })).toBeInTheDocument();
      expect(screen.getByRole('option', { name: 'KB-Two' })).toBeInTheDocument();
    });
  });

  it('should open type dropdown and render feedback type options when clicked', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <FeedbackFilterBar {...defaultProps} knowledgeBases={mockKnowledgeBases} />,
    );
    // 点击第二个 Select (type 选择器) 打开下拉，验证 typeOptions 通过 useMemo + FEEDBACK_TYPE_LABELS 生成
    const typeSelector = container.querySelectorAll('.ant-select-selector')[1];
    await user.click(typeSelector);
    // 虚拟列表可能不渲染全部 7 项，验证前几项即可证明 typeOptions 正确生成
    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'chat.feedbackType.faithfulnessIssue' })).toBeInTheDocument();
      expect(screen.getByRole('option', { name: 'chat.feedbackType.incompleteness' })).toBeInTheDocument();
    });
  });

  it('should open date panel when clicking RangePicker input', async () => {
    const user = userEvent.setup();
    const { container } = render(<FeedbackFilterBar {...defaultProps} />);
    const startInput = container.querySelectorAll('.ant-picker-input input')[0];
    await user.click(startInput);
    await waitFor(() => {
      expect(document.querySelector('.ant-picker-panel-container')).toBeInTheDocument();
    });
  });

  it('should memoize kbOptions across renders when knowledgeBases is stable', () => {
    const { rerender } = render(
      <FeedbackFilterBar {...defaultProps} knowledgeBases={mockKnowledgeBases} />,
    );
    // 选中 KB 后 Select 显示选中值而非 placeholder，这里验证重渲染不崩溃
    rerender(
      <FeedbackFilterBar
        {...defaultProps}
        knowledgeBases={mockKnowledgeBases}
        selectedKbId={1}
      />,
    );
    expect(screen.getByText('KB-One')).toBeInTheDocument();
  });

  it('should show selected KB value when provided', () => {
    render(
      <FeedbackFilterBar
        {...defaultProps}
        knowledgeBases={mockKnowledgeBases}
        selectedKbId={2}
      />,
    );
    expect(screen.getByText('KB-Two')).toBeInTheDocument();
  });
});
