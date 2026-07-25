/**
 * MetricCard 组件单元测试。
 *
 * 测试目的：覆盖 MetricCard 的核心渲染分支——
 *   1. 数值格式化（value * 100 + 保留 1 位小数 + '%' 后缀）
 *   2. 空值处理（null / undefined → '-' 且无后缀、无颜色）
 *   3. 颜色阈值三分支（>=0.7 success / >=0.4 warning / <0.4 danger）
 *   4. 子组件 Delta 与 ThresholdBar 的渲染委托（含 prevValue 缺失场景）
 *
 * MetricCard 当前覆盖率为 0%，本测试旨在将其提升至接近全覆盖。
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import MetricCard from './MetricCard';

// Mock react-i18next: 返回 key 本身，delta 参数附加后缀，便于断言 Delta 渲染了哪条文案
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { delta?: string }) =>
      opts?.delta ? `${key}:${opts.delta}` : key,
  }),
}));

describe('MetricCard', () => {
  it('should render label as statistic title', () => {
    render(<MetricCard label="Faithfulness" value={0.8} prevValue={0.5} />);
    expect(screen.getByText('Faithfulness')).toBeDefined();
  });

  it('should format value as percentage with one decimal place', () => {
    const { container } = render(<MetricCard label="L" value={0.823} prevValue={null} />);
    // antd Statistic 将数值拆分为整数与小数两个 span，需读取整体 textContent
    // 0.823 * 100 = 82.3
    expect(container.querySelector('.ant-statistic-content-value')?.textContent).toBe('82.3');
  });

  it('should append % suffix when value is present', () => {
    const { container } = render(<MetricCard label="L" value={0.5} prevValue={null} />);
    expect(container.querySelector('.ant-statistic-content-suffix')?.textContent).toBe('%');
  });

  it('should display "-" when value is null', () => {
    render(<MetricCard label="L" value={null} prevValue={null} />);
    expect(screen.getByText('-')).toBeDefined();
  });

  it('should display "-" when value is undefined', () => {
    render(<MetricCard label="L" value={undefined} prevValue={null} />);
    expect(screen.getByText('-')).toBeDefined();
  });

  it('should format value 0 as 0.0', () => {
    const { container } = render(<MetricCard label="L" value={0} prevValue={null} />);
    // antd Statistic 将数值拆分为整数与小数两个 span，需读取整体 textContent
    expect(container.querySelector('.ant-statistic-content-value')?.textContent).toBe('0.0');
  });

  it('should apply success color when value >= 0.7', () => {
    const { container } = render(<MetricCard label="L" value={0.7} prevValue={null} />);
    expect(container.querySelector('.ant-statistic-content')?.getAttribute('style')).toContain(
      'var(--accent-success)',
    );
  });

  it('should apply warning color when 0.4 <= value < 0.7', () => {
    const { container } = render(<MetricCard label="L" value={0.4} prevValue={null} />);
    expect(container.querySelector('.ant-statistic-content')?.getAttribute('style')).toContain(
      'var(--accent-warning)',
    );
  });

  it('should apply danger color when value < 0.4', () => {
    const { container } = render(<MetricCard label="L" value={0.1} prevValue={null} />);
    expect(container.querySelector('.ant-statistic-content')?.getAttribute('style')).toContain(
      'var(--accent-danger)',
    );
  });

  it('should not apply accent color when value is null', () => {
    const { container } = render(<MetricCard label="L" value={null} prevValue={null} />);
    const style = container.querySelector('.ant-statistic-content')?.getAttribute('style') || '';
    expect(style).not.toContain('var(--accent-');
  });

  it('should render ThresholdBar meter when value is present', () => {
    render(<MetricCard label="L" value={0.5} prevValue={null} />);
    expect(screen.getByRole('meter')).toBeDefined();
  });

  it('should not render ThresholdBar meter when value is null', () => {
    render(<MetricCard label="L" value={null} prevValue={null} />);
    expect(screen.queryByRole('meter')).toBeNull();
  });

  it('should render Delta with up trend when current > prev', () => {
    // delta = (0.8 - 0.5) * 100 = 30.0
    render(<MetricCard label="L" value={0.8} prevValue={0.5} />);
    expect(screen.getByText('evaluation.deltaUp:30.0')).toBeDefined();
  });

  it('should render Delta with down trend when current < prev', () => {
    // delta = (0.3 - 0.5) * 100 = -20.0
    render(<MetricCard label="L" value={0.3} prevValue={0.5} />);
    expect(screen.getByText('evaluation.deltaDown:20.0')).toBeDefined();
  });

  it('should render Delta with noPrev when prevValue is null', () => {
    render(<MetricCard label="L" value={0.8} prevValue={null} />);
    expect(screen.getByText('evaluation.deltaNoPrev')).toBeDefined();
  });

  it('should render Delta with noPrev when prevValue is undefined', () => {
    render(<MetricCard label="L" value={0.8} prevValue={undefined} />);
    expect(screen.getByText('evaluation.deltaNoPrev')).toBeDefined();
  });
});
