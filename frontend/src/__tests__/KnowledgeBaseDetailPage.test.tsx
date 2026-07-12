import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import KnowledgeBaseDetailPage from '../pages/KnowledgeBaseDetailPage';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string, params?: any) => {
    if (params && params.count !== undefined) return `${key} ${params.count}`;
    return key;
  }}),
}));

// Mock react-router-dom
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...(actual as any),
    useParams: () => ({ kbId: '1' }),
  };
});

// Mock store
vi.mock('../store/kb', () => ({
  useKBStore: (selector: any) => {
    const state = {
      knowledgeBases: [{ id: 1, name: 'Test KB', description: 'A test knowledge base', doc_count: 0, chunk_count: 0, updated_at: '2024-01-01', owner_id: 1 }],
      documents: { 1: [] },
      loading: false,
      loadingDocs: { 1: false },
      fetchKBs: vi.fn(),
      fetchDocuments: vi.fn(),
      deleteDocument: vi.fn(),
      reparseDocument: vi.fn(),
      pollProgress: vi.fn().mockReturnValue(vi.fn()),
      updateKB: vi.fn(),
    };
    return selector(state);
  },
}));

// Mock API
vi.mock('../api', () => ({
  kbApi: {
    getCollaborators: vi.fn().mockResolvedValue([]),
    addCollaborator: vi.fn(),
    removeCollaborator: vi.fn(),
  },
  documentApi: {
    upload: vi.fn(),
  },
}));

// Mock antd App
vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  return {
    ...(actual as any),
    App: Object.assign((actual as any).App, {
      useApp: () => ({ message: { success: vi.fn(), error: vi.fn() } }),
    }),
  };
});

// Mock format utils
vi.mock('../utils/format', () => ({
  formatFileSize: (s: number) => `${s} B`,
  formatDateTime: (d: any) => '2024-01-01 00:00',
  getStatusColor: (s: string) => 'default',
  getStatusText: (s: string) => s,
}));

describe('KnowledgeBaseDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should render the knowledge base name', () => {
    render(
      <MemoryRouter>
        <KnowledgeBaseDetailPage />
      </MemoryRouter>
    );
    const elements = screen.getAllByText('Test KB');
    expect(elements.length).toBeGreaterThanOrEqual(1);
  });

  it('should render upload document button', () => {
    render(
      <MemoryRouter>
        <KnowledgeBaseDetailPage />
      </MemoryRouter>
    );
    expect(screen.getByText('kb.uploadDocument')).toBeInTheDocument();
  });

  it('should show empty state when no documents', () => {
    render(
      <MemoryRouter>
        <KnowledgeBaseDetailPage />
      </MemoryRouter>
    );
    expect(screen.getByText('kb.noDocuments')).toBeInTheDocument();
  });
});