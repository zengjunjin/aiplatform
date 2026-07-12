import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import KnowledgeBasesPage from '../pages/KnowledgeBasesPage';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string, params?: any) => {
    if (params && params.count !== undefined) return `${key} ${params.count}`;
    return key;
  }}),
}));

// Mock store
vi.mock('../store/kb', () => ({
  useKBStore: (selector: any) => {
    const state = {
      knowledgeBases: [],
      loading: false,
      fetchKBs: vi.fn(),
      createKB: vi.fn(),
      deleteKB: vi.fn(),
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

describe('KnowledgeBasesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
});