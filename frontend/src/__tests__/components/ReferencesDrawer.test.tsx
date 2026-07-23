import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ReferencesDrawer from '../../components/ReferencesDrawer';
import type { Reference } from '../../types';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, params?: any) => {
      if (params && params.num !== undefined) return `${key} ${params.num}`;
      return key;
    },
  }),
}));

const mockRefs: Reference[] = [
  {
    chunk_id: 1,
    doc_id: 1,
    filename: 'doc1.pdf',
    page: 5,
    snippet: 'This is snippet 1',
    score: 0.95,
  },
  {
    chunk_id: 2,
    doc_id: 2,
    filename: 'doc2.txt',
    page: null as unknown as number,
    snippet: 'This is snippet 2 without page',
    score: 0.8,
  },
];

describe('ReferencesDrawer', () => {
  it('should render drawer title', () => {
    render(<ReferencesDrawer open={true} refs={mockRefs} onClose={() => {}} />);
    expect(screen.getByText('chat.references')).toBeInTheDocument();
  });

  it('should render all references with filename and snippet', () => {
    render(<ReferencesDrawer open={true} refs={mockRefs} onClose={() => {}} />);
    expect(screen.getByText('doc1.pdf')).toBeInTheDocument();
    expect(screen.getByText('doc2.txt')).toBeInTheDocument();
    expect(screen.getByText('This is snippet 1')).toBeInTheDocument();
    expect(screen.getByText('This is snippet 2 without page')).toBeInTheDocument();
  });

  it('should render page tag when ref.page is truthy', () => {
    render(<ReferencesDrawer open={true} refs={mockRefs} onClose={() => {}} />);
    expect(screen.getByText('chat.page 5')).toBeInTheDocument();
  });

  it('should not render page tag when ref.page is falsy', () => {
    render(<ReferencesDrawer open={true} refs={mockRefs} onClose={() => {}} />);
    // doc2.txt has page=null, should not have a page tag
    const pageTags = screen.queryAllByText(/chat.page/);
    expect(pageTags).toHaveLength(1); // Only doc1.pdf has page tag
  });

  it('should render relevance score as percentage', () => {
    render(<ReferencesDrawer open={true} refs={mockRefs} onClose={() => {}} />);
    expect(screen.getByText('chat.relevance: 95.0%')).toBeInTheDocument();
    expect(screen.getByText('chat.relevance: 80.0%')).toBeInTheDocument();
  });

  it('should render index tag for each reference', () => {
    render(<ReferencesDrawer open={true} refs={mockRefs} onClose={() => {}} />);
    expect(screen.getByText('[1]')).toBeInTheDocument();
    expect(screen.getByText('[2]')).toBeInTheDocument();
  });

  it('should render nothing in list when refs is empty', () => {
    const { container } = render(<ReferencesDrawer open={true} refs={[]} onClose={() => {}} />);
    // Drawer body should not contain any Card
    const cards = container.querySelectorAll('.ant-card');
    expect(cards).toHaveLength(0);
  });

  it('should call onClose when drawer close is triggered', () => {
    const onClose = vi.fn();
    const { container } = render(<ReferencesDrawer open={true} refs={mockRefs} onClose={onClose} />);
    // Find close button (X) in drawer header
    const closeBtn = container.querySelector('.ant-drawer-close');
    if (closeBtn) {
      fireEvent.click(closeBtn);
      expect(onClose).toHaveBeenCalled();
    }
  });
});
