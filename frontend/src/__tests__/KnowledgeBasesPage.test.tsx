import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import KnowledgeBasesPage from '../pages/KnowledgeBasesPage';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, params?: any) => {
      if (params && params.count !== undefined) return `${key} ${params.count}`;
      return key;
    },
  }),
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

// Mock i18n 模块
vi.mock('../i18n', () => ({
  globalT: (key: string, params?: any) => {
    if (params && params.count !== undefined) return `${key} ${params.count}`;
    return key;
  },
}));

// Mock stores with vi.hoisted
const { mockFetchKBs, mockCreateKB, mockDeleteKB } = vi.hoisted(() => ({
  mockFetchKBs: vi.fn(),
  mockCreateKB: vi.fn(),
  mockDeleteKB: vi.fn(),
}));

const { mockNavigate } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
}));

const mockKBs = [
  {
    id: 1,
    name: 'Test KB',
    description: 'Test description',
    owner_id: 1,
    doc_count: 5,
    chunk_count: 100,
    collaborators: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 2,
    name: 'KB No Desc',
    description: '',
    owner_id: 1,
    doc_count: 0,
    chunk_count: 0,
    collaborators: null,
    created_at: '',
    updated_at: '',
  },
];

let mockKBsState: any[] = [];

vi.mock('../store/kb', () => ({
  useKBStore: (selector: any) => {
    const state = {
      knowledgeBases: mockKBsState,
      loading: false,
      fetchKBs: mockFetchKBs,
      createKB: mockCreateKB,
      deleteKB: mockDeleteKB,
    };
    return selector(state);
  },
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...(actual as any),
    useNavigate: () => mockNavigate,
  };
});

// Mock antd App
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
  isFormValidationError: (e: unknown) =>
    typeof e === 'object' && e !== null && 'errorFields' in e,
}));

// Mock format utils
vi.mock('../utils/format', () => ({
  formatRelativeTime: () => 'just now',
}));

// Mock echarts-for-react 避免 canvas 渲染
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
  LineChart: {},
}));

vi.mock('echarts/components', () => ({
  GridComponent: {},
  TooltipComponent: {},
}));

vi.mock('echarts/renderers', () => ({
  CanvasRenderer: {},
}));

describe('KnowledgeBasesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockKBsState = [];
  });

  it('should render the page title', () => {
    render(
      <MemoryRouter>
        <KnowledgeBasesPage />
      </MemoryRouter>
    );
    expect(screen.getByText('kb.myKnowledgeBases')).toBeInTheDocument();
  });

  it('should render create knowledge base button', () => {
    render(
      <MemoryRouter>
        <KnowledgeBasesPage />
      </MemoryRouter>
    );
    expect(screen.getByText('kb.newKnowledgeBase')).toBeInTheDocument();
  });

  it('should show empty state when no knowledge bases', () => {
    render(
      <MemoryRouter>
        <KnowledgeBasesPage />
      </MemoryRouter>
    );
    expect(screen.getByText('kb.noKBs')).toBeInTheDocument();
  });

  it('should call fetchKBs on mount', () => {
    render(
      <MemoryRouter>
        <KnowledgeBasesPage />
      </MemoryRouter>
    );
    expect(mockFetchKBs).toHaveBeenCalled();
  });

  it('should render KB cards when knowledge bases exist', () => {
    mockKBsState = mockKBs;
    render(
      <MemoryRouter>
        <KnowledgeBasesPage />
      </MemoryRouter>
    );
    expect(screen.getByText('Test KB')).toBeInTheDocument();
    expect(screen.getByText('KB No Desc')).toBeInTheDocument();
  });

  it('should render KB description when present', () => {
    mockKBsState = mockKBs;
    render(
      <MemoryRouter>
        <KnowledgeBasesPage />
      </MemoryRouter>
    );
    expect(screen.getByText('Test description')).toBeInTheDocument();
  });

  it('should render no description text when description is empty', () => {
    mockKBsState = mockKBs;
    render(
      <MemoryRouter>
        <KnowledgeBasesPage />
      </MemoryRouter>
    );
    expect(screen.getByText('kb.noDescription')).toBeInTheDocument();
  });

  it('should render statistics cards', () => {
    mockKBsState = mockKBs;
    render(
      <MemoryRouter>
        <KnowledgeBasesPage />
      </MemoryRouter>
    );
    expect(screen.getByText('kb.totalKBs')).toBeInTheDocument();
    expect(screen.getByText('kb.totalDocs')).toBeInTheDocument();
    expect(screen.getByText('kb.totalChunks')).toBeInTheDocument();
    expect(screen.getByText('kb.weeklyNewKBs')).toBeInTheDocument();
  });

  it('should navigate to KB detail when card clicked', () => {
    mockKBsState = [mockKBs[0]];
    render(
      <MemoryRouter>
        <KnowledgeBasesPage />
      </MemoryRouter>
    );
    fireEvent.click(screen.getByText('Test KB'));
    expect(mockNavigate).toHaveBeenCalledWith('/knowledge-bases/1');
  });

  it('should open create modal when new KB button clicked', () => {
    render(
      <MemoryRouter>
        <KnowledgeBasesPage />
      </MemoryRouter>
    );
    fireEvent.click(screen.getByText('kb.newKnowledgeBase'));
    expect(screen.getByText('kb.kbName')).toBeInTheDocument();
    expect(screen.getByText('kb.description')).toBeInTheDocument();
  });

  it('should show createFirstKB button in empty state', () => {
    render(
      <MemoryRouter>
        <KnowledgeBasesPage />
      </MemoryRouter>
    );
    expect(screen.getByText('kb.createFirstKB')).toBeInTheDocument();
  });
});
