import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import MainLayout from '../components/Layout';

// --- Stable mocks via vi.hoisted (must be stable to prevent useCallback/useEffect infinite loops) ---

// 1. react-i18next: stable t + i18n with changeLanguage spy
const { mockT, mockI18n } = vi.hoisted(() => ({
  mockT: (key: string, _params?: any) => key,
  mockI18n: {
    language: 'zh-CN',
    changeLanguage: vi.fn(),
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT, i18n: mockI18n }),
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

// 2. antd App.useApp: stable message reference (else fetchPreview useCallback infinite loop)
const { mockMessage } = vi.hoisted(() => ({
  mockMessage: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  return {
    ...(actual as any),
    App: Object.assign((actual as any).App, {
      useApp: () => ({ message: mockMessage }),
    }),
  };
});

// 3. useAuthStore: provide user/logout/themeMode/toggleTheme/token
const { mockLogout, mockToggleTheme, mockUser } = vi.hoisted(() => ({
  mockLogout: vi.fn().mockResolvedValue(undefined),
  mockToggleTheme: vi.fn(),
  mockUser: {
    id: 1,
    username: 'admin',
    email: 'admin@example.com',
    role: 'admin' as const,
    is_active: true,
    created_at: '',
    updated_at: '',
  },
}));

vi.mock('../store/auth', () => ({
  useAuthStore: (selector: any) =>
    selector({
      user: mockUser,
      logout: mockLogout,
      themeMode: 'light' as 'light' | 'dark',
      toggleTheme: mockToggleTheme,
      token: 'test-token',
    }),
}));

// 4. useWebSocket: no-op (no real WS connections in tests)
vi.mock('../hooks/useWebSocket', () => ({
  useWebSocket: vi.fn(),
}));

// 5. react-router-dom: override useNavigate only, keep useLocation/MemoryRouter/NavLink real
const { mockNavigate } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...(actual as any),
    useNavigate: () => mockNavigate,
  };
});

// 6. Tauri utilities: no-op in test environment
vi.mock('../utils/tauri', () => ({
  isTauri: () => false,
  setWindowTitle: vi.fn(),
}));

// 7. errorReporter
vi.mock('../utils/errorReporter', () => ({
  getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
  isFormValidationError: (e: unknown) =>
    typeof e === 'object' && e !== null && 'errorFields' in e,
}));

// 8. authApi (avoid real axios calls)
vi.mock('../api', () => ({
  authApi: { changePassword: vi.fn().mockResolvedValue(undefined) },
}));

// --- Test helper ---
function renderLayout(initialPath = '/dashboard') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/" element={<MainLayout />}>
          <Route path="dashboard" element={<div>Dashboard Page</div>} />
          <Route path="chat" element={<div>Chat Page</div>} />
          <Route path="knowledge-bases" element={<div>KB Page</div>} />
          <Route path="documents" element={<div>Documents Page</div>} />
          <Route path="users" element={<div>Users Page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

describe('MainLayout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('renders sidebar, header, and content area', () => {
    renderLayout();
    // Sidebar: platform name + subtitle
    expect(screen.getByText('nav.platformName')).toBeInTheDocument();
    expect(screen.getByText('nav.platformSubtitle')).toBeInTheDocument();
    // Sidebar: nav menu items (chat is unique — dashboard also appears as page title)
    expect(screen.getByText('nav.chat')).toBeInTheDocument();
    expect(screen.getByText('nav.knowledgeBase')).toBeInTheDocument();
    // Content: Outlet renders child route
    expect(screen.getByText('Dashboard Page')).toBeInTheDocument();
  });

  it('navigates to chat page when chat nav item is clicked', () => {
    renderLayout();
    // Initially on dashboard
    expect(screen.getByText('Dashboard Page')).toBeInTheDocument();
    // Click chat nav link (NavLink — MemoryRouter handles route change)
    fireEvent.click(screen.getByText('nav.chat'));
    // Outlet should now render chat page content
    expect(screen.getByText('Chat Page')).toBeInTheDocument();
  });

  it('opens user menu dropdown when avatar area is hovered', async () => {
    const user = userEvent.setup();
    const { container } = renderLayout();
    const trigger = container.querySelector('.user-dropdown-trigger') as HTMLElement;
    expect(trigger).toBeTruthy();
    // Hover to open dropdown (antd Dropdown default trigger is hover)
    await user.hover(trigger);
    // Dropdown menu items should appear (rendered to document.body portal)
    await waitFor(() => {
      expect(screen.getByText('nav.logout')).toBeInTheDocument();
      expect(screen.getByText('nav.changePassword')).toBeInTheDocument();
    });
  });

  it('opens password modal when change password menu item is clicked', async () => {
    const user = userEvent.setup();
    const { container } = renderLayout();
    // Open the user dropdown
    const trigger = container.querySelector('.user-dropdown-trigger') as HTMLElement;
    await user.hover(trigger);
    // Wait for dropdown menu to appear
    const changePwdItem = await screen.findByText('nav.changePassword');
    // Click "change password" → onClick: () => setPwdModal(true)
    await user.click(changePwdItem);
    // Modal should open with title
    await waitFor(() => {
      expect(screen.getByText('auth.changePasswordTitle')).toBeInTheDocument();
    });
  });

  it('toggles language when language button is clicked', () => {
    renderLayout();
    // Language toggle button has aria-label="nav.toggleLanguage"
    const langBtn = screen.getByLabelText('nav.toggleLanguage');
    fireEvent.click(langBtn);
    // i18n.changeLanguage should be called with 'en-US' (current is 'zh-CN')
    expect(mockI18n.changeLanguage).toHaveBeenCalledWith('en-US');
  });
});
