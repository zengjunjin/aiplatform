import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import SessionSider from '../../components/SessionSider';
import type { ChatSession } from '../../types';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mockSessions: ChatSession[] = [
  {
    id: 1,
    user_id: 1,
    title: 'First session',
    kb_id: 10,
    created_at: '',
    updated_at: '',
  },
  {
    id: 2,
    user_id: 1,
    title: '',
    kb_id: null,
    created_at: '',
    updated_at: '',
  },
];

describe('SessionSider', () => {
  it('should render new chat button', () => {
    render(
      <SessionSider
        siderVisible={true}
        sessions={[]}
        sessionIdNum={0}
        onNavigate={() => {}}
        onDeleteSession={() => {}}
        onNewSessionClick={() => {}}
        getKBName={() => ''}
      />
    );
    expect(screen.getByText('chat.newChat')).toBeInTheDocument();
  });

  it('should render all sessions with title or default new session text', () => {
    render(
      <SessionSider
        siderVisible={true}
        sessions={mockSessions}
        sessionIdNum={0}
        onNavigate={() => {}}
        onDeleteSession={() => {}}
        onNewSessionClick={() => {}}
        getKBName={() => ''}
      />
    );
    expect(screen.getByText('First session')).toBeInTheDocument();
    // Empty title should fall back to chat.newSession
    expect(screen.getByText('chat.newSession')).toBeInTheDocument();
  });

  it('should call onNavigate when session item clicked', () => {
    const onNavigate = vi.fn();
    render(
      <SessionSider
        siderVisible={true}
        sessions={mockSessions}
        sessionIdNum={0}
        onNavigate={onNavigate}
        onDeleteSession={() => {}}
        onNewSessionClick={() => {}}
        getKBName={() => ''}
      />
    );
    fireEvent.click(screen.getByText('First session'));
    expect(onNavigate).toHaveBeenCalledWith(1);
  });

  it('should call onNewSessionClick when new chat button clicked', () => {
    const onNewSessionClick = vi.fn();
    render(
      <SessionSider
        siderVisible={true}
        sessions={[]}
        sessionIdNum={0}
        onNavigate={() => {}}
        onDeleteSession={() => {}}
        onNewSessionClick={onNewSessionClick}
        getKBName={() => ''}
      />
    );
    fireEvent.click(screen.getByText('chat.newChat'));
    expect(onNewSessionClick).toHaveBeenCalled();
  });

  it('should call onDeleteSession when delete button clicked and stop propagation', () => {
    const onDeleteSession = vi.fn();
    const onNavigate = vi.fn();
    render(
      <SessionSider
        siderVisible={true}
        sessions={mockSessions}
        sessionIdNum={0}
        onNavigate={onNavigate}
        onDeleteSession={onDeleteSession}
        onNewSessionClick={() => {}}
        getKBName={() => ''}
      />
    );
    const deleteBtns = screen.getAllByLabelText('chat.deleteSession');
    fireEvent.click(deleteBtns[0]);
    expect(onDeleteSession).toHaveBeenCalledWith(1);
    // Navigation should not be triggered due to stopPropagation
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it('should call getKBName for each session', () => {
    const getKBName = vi.fn((kbId: number | null) => `KB-${kbId}`);
    render(
      <SessionSider
        siderVisible={true}
        sessions={mockSessions}
        sessionIdNum={0}
        onNavigate={() => {}}
        onDeleteSession={() => {}}
        onNewSessionClick={() => {}}
        getKBName={getKBName}
      />
    );
    expect(getKBName).toHaveBeenCalledWith(10);
    expect(getKBName).toHaveBeenCalledWith(null);
  });

  it('should apply is-active class to current session', () => {
    const { container } = render(
      <SessionSider
        siderVisible={true}
        sessions={mockSessions}
        sessionIdNum={1}
        onNavigate={() => {}}
        onDeleteSession={() => {}}
        onNewSessionClick={() => {}}
        getKBName={() => ''}
      />
    );
    const activeItem = container.querySelector('.chat-session-item.is-active');
    expect(activeItem).toBeTruthy();
  });
});
