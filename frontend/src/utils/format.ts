import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { globalT } from '../i18n';

// dayjs locale 由 i18n/index.ts 统一管理，随语言切换动态变化
dayjs.extend(relativeTime);

/** 格式化文件大小 */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
  return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
}

/** 格式化日期时间 */
export function formatDateTime(date: string | Date): string {
  return dayjs(date).format('YYYY-MM-DD HH:mm');
}

/** 格式化相对时间 (如 "3分钟前") */
export function formatRelativeTime(date: string | Date): string {
  return dayjs(date).fromNow();
}

/** 格式化时间 (HH:mm) */
export function formatTime(date: string | Date): string {
  return dayjs(date).format('HH:mm');
}

/** 按日期分组消息 */
export function groupMessagesByDate<T extends { created_at?: string }>(
  messages: T[]
): { date: string; items: T[] }[] {
  const groups: { date: string; items: T[] }[] = [];
  let currentDate = '';
  
  for (const msg of messages) {
    const dateStr = dayjs(msg.created_at || new Date()).format('YYYY-MM-DD');
    if (dateStr !== currentDate) {
      currentDate = dateStr;
      groups.push({ date: dateStr, items: [msg] });
    } else {
      groups[groups.length - 1].items.push(msg);
    }
  }
  
  return groups;
}

/** 获取状态颜色 */
export function getStatusColor(status: string): string {
  const map: Record<string, string> = {
    pending: 'default',
    parsing: 'processing',
    chunking: 'processing',
    embedding: 'processing',
    done: 'success',
    failed: 'error',
  };
  return map[status] || 'default';
}

/** 状态 → i18n key 映射 */
const STATUS_I18N_KEYS: Record<string, string> = {
  pending: 'status.pending',
  parsing: 'status.parsing',
  chunking: 'status.chunking',
  embedding: 'status.embedding',
  done: 'status.done',
  failed: 'status.failed',
};

/** 获取状态文本（通过 i18n 全局 t 函数翻译，未识别状态返回原始字符串） */
export function getStatusTextKey(status: string): string {
  const key = STATUS_I18N_KEYS[status];
  if (key) {
    return globalT(key);
  }
  return status;
}

/** 复制文本到剪贴板 (带 fallback) */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {}
  // Fallback
  try {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
    return true;
  } catch {
    return false;
  }
}

/** 防抖 */
export function debounce<T extends (...args: unknown[]) => void>(
  fn: T,
  delay: number
): (...args: Parameters<T>) => void {
  let timer: ReturnType<typeof setTimeout>;
  return (...args: Parameters<T>) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

/** 文件类型图标颜色 */
export function getFileTypeColor(fileType: string): string {
  const map: Record<string, string> = {
    pdf: '#ff4d4f',
    docx: '#1677ff',
    md: '#52c41a',
    txt: '#8c8c8c',
  };
  return map[fileType] || '#8c8c8c';
}

/** 截断文本 */
export function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + '...';
}
