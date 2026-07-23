import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import NotificationPopover from '../components/NotificationPopover';
import type { NotifItem } from '../components/NotificationPopover';

// Stable mock for t function
const { mockT } = vi.hoisted(() => ({
  mockT: (key: string, _params?: any) => key,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT }),
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

const sampleNotifications: NotifItem[] = [
  {
    type: 'notification',
    title: 'Test Notification 1',
    message: 'Message 1 content',
    data: {},
    user_id: '1',
    timestamp: 1000,
  },
  {
    type: 'notification',
    title: 'Test Notification 2',
    message: 'Message 2 content',
    data: {},
    user_id: '1',
    timestamp: 2000,
  },
];

describe('NotificationPopover', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders notification bell button with unread badge count', () => {
    const { container } = render(
      <NotificationPopover
        open={false}
        notifications={sampleNotifications}
        readAt={0}
        onOpenChange={vi.fn()}
        onClear={vi.fn()}
      />
    );
    // Bell button exists with aria-label="notification.title"
    const bellBtn = screen.getByLabelText('notification.title');
    expect(bellBtn).toBeInTheDocument();
    // Badge shows unread count = 2 (both timestamps > readAt=0)
    const badge = container.querySelector('.ant-badge-count');
    expect(badge?.textContent).toContain('2');
  });

  it('displays WS-pushed notification items in popover content when open', () => {
    render(
      <NotificationPopover
        open
        notifications={sampleNotifications}
        readAt={0}
        onOpenChange={vi.fn()}
        onClear={vi.fn()}
      />
    );
    // Both notification titles and messages are rendered in the popover
    expect(screen.getByText('Test Notification 1')).toBeInTheDocument();
    expect(screen.getByText('Message 1 content')).toBeInTheDocument();
    expect(screen.getByText('Test Notification 2')).toBeInTheDocument();
    expect(screen.getByText('Message 2 content')).toBeInTheDocument();
    // Clear button is present when notifications exist
    expect(screen.getByText('notification.clear')).toBeInTheDocument();
  });

  it('updates unread badge count when readAt changes (mark as read)', () => {
    const { container, rerender } = render(
      <NotificationPopover
        open={false}
        notifications={sampleNotifications}
        readAt={0}
        onOpenChange={vi.fn()}
        onClear={vi.fn()}
      />
    );
    // Initially both notifications are unread → badge shows "2"
    let badge = container.querySelector('.ant-badge-count');
    expect(badge?.textContent).toContain('2');

    // After readAt=1500, only the second notification (timestamp=2000) is unread
    rerender(
      <NotificationPopover
        open={false}
        notifications={sampleNotifications}
        readAt={1500}
        onOpenChange={vi.fn()}
        onClear={vi.fn()}
      />
    );
    badge = container.querySelector('.ant-badge-count');
    expect(badge?.textContent).toContain('1');
  });

  it('shows empty state message when notifications array is empty', () => {
    render(
      <NotificationPopover
        open
        notifications={[]}
        readAt={0}
        onOpenChange={vi.fn()}
        onClear={vi.fn()}
      />
    );
    // Empty state message is displayed
    expect(screen.getByText('notification.empty')).toBeInTheDocument();
    // Clear button should NOT be rendered when there are no notifications
    expect(screen.queryByText('notification.clear')).not.toBeInTheDocument();
  });

  it('calls onClear when clear button is clicked', () => {
    const onClear = vi.fn();
    render(
      <NotificationPopover
        open
        notifications={sampleNotifications}
        readAt={0}
        onOpenChange={vi.fn()}
        onClear={onClear}
      />
    );
    fireEvent.click(screen.getByText('notification.clear'));
    expect(onClear).toHaveBeenCalledTimes(1);
  });
});
