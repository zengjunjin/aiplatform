import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SessionsPage from '../pages/SessionsPage';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string, params?: any) => {
    if (params && params.count !== undefined) return `${key} ${params.count}`;
    return key;
  }}),
}));

// Mock stores
vi.mock('../store/chat', () => ({
  useChatStore: (selector: any) => {
    const state = {
      sessions: [],
      loading: false,
      fetchSessions: vi.fn(),
      createSession: vi.fn(),
      deleteSession: vi.fn(),
    };
    return selector(state);
  },
}));

vi.mock('../store/kb', () => ({
  useKBStore: (selector: any) => {
    const state = {
      knowledgeBases: [],
      fetchKBs: vi.fn(),
    };
    return selector(state);
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

describe('SessionsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
    render(
      <MemoryRouter>
        <SessionsPage />
      </MemoryRouter>
    );
    expect(screen.getByText('session.noSessions')).toBeInTheDocument();
  });
});