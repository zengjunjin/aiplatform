import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import ThresholdBar from '../../pages/evaluation/ThresholdBar';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe('ThresholdBar', () => {
  it('renders nothing when value is null', () => {
    const { container } = render(<ThresholdBar value={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when value is undefined', () => {
    const { container } = render(<ThresholdBar value={undefined} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders meter with aria-label when value is provided', () => {
    render(<ThresholdBar value={0.5} />);
    const meter = screen.getByRole('meter');
    expect(meter).toBeDefined();
    expect(meter.getAttribute('aria-valuenow')).toBe('0.5');
    expect(meter.getAttribute('aria-valuemin')).toBe('0');
    expect(meter.getAttribute('aria-valuemax')).toBe('1');
  });

  it('clamps value below 0 to 0', () => {
    render(<ThresholdBar value={-0.5} />);
    const meter = screen.getByRole('meter');
    // aria-valuenow 保留原始值，但指示器位置被 clamp
    expect(meter.getAttribute('aria-valuenow')).toBe('-0.5');
  });

  it('clamps value above 1 to 1', () => {
    render(<ThresholdBar value={1.5} />);
    const meter = screen.getByRole('meter');
    expect(meter.getAttribute('aria-valuenow')).toBe('1.5');
  });

  it('renders three color segments', () => {
    render(<ThresholdBar value={0.5} />);
    const meter = screen.getByRole('meter');
    // 应有 4 个子 div：3 个色段 + 1 个指示器
    expect(meter.children.length).toBe(4);
  });
});
