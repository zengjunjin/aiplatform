import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import KBBreadcrumbHeader from '../../components/KBBreadcrumbHeader';
import type { KnowledgeBase } from '../../types';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mockKB: KnowledgeBase = {
  id: 1,
  name: 'Test KB',
  description: 'Test description',
  owner_id: 1,
  doc_count: 5,
  chunk_count: 100,
  collaborators: null,
  created_at: '',
  updated_at: '',
};

function renderWithRouter(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe('KBBreadcrumbHeader', () => {
  it('should render kb name in breadcrumb when kb is provided', () => {
    renderWithRouter(
      <KBBreadcrumbHeader
        kb={mockKB}
        loading={false}
        onEditClick={() => {}}
        onCollabClick={() => {}}
        onRefreshClick={() => {}}
        onUploadClick={() => {}}
      />
    );
    expect(screen.getAllByText('Test KB')).toHaveLength(2); // breadcrumb + title
  });

  it('should render loading text when kb is undefined', () => {
    renderWithRouter(
      <KBBreadcrumbHeader
        kb={undefined}
        loading={true}
        onEditClick={() => {}}
        onCollabClick={() => {}}
        onRefreshClick={() => {}}
        onUploadClick={() => {}}
      />
    );
    expect(screen.getAllByText('common.loading')).toHaveLength(2); // breadcrumb + title
  });

  it('should render kb description when provided', () => {
    renderWithRouter(
      <KBBreadcrumbHeader
        kb={mockKB}
        loading={false}
        onEditClick={() => {}}
        onCollabClick={() => {}}
        onRefreshClick={() => {}}
        onUploadClick={() => {}}
      />
    );
    expect(screen.getByText('Test description')).toBeInTheDocument();
  });

  it('should render empty description when kb has no description', () => {
    const kbNoDesc = { ...mockKB, description: '' };
    const { container } = renderWithRouter(
      <KBBreadcrumbHeader
        kb={kbNoDesc}
        loading={false}
        onEditClick={() => {}}
        onCollabClick={() => {}}
        onRefreshClick={() => {}}
        onUploadClick={() => {}}
      />
    );
    // Description Text component should exist but be empty
    const secondaryTexts = container.querySelectorAll('.ant-typography-secondary');
    expect(secondaryTexts.length).toBeGreaterThan(0);
  });

  it('should render all action buttons', () => {
    renderWithRouter(
      <KBBreadcrumbHeader
        kb={mockKB}
        loading={false}
        onEditClick={() => {}}
        onCollabClick={() => {}}
        onRefreshClick={() => {}}
        onUploadClick={() => {}}
      />
    );
    expect(screen.getByText('kb.edit')).toBeInTheDocument();
    expect(screen.getByText('kb.collaborators')).toBeInTheDocument();
    expect(screen.getByText('kb.refresh')).toBeInTheDocument();
    expect(screen.getByText('kb.uploadDocument')).toBeInTheDocument();
  });

  it('should call onEditClick when edit button clicked', () => {
    const onEditClick = vi.fn();
    renderWithRouter(
      <KBBreadcrumbHeader
        kb={mockKB}
        loading={false}
        onEditClick={onEditClick}
        onCollabClick={() => {}}
        onRefreshClick={() => {}}
        onUploadClick={() => {}}
      />
    );
    fireEvent.click(screen.getByText('kb.edit'));
    expect(onEditClick).toHaveBeenCalled();
  });

  it('should call onCollabClick when collaborators button clicked', () => {
    const onCollabClick = vi.fn();
    renderWithRouter(
      <KBBreadcrumbHeader
        kb={mockKB}
        loading={false}
        onEditClick={() => {}}
        onCollabClick={onCollabClick}
        onRefreshClick={() => {}}
        onUploadClick={() => {}}
      />
    );
    fireEvent.click(screen.getByText('kb.collaborators'));
    expect(onCollabClick).toHaveBeenCalled();
  });

  it('should call onRefreshClick when refresh button clicked', () => {
    const onRefreshClick = vi.fn();
    renderWithRouter(
      <KBBreadcrumbHeader
        kb={mockKB}
        loading={false}
        onEditClick={() => {}}
        onCollabClick={() => {}}
        onRefreshClick={onRefreshClick}
        onUploadClick={() => {}}
      />
    );
    fireEvent.click(screen.getByText('kb.refresh'));
    expect(onRefreshClick).toHaveBeenCalled();
  });

  it('should call onUploadClick when upload button clicked', () => {
    const onUploadClick = vi.fn();
    renderWithRouter(
      <KBBreadcrumbHeader
        kb={mockKB}
        loading={false}
        onEditClick={() => {}}
        onCollabClick={() => {}}
        onRefreshClick={() => {}}
        onUploadClick={onUploadClick}
      />
    );
    fireEvent.click(screen.getByText('kb.uploadDocument'));
    expect(onUploadClick).toHaveBeenCalled();
  });

  it('should render kb link in breadcrumb', () => {
    renderWithRouter(
      <KBBreadcrumbHeader
        kb={mockKB}
        loading={false}
        onEditClick={() => {}}
        onCollabClick={() => {}}
        onRefreshClick={() => {}}
        onUploadClick={() => {}}
      />
    );
    const link = screen.getByText('kb.kb');
    expect(link.closest('a')).toHaveAttribute('href', '/knowledge-bases');
  });
});
