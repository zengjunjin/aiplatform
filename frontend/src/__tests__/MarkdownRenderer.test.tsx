import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MarkdownRenderer } from '../components/MarkdownRenderer';

// Mock i18n 模块
vi.mock('../i18n', () => ({
  globalT: (key: string, params?: any) => {
    if (params && params.n !== undefined) return `${key} ${params.n}`;
    if (params && params.lang !== undefined) return `${key} ${params.lang}`;
    return key;
  },
}));

describe('MarkdownRenderer', () => {
  it('should render plain text', () => {
    render(<MarkdownRenderer content="Hello world" />);
    expect(screen.getByText('Hello world')).toBeInTheDocument();
  });

  it('should render bold text', () => {
    render(<MarkdownRenderer content="**bold text**" />);
    const bold = screen.getByText('bold text');
    expect(bold.tagName.toLowerCase()).toBe('strong');
  });

  it('should render code blocks', () => {
    const code = '```javascript\nconsole.log("hello");\n```';
    const { container } = render(<MarkdownRenderer content={code} />);
    // code 渲染后应该有 pre 标签
    const pre = container.querySelector('pre');
    expect(pre).toBeInTheDocument();
  });

  it('should render links', () => {
    render(<MarkdownRenderer content="[link](https://example.com)" />);
    const link = screen.getByText('link');
    expect(link.tagName.toLowerCase()).toBe('a');
    expect(link).toHaveAttribute('href', 'https://example.com');
  });

  it('should render lists', () => {
    const listContent = '- item1\n- item2\n- item3';
    const { container } = render(<MarkdownRenderer content={listContent} />);
    const items = container.querySelectorAll('li');
    expect(items.length).toBe(3);
    expect(items[0].textContent).toContain('item1');
    expect(items[1].textContent).toContain('item2');
    expect(items[2].textContent).toContain('item3');
  });

  it('should handle empty content', () => {
    const { container } = render(<MarkdownRenderer content="" />);
    expect(container.querySelector('.markdown-content')).toBeInTheDocument();
  });

  it('should render reference chips with click handler', () => {
    const onClick = vi.fn();
    render(<MarkdownRenderer content="See [1] for details" onReferenceClick={onClick} />);
    const chip = screen.getByText('[1]');
    fireEvent.click(chip);
    expect(onClick).toHaveBeenCalledWith(1);
  });

  it('should render reference chips without click handler (not clickable)', () => {
    render(<MarkdownRenderer content="See [1] for details" />);
    const chip = screen.getByText('[1]');
    expect(chip).toBeInTheDocument();
    // No role=button when not clickable
    expect(chip).not.toHaveAttribute('role', 'button');
  });

  it('should handle keyboard navigation on reference chips (Enter key)', () => {
    const onClick = vi.fn();
    render(<MarkdownRenderer content="See [2] for details" onReferenceClick={onClick} />);
    const chip = screen.getByText('[2]');
    fireEvent.keyDown(chip, { key: 'Enter' });
    expect(onClick).toHaveBeenCalledWith(2);
  });

  it('should handle keyboard navigation on reference chips (Space key)', () => {
    const onClick = vi.fn();
    render(<MarkdownRenderer content="See [3] for details" onReferenceClick={onClick} />);
    const chip = screen.getByText('[3]');
    fireEvent.keyDown(chip, { key: ' ' });
    expect(onClick).toHaveBeenCalledWith(3);
  });

  it('should render multiple references in a paragraph', () => {
    const onClick = vi.fn();
    render(<MarkdownRenderer content="See [1] and [2] for details" onReferenceClick={onClick} />);
    expect(screen.getByText('[1]')).toBeInTheDocument();
    expect(screen.getByText('[2]')).toBeInTheDocument();
  });

  it('should render references in list items', () => {
    const onClick = vi.fn();
    render(<MarkdownRenderer content="- Item [1]\n- Item [2]" onReferenceClick={onClick} />);
    expect(screen.getByText('[1]')).toBeInTheDocument();
    expect(screen.getByText('[2]')).toBeInTheDocument();
  });

  it('should block unsafe URL protocols (javascript:)', () => {
    render(<MarkdownRenderer content="[click](javascript:alert(1))" />);
    const link = screen.getByText('click');
    // safeUrlTransform should return '' for javascript: protocol
    expect(link).not.toHaveAttribute('href', 'javascript:alert(1)');
  });

  it('should render inline code (not block)', () => {
    const { container } = render(<MarkdownRenderer content="Use `npm install` to install" />);
    const code = container.querySelector('code');
    expect(code).toBeInTheDocument();
    // Inline code should not have pre wrapper
    expect(container.querySelector('pre')).not.toBeInTheDocument();
  });

  it('should render image without alt text using fallback', () => {
    const { container } = render(<MarkdownRenderer content="![](https://example.com/img.png)" />);
    const img = container.querySelector('img');
    expect(img).toBeInTheDocument();
    expect(img?.getAttribute('alt')).toBeTruthy();
  });

  it('should render image with alt text', () => {
    const { container } = render(<MarkdownRenderer content='![alt text](https://example.com/img.png)' />);
    const img = container.querySelector('img');
    expect(img).toBeInTheDocument();
    expect(img?.getAttribute('alt')).toBe('alt text');
  });

  it('should render table with references', () => {
    const onClick = vi.fn();
    const table = '| Col1 | Col2 |\n|------|------|\n| [1]  | data |';
    render(<MarkdownRenderer content={table} onReferenceClick={onClick} />);
    expect(screen.getByText('[1]')).toBeInTheDocument();
  });
});
