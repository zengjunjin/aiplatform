/**
 * ProgressPanel 组件单元测试。
 *
 * 测试目的：覆盖进度面板的核心分支——
 *   1. progressState 为 null → Modal 关闭、内部内容不渲染
 *   2. 未完成态（completed=false）→ active 进度 + progressRunning 文案 + 1s 计时器运行
 *   3. 已完成态（completed=true）→ success 进度 + progressCompleted 文案 + 计时器不运行
 *   4. 计时器推进 current（基于 ESTIMATE_SECONDS_PER_QUESTION=3 的估算公式）
 *   5. current 到达 total → 标记 completed
 *   6. onProgress updater 对 null prev 的守卫分支
 *   7. onClose 按钮回调 + 卸载时清理计时器
 *
 * 注：组件无显式 "失败" 状态（status 仅 success/active），故覆盖 active/completed/null 三态。
 * 当前覆盖率 35.7%，本测试旨在覆盖 useEffect 计时器与各状态分支。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import ProgressPanel, { type ProgressState } from './ProgressPanel';

// Stable t mock：current/total 参数附加后缀，便于断言题号渲染
const { mockT } = vi.hoisted(() => ({
  mockT: (key: string, params?: { current?: number; total?: number }) => {
    if (
      params &&
      params.current !== undefined &&
      params.total !== undefined
    ) {
      return `${key}:${params.current}/${params.total}`;
    }
    return key;
  },
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT }),
}));

describe('ProgressPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('should not render progress content when progressState is null', () => {
    render(
      <ProgressPanel progressState={null} onProgress={() => {}} onClose={() => {}} />,
    );
    // 内部内容 gated by progressState &&，null 时不渲染
    expect(screen.queryByText('evaluation.progressRunning')).toBeNull();
    expect(screen.queryByText('evaluation.progressCompleted')).toBeNull();
    expect(screen.queryByText('common.ok')).toBeNull();
  });

  it('should render modal content when progressState is provided', () => {
    const ps: ProgressState = {
      total: 10,
      current: 3,
      startTime: Date.now(),
      completed: false,
    };
    render(<ProgressPanel progressState={ps} onProgress={() => {}} onClose={() => {}} />);
    expect(screen.getByText('evaluation.progressTitle')).toBeDefined();
    expect(screen.getByText('evaluation.progressQuestion:3/10')).toBeDefined();
  });

  it('should show progressRunning text when not completed', () => {
    const ps: ProgressState = {
      total: 10,
      current: 3,
      startTime: Date.now(),
      completed: false,
    };
    render(<ProgressPanel progressState={ps} onProgress={() => {}} onClose={() => {}} />);
    expect(screen.getByText('evaluation.progressRunning')).toBeDefined();
    expect(screen.queryByText('evaluation.progressCompleted')).toBeNull();
  });

  it('should show progressCompleted text when completed', () => {
    const ps: ProgressState = {
      total: 10,
      current: 10,
      startTime: Date.now(),
      completed: true,
    };
    render(<ProgressPanel progressState={ps} onProgress={() => {}} onClose={() => {}} />);
    expect(screen.getByText('evaluation.progressCompleted')).toBeDefined();
    expect(screen.queryByText('evaluation.progressRunning')).toBeNull();
  });

  it('should display computed percent', () => {
    const ps: ProgressState = {
      total: 10,
      current: 3,
      startTime: Date.now(),
      completed: false,
    };
    render(<ProgressPanel progressState={ps} onProgress={() => {}} onClose={() => {}} />);
    // Math.round((3 / 10) * 100) = 30
    expect(screen.getByText('30%')).toBeDefined();
  });

  it('should render success progress status class when completed', () => {
    const ps: ProgressState = {
      total: 10,
      current: 10,
      startTime: Date.now(),
      completed: true,
    };
    render(<ProgressPanel progressState={ps} onProgress={() => {}} onClose={() => {}} />);
    expect(document.body.querySelector('.ant-progress-status-success')).toBeTruthy();
  });

  it('should call onClose when OK button clicked', () => {
    const onClose = vi.fn();
    const ps: ProgressState = {
      total: 10,
      current: 3,
      startTime: Date.now(),
      completed: false,
    };
    render(<ProgressPanel progressState={ps} onProgress={() => {}} onClose={onClose} />);
    fireEvent.click(screen.getByText('common.ok'));
    expect(onClose).toHaveBeenCalled();
  });

  it('should not run timer when completed', () => {
    const onProgress = vi.fn();
    const ps: ProgressState = {
      total: 10,
      current: 10,
      startTime: Date.now(),
      completed: true,
    };
    render(<ProgressPanel progressState={ps} onProgress={onProgress} onClose={() => {}} />);
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(onProgress).not.toHaveBeenCalled();
  });

  it('should call onProgress with updater after 1s when not completed', () => {
    const onProgress = vi.fn();
    const start = Date.now();
    const ps: ProgressState = {
      total: 10,
      current: 1,
      startTime: start,
      completed: false,
    };
    render(<ProgressPanel progressState={ps} onProgress={onProgress} onClose={() => {}} />);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(onProgress).toHaveBeenCalled();
    const updater = onProgress.mock.calls[0][0];
    expect(typeof updater).toBe('function');
    // elapsed=1s → next = floor(1/3) + 1 = 1
    const result = updater({ total: 10, current: 1, startTime: start, completed: false });
    expect(result.current).toBe(1);
    expect(result.completed).toBe(false);
  });

  it('should advance current based on elapsed time', () => {
    const onProgress = vi.fn();
    const start = Date.now();
    const ps: ProgressState = {
      total: 10,
      current: 1,
      startTime: start,
      completed: false,
    };
    render(<ProgressPanel progressState={ps} onProgress={onProgress} onClose={() => {}} />);
    // 推进 7s → 7 次 interval 触发；elapsed=7s → next = floor(7/3) + 1 = 3
    act(() => {
      vi.advanceTimersByTime(7000);
    });
    expect(onProgress).toHaveBeenCalled();
    const lastUpdater =
      onProgress.mock.calls[onProgress.mock.calls.length - 1][0];
    const result = lastUpdater({ total: 10, current: 1, startTime: start, completed: false });
    expect(result.current).toBe(3);
    expect(result.completed).toBe(false);
  });

  it('should mark completed when next reaches total', () => {
    const onProgress = vi.fn();
    const start = Date.now();
    // total=3, elapsed=6s → next = floor(6/3) + 1 = 3 >= 3 → completed
    const ps: ProgressState = {
      total: 3,
      current: 1,
      startTime: start,
      completed: false,
    };
    render(<ProgressPanel progressState={ps} onProgress={onProgress} onClose={() => {}} />);
    act(() => {
      vi.advanceTimersByTime(6000);
    });
    const updater = onProgress.mock.calls[0][0];
    const result = updater({ total: 3, current: 1, startTime: start, completed: false });
    expect(result.current).toBe(3);
    expect(result.completed).toBe(true);
  });

  it('should clamp current to total when elapsed exceeds estimate', () => {
    const onProgress = vi.fn();
    const start = Date.now();
    const ps: ProgressState = {
      total: 3,
      current: 1,
      startTime: start,
      completed: false,
    };
    render(<ProgressPanel progressState={ps} onProgress={onProgress} onClose={() => {}} />);
    act(() => {
      vi.advanceTimersByTime(30000);
    });
    expect(onProgress).toHaveBeenCalled();
    const lastUpdater =
      onProgress.mock.calls[onProgress.mock.calls.length - 1][0];
    const result = lastUpdater({ total: 3, current: 1, startTime: start, completed: false });
    expect(result.current).toBe(3);
    expect(result.completed).toBe(true);
  });

  it('should return null prev unchanged from updater', () => {
    const onProgress = vi.fn();
    const start = Date.now();
    const ps: ProgressState = {
      total: 10,
      current: 1,
      startTime: start,
      completed: false,
    };
    render(<ProgressPanel progressState={ps} onProgress={onProgress} onClose={() => {}} />);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    const updater = onProgress.mock.calls[0][0];
    // prev 为 null 时守卫分支直接返回 null
    expect(updater(null)).toBeNull();
  });

  it('should clear timer on unmount', () => {
    const onProgress = vi.fn();
    const ps: ProgressState = {
      total: 10,
      current: 1,
      startTime: Date.now(),
      completed: false,
    };
    const { unmount } = render(
      <ProgressPanel progressState={ps} onProgress={onProgress} onClose={() => {}} />,
    );
    unmount();
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(onProgress).not.toHaveBeenCalled();
  });
});
