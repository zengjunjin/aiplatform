import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import UsersPage from '../pages/UsersPage';

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
const { mockUser } = vi.hoisted(() => ({
  mockUser: { id: 1, username: 'admin', email: 'admin@test.com', role: 'admin', is_active: true },
}));

vi.mock('../store/auth', () => ({
  useAuthStore: (selector: any) => {
    const state = { user: mockUser };
    return selector(state);
  },
}));

// Mock API with vi.hoisted
const { mockList, mockUpdateRole, mockUpdateStatus } = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockUpdateRole: vi.fn(),
  mockUpdateStatus: vi.fn(),
}));

vi.mock('../api', () => ({
  usersApi: {
    list: mockList,
    updateRole: mockUpdateRole,
    updateStatus: mockUpdateStatus,
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

const mockUsers = [
  { id: 1, username: 'admin', email: 'admin@test.com', role: 'admin', is_active: true, created_at: '', updated_at: '' },
  { id: 2, username: 'user1', email: 'user1@test.com', role: 'user', is_active: false, created_at: '', updated_at: '' },
];

describe('UsersPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockList.mockResolvedValue({ items: [], total: 0 });
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

  it('should call usersApi.list on mount', async () => {
    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(mockList).toHaveBeenCalled();
    });
  });

  it('should render user list when users exist', async () => {
    mockList.mockResolvedValue({ items: mockUsers, total: 2 });

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('admin')).toBeInTheDocument();
      expect(screen.getByText('user1')).toBeInTheDocument();
    });
  });

  it('should show error message when fetch fails', async () => {
    mockList.mockRejectedValue(new Error('Network error'));

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(msgError).toHaveBeenCalledWith('Network error');
    });
  });

  it('should render admin role tag for admin users', async () => {
    mockList.mockResolvedValue({ items: [mockUsers[0]], total: 1 });

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('user.admin')).toBeInTheDocument();
    });
  });

  it('should render normal user tag for non-admin users', async () => {
    mockList.mockResolvedValue({ items: [mockUsers[1]], total: 1 });

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('user.normalUser')).toBeInTheDocument();
    });
  });

  it('should render active status for active users', async () => {
    mockList.mockResolvedValue({ items: [mockUsers[0]], total: 1 });

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('user.active')).toBeInTheDocument();
    });
  });

  it('should render disabled status for inactive users', async () => {
    mockList.mockResolvedValue({ items: [mockUsers[1]], total: 1 });

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('user.disabled')).toBeInTheDocument();
    });
  });

  it('should render table headers', async () => {
    mockList.mockResolvedValue({ items: mockUsers, total: 2 });

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('user.id')).toBeInTheDocument();
      expect(screen.getByText('user.username')).toBeInTheDocument();
      expect(screen.getByText('user.email')).toBeInTheDocument();
      expect(screen.getByText('user.role')).toBeInTheDocument();
      expect(screen.getByText('user.status')).toBeInTheDocument();
    });
  });

  it('should show user count with total', async () => {
    mockList.mockResolvedValue({ items: mockUsers, total: 2 });

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('user.userCount 2')).toBeInTheDocument();
    });
  });
});
