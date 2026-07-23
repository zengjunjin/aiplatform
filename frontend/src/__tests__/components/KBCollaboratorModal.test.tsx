import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import KBCollaboratorModal from '../../components/KBCollaboratorModal';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// Mock antd App.useApp
const messageMock = {
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
};
vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  return {
    ...(actual as any),
    App: Object.assign((actual as any).App, {
      useApp: () => ({ message: messageMock }),
    }),
  };
});

// Mock errorReporter utils
vi.mock('../../utils/errorReporter', () => ({
  getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
  isFormValidationError: (e: unknown) => {
    return typeof e === 'object' && e !== null && 'errorFields' in e;
  },
}));

// Mock API - vi.hoisted ensures mocks are available in vi.mock factory (hoisted)
const { getCollaboratorsMock, addCollaboratorMock, removeCollaboratorMock, searchUsersMock } = vi.hoisted(() => ({
  getCollaboratorsMock: vi.fn(),
  addCollaboratorMock: vi.fn(),
  removeCollaboratorMock: vi.fn(),
  searchUsersMock: vi.fn(),
}));

vi.mock('../../api', () => ({
  kbApi: {
    getCollaborators: getCollaboratorsMock,
    addCollaborator: addCollaboratorMock,
    removeCollaborator: removeCollaboratorMock,
  },
}));

vi.mock('../../api/auth', () => ({
  default: {
    searchUsers: searchUsersMock,
  },
}));

describe('KBCollaboratorModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getCollaboratorsMock.mockResolvedValue([]);
    addCollaboratorMock.mockResolvedValue({});
    removeCollaboratorMock.mockResolvedValue(undefined);
    searchUsersMock.mockResolvedValue([]);
  });

  it('should render modal title and add collaborator section when open', async () => {
    render(<KBCollaboratorModal open={true} kbId={1} onClose={() => {}} />);
    expect(screen.getByText('kb.collaborators')).toBeInTheDocument();
    expect(screen.getByText('kb.addCollaborator')).toBeInTheDocument();
  });

  it('should fetch collaborators when open becomes true', async () => {
    const mockCollabs = [
      { user_id: 2, username: 'user2', permission: 'read' as const },
      { user_id: 3, username: 'user3', permission: 'write' as const },
    ];
    getCollaboratorsMock.mockResolvedValue(mockCollabs);

    render(<KBCollaboratorModal open={true} kbId={1} onClose={() => {}} />);

    await waitFor(() => {
      expect(getCollaboratorsMock).toHaveBeenCalledWith(1);
    });
  });

  it('should show empty state when no collaborators', async () => {
    getCollaboratorsMock.mockResolvedValue([]);

    render(<KBCollaboratorModal open={true} kbId={1} onClose={() => {}} />);

    await waitFor(() => {
      expect(getCollaboratorsMock).toHaveBeenCalled();
    });
    expect(screen.getByText('kb.noCollaborators')).toBeInTheDocument();
  });

  it('should render collaborator list with username and permission tag', async () => {
    const mockCollabs = [
      { user_id: 2, username: 'alice', permission: 'admin' as const },
      { user_id: 3, username: 'bob', permission: 'write' as const },
      { user_id: 4, username: 'carol', permission: 'read' as const },
    ];
    getCollaboratorsMock.mockResolvedValue(mockCollabs);

    render(<KBCollaboratorModal open={true} kbId={1} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText('alice')).toBeInTheDocument();
    });
    expect(screen.getByText('bob')).toBeInTheDocument();
    expect(screen.getByText('carol')).toBeInTheDocument();
    expect(screen.getByText('kb.permAdmin')).toBeInTheDocument();
    expect(screen.getByText('kb.permWrite')).toBeInTheDocument();
    expect(screen.getByText('kb.permRead')).toBeInTheDocument();
  });

  it('should show error message when fetch collaborators fails', async () => {
    getCollaboratorsMock.mockRejectedValue(new Error('Network error'));

    render(<KBCollaboratorModal open={true} kbId={1} onClose={() => {}} />);

    await waitFor(() => {
      expect(messageMock.error).toHaveBeenCalledWith('Network error');
    });
  });

  it('should call onClose when modal close triggered', async () => {
    const onClose = vi.fn();
    const { container } = render(<KBCollaboratorModal open={true} kbId={1} onClose={onClose} />);

    await waitFor(() => {
      expect(getCollaboratorsMock).toHaveBeenCalled();
    });

    // Find cancel/close button in modal header
    const closeBtn = container.querySelector('.ant-modal-close');
    if (closeBtn) {
      fireEvent.click(closeBtn);
      expect(onClose).toHaveBeenCalled();
    }
  });

  it('should render add button and permission select', async () => {
    render(<KBCollaboratorModal open={true} kbId={1} onClose={() => {}} />);

    await waitFor(() => {
      expect(getCollaboratorsMock).toHaveBeenCalled();
    });

    expect(screen.getByText('kb.add')).toBeInTheDocument();
    // Permission options exist in select
    expect(screen.getByText('kb.permission')).toBeInTheDocument();
  });

  it('should render user search placeholder when not searching', async () => {
    getCollaboratorsMock.mockResolvedValue([]);
    render(<KBCollaboratorModal open={true} kbId={1} onClose={() => {}} />);

    await waitFor(() => {
      expect(getCollaboratorsMock).toHaveBeenCalled();
    });

    // The search input placeholder should be visible
    expect(screen.getByText('kb.userSearchPlaceholder')).toBeInTheDocument();
    expect(screen.getByText('kb.permission')).toBeInTheDocument();
  });

  it('should render current collaborators divider', async () => {
    render(<KBCollaboratorModal open={true} kbId={1} onClose={() => {}} />);

    await waitFor(() => {
      expect(getCollaboratorsMock).toHaveBeenCalled();
    });

    expect(screen.getByText('kb.currentCollaborators')).toBeInTheDocument();
  });
});
