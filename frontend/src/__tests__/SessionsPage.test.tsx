import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SessionsPage from '../pages/SessionsPage';

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
const { mockFetchSessions, mockCreateSession, mockDeleteSession } = vi.hoisted(() => ({
  mockFetchSessions: vi.fn(),
  mockCreateSession: vi.fn(),
  mockDeleteSession: vi.fn(),
}));

const { mockNavigate } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
}));

const mockSessions = [
  {
    id: 1,
    user_id: 1,
    title: 'Session 1',
    kb_id: 10,
    last_message_at: '',
    message_count: 5,
    created_at: '',
    updated_at: '',
  },
  {
    id: 2,
    user_id: 1,
    title: '',
    kb_id: null,
    last_message_at: '',
    message_count: 0,
    created_at: '',
    updated_at: '',
  },
];

let mockSessionsState = mockSessions;

vi.mock('../store/chat', () => ({
  useChatStore: (selector: any) => {
    const state = {
      sessions: mockSessionsState,
      loading: false,
      fetchSessions: mockFetchSessions,
      createSession: mockCreateSession,
      deleteSession: mockDeleteSession,
    };
    return selector(state);
  },
}));

const mockKBs = [
  { id: 10, name: 'KB1', description: '', owner_id: 1, doc_count: 1, chunk_count: 1, collaborators: null, created_at: '', updated_at: '' },
];

vi.mock('../store/kb', () => ({
  useKBStore: (selector: any) => {
    const state = {
      knowledgeBases: mockKBs,
      fetchKBs: vi.fn(),
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

describe('SessionsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSessionsState = mockSessions;
  });

  it('should render the page title', () => {
    render(
      <MemoryRouter>
        <SessionsPage />
      </MemoryRouter>
    );
    expect(screen.getByText('session.mySessions')).toBeInTheDocument();
  });

  it('should render create session button', () => {
    render(
      <MemoryRouter>
        <SessionsPage />
      </MemoryRouter>
    );
    expect(screen.getByText('session.newSession')).toBeInTheDocument();
  });

  it('should show empty state when no sessions', () => {
    mockSessionsState = [];
    render(
      <MemoryRouter>
        <SessionsPage />
      </MemoryRouter>
    );
    expect(screen.getByText('session.noSessions')).toBeInTheDocument();
  });

  it('should render session list when sessions exist', () => {
    render(
      <MemoryRouter>
        <SessionsPage />
      </MemoryRouter>
    );
    expect(screen.getByText('Session 1')).toBeInTheDocument();
  });

  it('should call fetchSessions on mount', () => {
    render(
      <MemoryRouter>
        <SessionsPage />
      </MemoryRouter>
    );
    expect(mockFetchSessions).toHaveBeenCalled();
  });

  it('should navigate to session when clicked', () => {
    render(
      <MemoryRouter>
        <SessionsPage />
      </MemoryRouter>
    );
    fireEvent.click(screen.getByText('Session 1'));
    expect(mockNavigate).toHaveBeenCalledWith('/chat/1');
  });
});
