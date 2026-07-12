import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import RegisterPage from '../pages/RegisterPage';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// Mock store
const mockRegister = vi.fn();
vi.mock('../store/auth', () => ({
  useAuthStore: (selector: any) => {
    const state = { register: mockRegister };
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

describe('RegisterPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should render register form', () => {
    render(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>
    );
    expect(screen.getByText('auth.createAccount')).toBeInTheDocument();
    expect(screen.getByText('auth.registerSubtitle')).toBeInTheDocument();
  });

  it('should render username, email, password and confirm password inputs', () => {
    render(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>
    );
    expect(screen.getByPlaceholderText('auth.usernamePlaceholder')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('auth.emailPlaceholder')).toBeInTheDocument();
    expect(screen.getAllByPlaceholderText('auth.passwordPlaceholder').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByPlaceholderText('auth.confirmPasswordPlaceholder')).toBeInTheDocument();
  });

  it('should render register submit button', () => {
    render(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>
    );
    expect(screen.getByText('auth.register')).toBeInTheDocument();
  });

  it('should render login link', () => {
    render(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>
    );
    expect(screen.getByText('auth.loginNow')).toBeInTheDocument();
  });
});