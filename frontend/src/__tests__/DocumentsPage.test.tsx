import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DocumentsPage from '../pages/DocumentsPage';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, params?: any) => {
      if (params && params.count !== undefined) return `${key} ${params.count}`;
      return key;
    },
  }),
}));

// Mock store with vi.hoisted
const { mockFetchKBs } = vi.hoisted(() => ({
  mockFetchKBs: vi.fn(),
}));

const mockKBs = [
  { id: 1, name: 'KB1', description: '', owner_id: 1, doc_count: 1, chunk_count: 1, collaborators: null, created_at: '', updated_at: '' },
];

vi.mock('../store/kb', () => ({
  useKBStore: (selector: any) => {
    const state = {
      knowledgeBases: mockKBs,
      fetchKBs: mockFetchKBs,
    };
    return selector(state);
  },
}));

// Mock API with vi.hoisted
const { mockList, mockDelete, mockReparse } = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockDelete: vi.fn(),
  mockReparse: vi.fn(),
}));

vi.mock('../api', () => ({
  documentApi: {
    list: mockList,
    delete: mockDelete,
    reparse: mockReparse,
  },
}));

// Mock antd App with trackable message
const { msgSuccess, msgError } = vi.hoisted(() => ({
  msgSuccess: vi.fn(),
  msgError: vi.fn(),
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  return {
    ...(actual as any),
    App: Object.assign((actual as any).App, {
      useApp: () => ({ message: { success: msgSuccess, error: msgError } }),
    }),
  };
});

// Mock errorReporter
vi.mock('../utils/errorReporter', () => ({
  getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));

// Mock format utils
vi.mock('../utils/format', () => ({
  formatFileSize: (s: number) => `${s} B`,
  formatDateTime: (_d: unknown) => '2024-01-01 00:00',
  getStatusColor: (_s: string) => 'default',
  getStatusTextKey: (s: string) => s,
}));

// Mock DocumentPreviewModal to simplify testing
vi.mock('../components/DocumentPreviewModal', () => ({
  __esModule: true,
  default: () => <div data-testid="preview-modal-mock" />,
}));

// Mock echarts-for-react
vi.mock('echarts-for-react/lib/core', () => ({
  __esModule: true,
  default: () => <div data-testid="echarts-mock" />,
}));

vi.mock('echarts/core', () => ({
  __esModule: true,
  default: { use: vi.fn() },
  use: vi.fn(),
}));

vi.mock('echarts/charts', () => ({
  PieChart: {},
  BarChart: {},
}));

vi.mock('echarts/components', () => ({
  GridComponent: {},
  TooltipComponent: {},
  LegendComponent: {},
}));

vi.mock('echarts/renderers', () => ({
  CanvasRenderer: {},
}));

const mockDocs = [
  {
    id: 1,
    kb_id: 1,
    uploader_id: 1,
    filename: 'doc1.pdf',
    file_type: 'pdf',
    file_size: 1024,
    file_hash: '',
    status: 'done',
    chunk_count: 10,
    error_message: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 2,
    kb_id: 1,
    uploader_id: 1,
    filename: 'doc2.txt',
    file_type: 'txt',
    file_size: 512,
    file_hash: '',
    status: 'parsing',
    chunk_count: 0,
    error_message: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
];

describe('DocumentsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockList.mockResolvedValue({ items: [], total: 0 });
  });

  it('should render the page title', () => {
    render(
      <MemoryRouter>
        <DocumentsPage />
      </MemoryRouter>
    );
    expect(screen.getByText('document.management')).toBeInTheDocument();
  });

  it('should render refresh button', () => {
    render(
      <MemoryRouter>
        <DocumentsPage />
      </MemoryRouter>
    );
    expect(screen.getByText('document.refresh')).toBeInTheDocument();
  });

  it('should show empty state when no documents', async () => {
    render(
      <MemoryRouter>
        <DocumentsPage />
      </MemoryRouter>
    );
    expect(await screen.findByText('document.noDocuments')).toBeInTheDocument();
  });

  it('should call fetchKBs on mount', () => {
    render(
      <MemoryRouter>
        <DocumentsPage />
      </MemoryRouter>
    );
    expect(mockFetchKBs).toHaveBeenCalled();
  });

  it('should call documentApi.list on mount', async () => {
    render(
      <MemoryRouter>
        <DocumentsPage />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(mockList).toHaveBeenCalled();
    });
  });

  it('should render document list when documents exist', async () => {
    mockList.mockResolvedValue({ items: mockDocs, total: 2 });

    render(
      <MemoryRouter>
        <DocumentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('doc1.pdf')).toBeInTheDocument();
      expect(screen.getByText('doc2.txt')).toBeInTheDocument();
    });
  });

  it('should show error message when fetch fails', async () => {
    mockList.mockRejectedValue(new Error('Network error'));

    render(
      <MemoryRouter>
        <DocumentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(msgError).toHaveBeenCalledWith('Network error');
    });
  });

  it('should render statistics cards', async () => {
    mockList.mockResolvedValue({ items: mockDocs, total: 2 });

    render(
      <MemoryRouter>
        <DocumentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('document.statsTotalSize')).toBeInTheDocument();
      expect(screen.getByText('document.statsStatus')).toBeInTheDocument();
      expect(screen.getByText('document.statsType')).toBeInTheDocument();
    });
  });

  it('should render KB filter select', async () => {
    mockList.mockResolvedValue({ items: [], total: 0 });

    render(
      <MemoryRouter>
        <DocumentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('document.filterByKB')).toBeInTheDocument();
    });
  });

  it('should render table headers', async () => {
    mockList.mockResolvedValue({ items: mockDocs, total: 2 });

    render(
      <MemoryRouter>
        <DocumentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('document.filename')).toBeInTheDocument();
    });
  });

  it('should render document status tags', async () => {
    mockList.mockResolvedValue({ items: mockDocs, total: 2 });

    render(
      <MemoryRouter>
        <DocumentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('done')).toBeInTheDocument();
      expect(screen.getByText('parsing')).toBeInTheDocument();
    });
  });

  it('should render file size for documents', async () => {
    mockList.mockResolvedValue({ items: [mockDocs[0]], total: 1 });

    render(
      <MemoryRouter>
        <DocumentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('doc1.pdf')).toBeInTheDocument();
    });
    // File size should be rendered using formatFileSize mock
    // Both the stats Statistic (totalSize) and the table cell render "1024 B"
    expect(screen.getAllByText('1024 B').length).toBeGreaterThanOrEqual(1);
  });
});
