import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import LoginPage from '../pages/LoginPage';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// Mock errorReporter
vi.mock('../utils/errorReporter', () => ({
  getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));

// Mock store with vi.hoisted to support form submission tests
const { mockLogin } = vi.hoisted(() => ({
  mockLogin: vi.fn(),
}));

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

vi.mock('../store/auth', () => ({
  useAuthStore: (selector: any) => {
    const state = { login: mockLogin };
    return selector(state);
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

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should render login form', () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    );
    expect(screen.getByText('auth.welcomeBack')).toBeInTheDocument();
    expect(screen.getByText('auth.loginSubtitle')).toBeInTheDocument();
  });

  it('should render username and password inputs', () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    );
    expect(screen.getByPlaceholderText('auth.usernamePlaceholder')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('auth.passwordPlaceholder')).toBeInTheDocument();
  });

  it('should render login submit button', () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    );
    expect(screen.getByText('auth.login')).toBeInTheDocument();
  });

  it('should render register link', () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    );
    expect(screen.getByText('auth.registerNow')).toBeInTheDocument();
  });

  it('should navigate to register page when register link clicked', () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    );
    fireEvent.click(screen.getByText('auth.registerNow'));
    expect(mockNavigate).toHaveBeenCalledWith('/register');
  });

  it('should call login and navigate to dashboard on successful submit', async () => {
    mockLogin.mockResolvedValue(undefined);

    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    );

    // Fill form
    fireEvent.change(screen.getByPlaceholderText('auth.usernamePlaceholder'), {
      target: { value: 'testuser' },
    });
    fireEvent.change(screen.getByPlaceholderText('auth.passwordPlaceholder'), {
      target: { value: 'password123' },
    });

    // Submit form
    fireEvent.click(screen.getByText('auth.login'));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('testuser', 'password123');
    });

    await waitFor(() => {
      expect(msgSuccess).toHaveBeenCalledWith('auth.loginSuccess');
      expect(mockNavigate).toHaveBeenCalledWith('/dashboard');
    });
  });

  it('should show error message on login failure', async () => {
    mockLogin.mockRejectedValue(new Error('Invalid credentials'));

    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByPlaceholderText('auth.usernamePlaceholder'), {
      target: { value: 'testuser' },
    });
    fireEvent.change(screen.getByPlaceholderText('auth.passwordPlaceholder'), {
      target: { value: 'wrongpass' },
    });

    fireEvent.click(screen.getByText('auth.login'));

    await waitFor(() => {
      expect(msgError).toHaveBeenCalledWith('Invalid credentials');
    });

    // Should not navigate on failure
    expect(mockNavigate).not.toHaveBeenCalledWith('/dashboard');
  });

  it('should show generic error message when error has no message', async () => {
    mockLogin.mockRejectedValue('string error');

    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByPlaceholderText('auth.usernamePlaceholder'), {
      target: { value: 'testuser' },
    });
    fireEvent.change(screen.getByPlaceholderText('auth.passwordPlaceholder'), {
      target: { value: 'wrongpass' },
    });

    fireEvent.click(screen.getByText('auth.login'));

    await waitFor(() => {
      expect(msgError).toHaveBeenCalledWith('string error');
    });
  });

  it('should render copyright text', () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    );
    expect(screen.getByText('auth.copyright')).toBeInTheDocument();
  });
});
