import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import UsersPage from '../pages/UsersPage';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string, params?: any) => {
    if (params && params.count !== undefined) return `${key} ${params.count}`;
    return key;
  }}),
}));

// Mock store
vi.mock('../store/auth', () => ({
  useAuthStore: (selector: any) => {
    const state = { user: null };
    return selector(state);
  },
}));

// Mock API
vi.mock('../api', () => ({
  usersApi: {
    list: vi.fn().mockResolvedValue({ items: [] }),
    updateRole: vi.fn(),
    updateStatus: vi.fn(),
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

describe('UsersPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should render the page title', () => {
    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );
    expect(screen.getByText('user.management')).toBeInTheDocument();
  });

  it('should show user count tag', () => {
    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );
    expect(screen.getByText('user.userCount 0')).toBeInTheDocument();
  });

  it('should show empty state when no users', async () => {
    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText('user.noUsers')).toBeInTheDocument();
    });
  });
});