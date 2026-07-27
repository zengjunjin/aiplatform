import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
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

  // ========== T13 新增：覆盖角色切换、状态切换、分页、当前用户标记 ==========

  it('should show "currentUser" tag instead of action buttons for current user', async () => {
    // mockUser.id = 1, mockUsers[0].id = 1 → 当前用户行应显示 user.currentUser 标签
    mockList.mockResolvedValue({ items: [mockUsers[0]], total: 1 });

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('user.currentUser')).toBeInTheDocument();
    });
    // 不应显示操作按钮（当前用户行）
    expect(screen.queryByText('user.setAdmin')).not.toBeInTheDocument();
    expect(screen.queryByText('user.removeAdmin')).not.toBeInTheDocument();
  });

  it('should show action buttons for non-current user', async () => {
    // mockUsers[1].id = 2, currentUser.id = 1 → 应显示操作按钮
    mockList.mockResolvedValue({ items: [mockUsers[1]], total: 1 });

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      // mockUsers[1].role = 'user' → 按钮文本 'user.setAdmin'
      expect(screen.getByText('user.setAdmin')).toBeInTheDocument();
    });
    // mockUsers[1].is_active = false → 按钮文本 'user.enable'
    expect(screen.getByText('user.enable')).toBeInTheDocument();
  });

  it('should show "removeAdmin" button when user is admin', async () => {
    const adminUser = { ...mockUsers[1], id: 99, role: 'admin' as const };
    mockList.mockResolvedValue({ items: [adminUser], total: 1 });

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('user.removeAdmin')).toBeInTheDocument();
    });
  });

  it('should show "disable" button when user is active', async () => {
    const activeUser = { ...mockUsers[1], id: 99, is_active: true };
    mockList.mockResolvedValue({ items: [activeUser], total: 1 });

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('user.disable')).toBeInTheDocument();
    });
  });

  it('should call updateRole and refetch when confirming role change (user → admin)', async () => {
    // 非当前用户，role='user' → 点击 'setAdmin' 后确认
    mockList.mockResolvedValue({ items: [mockUsers[1]], total: 1 });
    mockUpdateRole.mockResolvedValue({});

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    // 等待列表渲染
    await waitFor(() => {
      expect(screen.getByText('user.setAdmin')).toBeInTheDocument();
    });

    // 点击 'setAdmin' 触发 Popconfirm
    fireEvent.click(screen.getByText('user.setAdmin'));

    // 等待 Popconfirm 出现并点击确认
    await waitFor(() => {
      expect(screen.getByText('user.setAdminConfirm')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('user.confirm'));

    // 验证 updateRole 被调用 (userId=2, role='admin')
    await waitFor(() => {
      expect(mockUpdateRole).toHaveBeenCalledWith(2, 'admin');
    });

    // runWithToast 成功后应调用 message.success('user.roleUpdated')
    await waitFor(() => {
      expect(msgSuccess).toHaveBeenCalledWith('user.roleUpdated');
    });

    // onSuccess 应触发 refetch (list 至少被调用 2 次：初始 + refetch)
    await waitFor(() => {
      expect(mockList).toHaveBeenCalledTimes(2);
    });
  });

  it('should call updateRole with "user" when demoting admin', async () => {
    const adminUser = { ...mockUsers[1], id: 99, role: 'admin' as const };
    mockList.mockResolvedValue({ items: [adminUser], total: 1 });
    mockUpdateRole.mockResolvedValue({});

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('user.removeAdmin')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('user.removeAdmin'));

    await waitFor(() => {
      expect(screen.getByText('user.setUserConfirm')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('user.confirm'));

    await waitFor(() => {
      expect(mockUpdateRole).toHaveBeenCalledWith(99, 'user');
    });
  });

  it('should show error toast when updateRole fails', async () => {
    mockList.mockResolvedValue({ items: [mockUsers[1]], total: 1 });
    mockUpdateRole.mockRejectedValue(new Error('role update failed'));

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('user.setAdmin')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('user.setAdmin'));
    await waitFor(() => {
      expect(screen.getByText('user.setAdminConfirm')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('user.confirm'));

    // runWithToast 失败时应调用 message.error
    await waitFor(() => {
      expect(msgError).toHaveBeenCalledWith('role update failed');
    });
  });

  it('should fall back to t(user.operationFailed) when updateRole fails without message', async () => {
    mockList.mockResolvedValue({ items: [mockUsers[1]], total: 1 });
    // getErrorMessage('') = String('') = '' (falsy) → 回退到 t(user.operationFailed)
    mockUpdateRole.mockRejectedValue('');

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('user.setAdmin')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('user.setAdmin'));
    await waitFor(() => {
      expect(screen.getByText('user.setAdminConfirm')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('user.confirm'));

    await waitFor(() => {
      expect(msgError).toHaveBeenCalledWith('user.operationFailed');
    });
  });

  it('should call updateStatus and show success toast when disabling user', async () => {
    const activeUser = { ...mockUsers[1], id: 99, is_active: true };
    mockList.mockResolvedValue({ items: [activeUser], total: 1 });
    mockUpdateStatus.mockResolvedValue({});

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('user.disable')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('user.disable'));

    await waitFor(() => {
      expect(screen.getByText('user.disableConfirm')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('user.confirm'));

    // updateStatus(99, false)
    await waitFor(() => {
      expect(mockUpdateStatus).toHaveBeenCalledWith(99, false);
    });

    // active=false → message.success('user.userDisabled')
    await waitFor(() => {
      expect(msgSuccess).toHaveBeenCalledWith('user.userDisabled');
    });

    // 应 refetch
    await waitFor(() => {
      expect(mockList).toHaveBeenCalledTimes(2);
    });
  });

  it('should call updateStatus and show "userEnabled" toast when enabling user', async () => {
    // mockUsers[1].is_active = false → 按钮是 'user.enable'
    mockList.mockResolvedValue({ items: [mockUsers[1]], total: 1 });
    mockUpdateStatus.mockResolvedValue({});

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('user.enable')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('user.enable'));

    await waitFor(() => {
      expect(screen.getByText('user.enableConfirm')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('user.confirm'));

    // updateStatus(2, true)
    await waitFor(() => {
      expect(mockUpdateStatus).toHaveBeenCalledWith(2, true);
    });

    // active=true → message.success('user.userEnabled')
    await waitFor(() => {
      expect(msgSuccess).toHaveBeenCalledWith('user.userEnabled');
    });
  });

  it('should show error toast when updateStatus fails', async () => {
    mockList.mockResolvedValue({ items: [mockUsers[1]], total: 1 });
    mockUpdateStatus.mockRejectedValue(new Error('status fail'));

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('user.enable')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('user.enable'));
    await waitFor(() => {
      expect(screen.getByText('user.enableConfirm')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('user.confirm'));

    await waitFor(() => {
      expect(msgError).toHaveBeenCalledWith('status fail');
    });
  });

  it('should render Skeleton when loading', async () => {
    // 用可控 promise 让 loading 保持 true
    let resolveList: (val: any) => void = () => {};
    mockList.mockReturnValue(
      new Promise((resolve) => {
        resolveList = resolve;
      }),
    );

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    // 等待 useEffect 触发 fetchUsers → setLoading(true)
    await waitFor(() => {
      expect(screen.queryByRole('paragraph') || document.querySelector('.ant-skeleton')).toBeTruthy();
    });

    // 释放 promise 让后续测试不被阻塞
    resolveList({ items: [], total: 0 });
  });

  it('should call list with page 2 when clicking next page', async () => {
    // total: 200, pageSize 默认 100 → 2 页
    mockList.mockResolvedValue({ items: mockUsers, total: 200 });

    const { container } = render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('admin')).toBeInTheDocument();
    });

    // 初始 list 调用 page=1
    expect(mockList).toHaveBeenCalledWith({ page: 1, page_size: 100 });

    // 点击下一页
    const nextBtn = container.querySelector('.ant-pagination-next')!;
    expect(nextBtn).toBeInTheDocument();
    fireEvent.click(nextBtn);

    // 应以 page=2 再次调用 list
    await waitFor(() => {
      expect(mockList).toHaveBeenCalledWith({ page: 2, page_size: 100 });
    });
  });

  it('should call list with new pageSize when changing page size', async () => {
    mockList.mockResolvedValue({ items: mockUsers, total: 200 });

    const { container } = render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('admin')).toBeInTheDocument();
    });

    // 打开 pageSize 选择器 (ant-select)
    const pageSizeSelect = container.querySelector('.ant-pagination-options .ant-select-selector')!;
    expect(pageSizeSelect).toBeInTheDocument();
    fireEvent.mouseDown(pageSizeSelect.querySelector('.ant-select-selection-search') || pageSizeSelect);

    // 等待下拉项出现，点击 50
    await waitFor(() => {
      const option = document.querySelector('.ant-select-item-option[title="50"]') as HTMLElement;
      // 不同 antd 版本可能用 title 或内容文本，尝试多种查找方式
      if (option) {
        fireEvent.click(option);
      } else {
        // 回退：找包含 "50" 的选项
        const opts = document.querySelectorAll('.ant-select-item-option');
        const target = Array.from(opts).find((o) => o.textContent?.includes('50'));
        if (target) fireEvent.click(target as HTMLElement);
      }
    });

    // 应以新的 page_size 调用 list
    await waitFor(() => {
      const calls = mockList.mock.calls.map((c) => c[0]);
      const has50 = calls.some((c) => c.page_size === 50);
      expect(has50).toBe(true);
    });
  });

  it('should call list with initial page=1 and page_size=100 on mount', async () => {
    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockList).toHaveBeenCalledWith({ page: 1, page_size: 100 });
    });
  });
});
