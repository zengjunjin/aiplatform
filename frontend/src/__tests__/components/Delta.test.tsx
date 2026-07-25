import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import Delta from '../../pages/evaluation/Delta';

// Mock react-i18next: 返回 key 本身，便于断言渲染了哪条文案
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string, opts?: { delta?: string }) => opts?.delta ? `${key}:${opts.delta}` : key }),
}));

describe('Delta', () => {
  it('renders deltaNoPrev when current is null', () => {
    render(<Delta current={null} prev={0.5} />);
    expect(screen.getByText('evaluation.deltaNoPrev')).toBeDefined();
  });

  it('renders deltaNoPrev when prev is null', () => {
    render(<Delta current={0.5} prev={null} />);
    expect(screen.getByText('evaluation.deltaNoPrev')).toBeDefined();
  });

  it('renders deltaNoPrev when current is undefined', () => {
    render(<Delta current={undefined} prev={0.5} />);
    expect(screen.getByText('evaluation.deltaNoPrev')).toBeDefined();
  });

  it('renders deltaNoPrev when prev is undefined', () => {
    render(<Delta current={0.5} prev={undefined} />);
    expect(screen.getByText('evaluation.deltaNoPrev')).toBeDefined();
  });

  it('renders deltaFlat when delta is near zero', () => {
    // current=0.5, prev=0.5 → delta=0, abs(delta) < 0.05
    render(<Delta current={0.5} prev={0.5} />);
    expect(screen.getByText('evaluation.deltaFlat')).toBeDefined();
  });

  it('renders deltaFlat when delta is tiny positive', () => {
    // delta = 0.04 * 100 = 4 → wait, delta = (current - prev) * 100
    // abs(delta) < 0.05 → |current - prev| * 100 < 0.05 → |current - prev| < 0.0005
    render(<Delta current={0.50001} prev={0.5} />);
    expect(screen.getByText('evaluation.deltaFlat')).toBeDefined();
  });

  it('renders deltaUp when current > prev', () => {
    // delta = (0.8 - 0.5) * 100 = 30 → isUp=true
    render(<Delta current={0.8} prev={0.5} />);
    expect(screen.getByText('evaluation.deltaUp:30.0')).toBeDefined();
  });

  it('renders deltaDown when current < prev', () => {
    // delta = (0.3 - 0.5) * 100 = -20 → isUp=false
    render(<Delta current={0.3} prev={0.5} />);
    expect(screen.getByText('evaluation.deltaDown:20.0')).toBeDefined();
  });

  it('renders deltaDown with correct absDelta for negative delta', () => {
    // delta = (0.1 - 0.5) * 100 = -40 → absDelta=40.0
    render(<Delta current={0.1} prev={0.5} />);
    expect(screen.getByText('evaluation.deltaDown:40.0')).toBeDefined();
  });

  it('sets aria-label correctly for up delta', () => {
    render(<Delta current={0.9} prev={0.5} />);
    const container = screen.getByLabelText('evaluation.deltaUp:40.0');
    expect(container).toBeDefined();
  });

  it('sets aria-label correctly for down delta', () => {
    render(<Delta current={0.1} prev={0.5} />);
    const container = screen.getByLabelText('evaluation.deltaDown:40.0');
    expect(container).toBeDefined();
  });
});
