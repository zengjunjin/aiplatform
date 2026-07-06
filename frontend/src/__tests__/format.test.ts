import { describe, it, expect } from 'vitest';
import {
  formatFileSize,
  formatDateTime,
  truncate,
  getStatusColor,
  getStatusText,
  copyToClipboard,
  debounce,
} from '../utils/format';

describe('formatFileSize', () => {
  it('should format bytes', () => {
    expect(formatFileSize(0)).toBe('0 B');
    expect(formatFileSize(512)).toBe('512 B');
  });

  it('should format KB', () => {
    expect(formatFileSize(1024)).toBe('1.0 KB');
    expect(formatFileSize(1536)).toBe('1.5 KB');
  });

  it('should format MB', () => {
    expect(formatFileSize(1048576)).toBe('1.00 MB');
    expect(formatFileSize(5242880)).toBe('5.00 MB');
  });

  it('should format GB', () => {
    expect(formatFileSize(1073741824)).toBe('1.00 GB');
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
});

describe('getStatusColor', () => {
  it('should return correct colors', () => {
    expect(getStatusColor('pending')).toBe('default');
    expect(getStatusColor('parsing')).toBe('processing');
    expect(getStatusColor('done')).toBe('success');
    expect(getStatusColor('failed')).toBe('error');
  });

  it('should return default for unknown status', () => {
    expect(getStatusColor('unknown')).toBe('default');
  });
});

describe('getStatusText', () => {
  it('should return Chinese labels', () => {
    expect(getStatusText('pending')).toBe('等待处理');
    expect(getStatusText('parsing')).toBe('解析中');
    expect(getStatusText('done')).toBe('已就绪');
    expect(getStatusText('failed')).toBe('失败');
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
});
