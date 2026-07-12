import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DocumentsPage from '../pages/DocumentsPage';

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
      fetchKBs: vi.fn(),
    };
    return selector(state);
  },
}));

// Mock API
vi.mock('../api', () => ({
  documentApi: {
    list: vi.fn().mockResolvedValue({ items: [] }),
    delete: vi.fn(),
    reparse: vi.fn(),
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

describe('DocumentsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

  it('should show empty state when no documents', () => {
    render(
      <MemoryRouter>
        <DocumentsPage />
      </MemoryRouter>
    );
    expect(screen.getByText('document.noDocuments')).toBeInTheDocument();
  });
});