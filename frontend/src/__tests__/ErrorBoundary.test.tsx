import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ErrorBoundary from '../components/ErrorBoundary';

// Mock i18n 模块: globalT 直接返回 key, 便于断言
vi.mock('../i18n', () => ({
  globalT: (key: string) => key,
}));

// Mock errorReporter: 捕获 reportError 调用以便断言
// vi.hoisted 保证 mock 变量在 vi.mock factory (会被提升到文件顶部) 中可用
const { reportErrorMock } = vi.hoisted(() => ({
  reportErrorMock: vi.fn(),
}));
vi.mock('../utils/errorReporter', () => ({
  reportError: reportErrorMock,
  addBreadcrumb: vi.fn(),
}));

// 抑制 React 测试 error boundary 时输出的 console.error 噪音
const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

// Helper: 制造渲染时抛错的子组件
function Boom({ shouldThrow = true }: { shouldThrow?: boolean }) {
  if (shouldThrow) throw new Error('boom');
  return <div data-testid="child-ok">child ok</div>;
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    reportErrorMock.mockClear();
    consoleErrorSpy.mockClear();
  });

  afterEach(() => {
    consoleErrorSpy.mockReset();
  });

  it('renders children when no error', () => {
    render(
      <ErrorBoundary>
        <div data-testid="child-ok">hello</div>
      </ErrorBoundary>
    );
    expect(screen.getByTestId('child-ok')).toBeInTheDocument();
    expect(screen.queryByText('errorBoundary.title')).not.toBeInTheDocument();
  });

  it('catches render error and shows fallback UI with retry button', () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>
    );
    // 渲染降级 UI
    expect(screen.getByText('errorBoundary.title')).toBeInTheDocument();
    expect(screen.getByText('boom')).toBeInTheDocument();
    expect(screen.getByText('errorBoundary.reload')).toBeInTheDocument();
    expect(screen.getByText('errorBoundary.retry')).toBeInTheDocument();
    // 上报函数被调用一次
    expect(reportErrorMock).toHaveBeenCalledTimes(1);
    expect(reportErrorMock.mock.calls[0][0]).toBeInstanceOf(Error);
  });

  it('retry button resets error state and re-renders children', () => {
    // 使用受控子组件: 第一次渲染抛错, 点击重试后通过 key 重新挂载正常子组件
    let throwFlag = true;
    function ControlledBoom() {
      if (throwFlag) throw new Error('first boom');
      return <div data-testid="child-ok">recovered</div>;
    }

    const { rerender } = render(
      <ErrorBoundary>
        <ControlledBoom />
      </ErrorBoundary>
    );
    // 错误态
    expect(screen.getByText('errorBoundary.title')).toBeInTheDocument();
    expect(screen.queryByTestId('child-ok')).not.toBeInTheDocument();

    // 修复外部状态, 点击重试 -> ErrorBoundary state 重置, 子组件重新渲染
    throwFlag = false;
    fireEvent.click(screen.getByText('errorBoundary.retry'));
    rerender(
      <ErrorBoundary>
        <ControlledBoom />
      </ErrorBoundary>
    );
    expect(screen.getByTestId('child-ok')).toBeInTheDocument();
    expect(screen.queryByText('errorBoundary.title')).not.toBeInTheDocument();
  });

  it('renders custom fallback when provided', () => {
    render(
      <ErrorBoundary fallback={<div data-testid="custom-fallback">custom</div>}>
        <Boom />
      </ErrorBoundary>
    );
    expect(screen.getByTestId('custom-fallback')).toBeInTheDocument();
    // 默认 fallback 不应出现
    expect(screen.queryByText('errorBoundary.title')).not.toBeInTheDocument();
  });

  it('reload button triggers window.location.reload', () => {
    const reloadSpy = vi.fn();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { reload: reloadSpy },
    });

    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>
    );
    fireEvent.click(screen.getByText('errorBoundary.reload'));
    expect(reloadSpy).toHaveBeenCalledTimes(1);
  });

  it('calls onReset callback when retry is clicked', () => {
    const onReset = vi.fn();
    render(
      <ErrorBoundary onReset={onReset}>
        <Boom />
      </ErrorBoundary>
    );
    fireEvent.click(screen.getByText('errorBoundary.retry'));
    expect(onReset).toHaveBeenCalledTimes(1);
  });
});
