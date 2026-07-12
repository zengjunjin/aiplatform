import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ChatPage from '../pages/ChatPage';

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
    useParams: () => ({ sessionId: undefined }),
  };
});

// Mock stores
vi.mock('../store/chat', () => ({
  useChatStore: (selector: any) => {
    const state = {
      sessions: [],
      messages: {},
      streaming: false,
      loading: false,
      fetchSessions: vi.fn(),
      fetchMessages: vi.fn(),
      sendMessage: vi.fn(),
      stopStreaming: vi.fn(),
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

// Mock systemApi
vi.mock('../api', () => ({
  systemApi: {
    listModels: vi.fn().mockResolvedValue({ models: [], default_model: '' }),
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
  formatDateTime: (d: any) => '2024-01-01 00:00',
  truncate: (t: string, n: number) => t,
}));

describe('ChatPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should render the chat page layout', () => {
    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>
    );
    expect(screen.getByText('chat.newChat')).toBeInTheDocument();
  });

  it('should render chat input area', () => {
    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>
    );
    // ChatInput renders with a placeholder textarea
    const textarea = document.querySelector('textarea');
    expect(textarea).toBeInTheDocument();
  });

  it('should show empty state when no messages', () => {
    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>
    );
    expect(screen.getByText('chat.startFirstChat')).toBeInTheDocument();
  });
});