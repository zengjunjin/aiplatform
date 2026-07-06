import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MarkdownRenderer } from '../components/MarkdownRenderer';

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
    render(<MarkdownRenderer content={code} />);
    // code 渲染后应该有 pre 标签
    const pre = document.querySelector('pre');
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
    render(<MarkdownRenderer content={listContent} />);
    const items = document.querySelectorAll('li');
    expect(items.length).toBe(3);
    expect(items[0].textContent).toContain('item1');
    expect(items[1].textContent).toContain('item2');
    expect(items[2].textContent).toContain('item3');
  });

  it('should handle empty content', () => {
    const { container } = render(<MarkdownRenderer content="" />);
    expect(container.querySelector('.markdown-content')).toBeInTheDocument();
  });
});
