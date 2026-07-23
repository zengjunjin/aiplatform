import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import HeaderActions from '../components/HeaderActions';

// Stable mock for t function
const { mockT } = vi.hoisted(() => ({
  mockT: (key: string, _params?: any) => key,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT }),
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

// --- Stable callbacks (created once, cleared in beforeEach) ---
const onToggleLanguage = vi.fn();
const onToggleTheme = vi.fn();
const onPasswordClick = vi.fn();
const onLogoutClick = vi.fn();

const mockUser = {
  id: 1,
  username: 'admin',
  email: 'admin@example.com',
  role: 'admin' as const,
  is_active: true,
  created_at: '',
  updated_at: '',
};

const mockUserMenuItems = [
  {
    key: 'password',
    icon: null,
    label: 'nav.changePassword',
    onClick: onPasswordClick,
  },
  { type: 'divider' as const },
  {
    key: 'logout',
    icon: null,
    label: 'nav.logout',
    onClick: onLogoutClick,
  },
];

function renderHeaderActions(overrides: Record<string, any> = {}) {
  const props = {
    user: mockUser,
    themeMode: 'light' as 'light' | 'dark',
    currentLang: 'zh-CN',
    userMenuItems: mockUserMenuItems,
    onToggleLanguage,
    onToggleTheme,
    ...overrides,
  };
  return render(<HeaderActions {...props} />);
}

describe('HeaderActions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders language toggle, theme toggle, and user info', () => {
    renderHeaderActions();
    // Language button with aria-label
    expect(screen.getByLabelText('nav.toggleLanguage')).toBeInTheDocument();
    // Theme button with aria-label
    expect(screen.getByLabelText('nav.toggleTheme')).toBeInTheDocument();
    // Username displayed
    expect(screen.getByText('admin')).toBeInTheDocument();
    // When currentLang is 'zh-CN', the button shows 'EN' (the target language)
    expect(screen.getByText('EN')).toBeInTheDocument();
  });

  it('calls onToggleLanguage when language button is clicked', () => {
    renderHeaderActions();
    fireEvent.click(screen.getByLabelText('nav.toggleLanguage'));
    expect(onToggleLanguage).toHaveBeenCalledTimes(1);
  });

  it('opens dropdown menu when avatar area is hovered', async () => {
    const user = userEvent.setup();
    const { container } = renderHeaderActions();
    const trigger = container.querySelector('.user-dropdown-trigger') as HTMLElement;
    expect(trigger).toBeTruthy();
    await user.hover(trigger);
    // Dropdown menu items should appear (rendered to document.body portal)
    await waitFor(() => {
      expect(screen.getByText('nav.changePassword')).toBeInTheDocument();
      expect(screen.getByText('nav.logout')).toBeInTheDocument();
    });
  });

  it('triggers change password callback when password menu item is clicked', async () => {
    const user = userEvent.setup();
    const { container } = renderHeaderActions();
    const trigger = container.querySelector('.user-dropdown-trigger') as HTMLElement;
    await user.hover(trigger);
    const passwordItem = await screen.findByText('nav.changePassword');
    await user.click(passwordItem);
    expect(onPasswordClick).toHaveBeenCalledTimes(1);
  });

  it('calls onToggleTheme when theme button is clicked', () => {
    renderHeaderActions();
    fireEvent.click(screen.getByLabelText('nav.toggleTheme'));
    expect(onToggleTheme).toHaveBeenCalledTimes(1);
  });
});
