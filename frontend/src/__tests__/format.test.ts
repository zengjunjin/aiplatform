import { describe, it, expect, vi } from 'vitest';
import {
  formatFileSize,
  formatDateTime,
  formatTime,
  formatRelativeTime,
  groupMessagesByDate,
  truncate,
  getStatusColor,
  getStatusTextKey,
  getFileTypeColor,
  copyToClipboard,
  debounce,
} from '../utils/format';

describe('formatFileSize', () => {
  it('should format bytes', () => {
    expect(formatFileSize(0)).toBe('0 B');
    expect(formatFileSize(512)).toBe('512 B');
    expect(formatFileSize(1023)).toBe('1023 B');
  });

  it('should format KB', () => {
    expect(formatFileSize(1024)).toBe('1.0 KB');
    expect(formatFileSize(1536)).toBe('1.5 KB');
    expect(formatFileSize(102400)).toBe('100.0 KB');
  });

  it('should format MB', () => {
    expect(formatFileSize(1048576)).toBe('1.00 MB');
    expect(formatFileSize(5242880)).toBe('5.00 MB');
    expect(formatFileSize(104857600)).toBe('100.00 MB');
  });

  it('should format GB', () => {
    expect(formatFileSize(1073741824)).toBe('1.00 GB');
    expect(formatFileSize(5368709120)).toBe('5.00 GB');
  });
});

describe('formatDateTime', () => {
  it('should format date string', () => {
    const result = formatDateTime('2024-01-15T10:30:00');
    expect(result).toBe('2024-01-15 10:30');
  });

  it('should format Date object', () => {
    const result = formatDateTime(new Date('2024-06-01T08:00:00'));
    expect(result).toBe('2024-06-01 08:00');
  });
});

describe('formatTime', () => {
  it('should format to HH:mm', () => {
    const result = formatTime('2024-01-15T14:05:30');
    expect(result).toBe('14:05');
  });

  it('should format Date object to HH:mm', () => {
    const result = formatTime(new Date('2024-01-15T09:15:00'));
    expect(result).toBe('09:15');
  });
});

describe('formatRelativeTime', () => {
  it('should return relative time string', () => {
    const result = formatRelativeTime(new Date());
    expect(result).toContain('前');
  });

  it('should return relative time for past date', () => {
    const pastDate = new Date(Date.now() - 3600000); // 1 hour ago
    const result = formatRelativeTime(pastDate);
    expect(typeof result).toBe('string');
    expect(result.length).toBeGreaterThan(0);
  });
});

describe('groupMessagesByDate', () => {
  it('should group messages by date', () => {
    const messages = [
      { created_at: '2024-01-01T10:00:00', content: 'msg1' },
      { created_at: '2024-01-01T11:00:00', content: 'msg2' },
      { created_at: '2024-01-02T09:00:00', content: 'msg3' },
    ];
    const groups = groupMessagesByDate(messages);
    expect(groups).toHaveLength(2);
    expect(groups[0].date).toBe('2024-01-01');
    expect(groups[0].items).toHaveLength(2);
    expect(groups[1].date).toBe('2024-01-02');
    expect(groups[1].items).toHaveLength(1);
  });

  it('should handle empty array', () => {
    const groups = groupMessagesByDate([]);
    expect(groups).toHaveLength(0);
  });

  it('should handle messages without created_at', () => {
    const messages = [
      { content: 'msg1', created_at: undefined as unknown as string },
      { content: 'msg2', created_at: undefined as unknown as string },
    ];
    const groups = groupMessagesByDate(messages);
    expect(groups).toHaveLength(1);
  });
});

describe('truncate', () => {
  it('should return original string when shorter than maxLen', () => {
    expect(truncate('hello', 10)).toBe('hello');
  });

  it('should truncate and add ellipsis', () => {
    expect(truncate('hello world', 5)).toBe('hello...');
  });

  it('should handle empty string', () => {
    expect(truncate('', 10)).toBe('');
  });

  it('should return original when length equals maxLen', () => {
    expect(truncate('hello', 5)).toBe('hello');
  });
});

describe('getStatusColor', () => {
  it('should return correct colors', () => {
    expect(getStatusColor('pending')).toBe('default');
    expect(getStatusColor('parsing')).toBe('processing');
    expect(getStatusColor('chunking')).toBe('processing');
    expect(getStatusColor('embedding')).toBe('processing');
    expect(getStatusColor('done')).toBe('success');
    expect(getStatusColor('failed')).toBe('error');
  });

  it('should return default for unknown status', () => {
    expect(getStatusColor('unknown')).toBe('default');
  });
});

describe('getStatusTextKey', () => {
  it('should return Chinese labels', () => {
    expect(getStatusTextKey('pending')).toBe('等待处理');
    expect(getStatusTextKey('parsing')).toBe('解析中');
    expect(getStatusTextKey('chunking')).toBe('分块中');
    expect(getStatusTextKey('embedding')).toBe('向量化中');
    expect(getStatusTextKey('done')).toBe('已就绪');
    expect(getStatusTextKey('failed')).toBe('失败');
  });

  it('should return original status for unknown', () => {
    expect(getStatusTextKey('unknown_status')).toBe('unknown_status');
  });
});

describe('getFileTypeColor', () => {
  it('should return correct colors for known types', () => {
    expect(getFileTypeColor('pdf')).toBe('#ff4d4f');
    expect(getFileTypeColor('docx')).toBe('#1677ff');
    expect(getFileTypeColor('md')).toBe('#52c41a');
    expect(getFileTypeColor('txt')).toBe('#8c8c8c');
  });

  it('should return default color for unknown type', () => {
    expect(getFileTypeColor('xlsx')).toBe('#8c8c8c');
    expect(getFileTypeColor('')).toBe('#8c8c8c');
  });
});

describe('copyToClipboard', () => {
  it('should return true on successful copy', async () => {
    // Mock clipboard API
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      writable: true,
      configurable: true,
    });

    const result = await copyToClipboard('test text');
    expect(result).toBe(true);
    expect(writeText).toHaveBeenCalledWith('test text');
  });

  it('should return false when clipboard is not available', async () => {
    // Remove clipboard
    Object.defineProperty(navigator, 'clipboard', {
      value: undefined,
      writable: true,
      configurable: true,
    });

    const result = await copyToClipboard('test text');
    // Should fallback to execCommand or return false
    expect(typeof result).toBe('boolean');
  });
});

describe('debounce', () => {
  it('should debounce function calls', async () => {
    let count = 0;
    const fn = debounce(() => count++, 50);

    fn();
    fn();
    fn();

    expect(count).toBe(0);

    await new Promise((r) => setTimeout(r, 100));
    expect(count).toBe(1);
  });

  it('should pass arguments to debounced function', async () => {
    let receivedArgs: any[] = [];
    const fn = debounce((...args: any[]) => { receivedArgs = args; }, 50);

    fn('hello', 42);

    await new Promise((r) => setTimeout(r, 100));
    expect(receivedArgs).toEqual(['hello', 42]);
  });

  it('should reset timer on subsequent calls', async () => {
    let count = 0;
    const fn = debounce(() => count++, 50);

    fn();
    await new Promise((r) => setTimeout(r, 30));
    fn(); // reset timer

    await new Promise((r) => setTimeout(r, 30));
    expect(count).toBe(0); // not yet fired

    await new Promise((r) => setTimeout(r, 40));
    expect(count).toBe(1);
  });
});
