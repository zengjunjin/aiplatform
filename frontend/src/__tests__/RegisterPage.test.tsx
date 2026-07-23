import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import RegisterPage from '../pages/RegisterPage';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// Mock errorReporter
vi.mock('../utils/errorReporter', () => ({
  getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));

// Mock store with vi.hoisted
const { mockRegister } = vi.hoisted(() => ({
  mockRegister: vi.fn(),
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
    const state = { register: mockRegister };
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

  it('should navigate to login page when login link clicked', () => {
    render(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>
    );
    fireEvent.click(screen.getByText('auth.loginNow'));
    expect(mockNavigate).toHaveBeenCalledWith('/login');
  });

  it('should render password strength bar', () => {
    render(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>
    );
    expect(screen.getByLabelText('auth.passwordStrength.title')).toBeInTheDocument();
  });

  it('should render copyright text', () => {
    render(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>
    );
    expect(screen.getByText('auth.copyright')).toBeInTheDocument();
  });

  it('should show password strength labels', () => {
    render(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>
    );
    expect(screen.getByText(/auth\.passwordStrength\.length/)).toBeInTheDocument();
    expect(screen.getByText(/auth\.passwordStrength\.uppercase/)).toBeInTheDocument();
    expect(screen.getByText(/auth\.passwordStrength\.lowercase/)).toBeInTheDocument();
    expect(screen.getByText(/auth\.passwordStrength\.digit/)).toBeInTheDocument();
    expect(screen.getByText(/auth\.passwordStrength\.symbol/)).toBeInTheDocument();
  });

  it('should call register and navigate on successful submission', async () => {
    mockRegister.mockResolvedValue(undefined);

    render(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>
    );

    // Fill form
    fireEvent.change(screen.getByPlaceholderText('auth.usernamePlaceholder'), {
      target: { value: 'newuser' },
    });
    fireEvent.change(screen.getByPlaceholderText('auth.emailPlaceholder'), {
      target: { value: 'new@test.com' },
    });
    const passwordInputs = screen.getAllByPlaceholderText('auth.passwordPlaceholder');
    fireEvent.change(passwordInputs[0], { target: { value: 'Password1!' } });
    fireEvent.change(screen.getByPlaceholderText('auth.confirmPasswordPlaceholder'), {
      target: { value: 'Password1!' },
    });

    // Submit
    fireEvent.click(screen.getByText('auth.register'));

    await waitFor(() => {
      expect(mockRegister).toHaveBeenCalledWith('newuser', 'new@test.com', 'Password1!');
    });

    await waitFor(() => {
      expect(msgSuccess).toHaveBeenCalledWith('auth.registerSuccess');
      expect(mockNavigate).toHaveBeenCalledWith('/');
    });
  });

  it('should show error message on registration failure', async () => {
    mockRegister.mockRejectedValue(new Error('Username already exists'));

    render(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByPlaceholderText('auth.usernamePlaceholder'), {
      target: { value: 'existing' },
    });
    fireEvent.change(screen.getByPlaceholderText('auth.emailPlaceholder'), {
      target: { value: 'exist@test.com' },
    });
    const passwordInputs = screen.getAllByPlaceholderText('auth.passwordPlaceholder');
    fireEvent.change(passwordInputs[0], { target: { value: 'Password1!' } });
    fireEvent.change(screen.getByPlaceholderText('auth.confirmPasswordPlaceholder'), {
      target: { value: 'Password1!' },
    });

    fireEvent.click(screen.getByText('auth.register'));

    await waitFor(() => {
      expect(msgError).toHaveBeenCalledWith('Username already exists');
    });
  });

  it('should not call register when passwords do not match (form validation prevents submit)', async () => {
    render(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByPlaceholderText('auth.usernamePlaceholder'), {
      target: { value: 'newuser' },
    });
    fireEvent.change(screen.getByPlaceholderText('auth.emailPlaceholder'), {
      target: { value: 'new@test.com' },
    });
    const passwordInputs = screen.getAllByPlaceholderText('auth.passwordPlaceholder');
    fireEvent.change(passwordInputs[0], { target: { value: 'Password1!' } });
    fireEvent.change(screen.getByPlaceholderText('auth.confirmPasswordPlaceholder'), {
      target: { value: 'DifferentPass1!' },
    });

    fireEvent.click(screen.getByText('auth.register'));

    // Form validation should prevent onFinish from being called
    await new Promise((r) => setTimeout(r, 100));
    expect(mockRegister).not.toHaveBeenCalled();
  });
});
