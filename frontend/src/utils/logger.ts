/**
 * Task 6.1: 统一日志工具
 * 生产环境 debug/info 不输出，warn/error 仍输出到控制台（便于排查）。
 * 替代散落在 store/utils 中的 console.error 调用。
 */
const isDev = import.meta.env.DEV;

export const logger = {
  debug: (...args: unknown[]) => isDev && console.debug(...args),
  info: (...args: unknown[]) => isDev && console.info(...args),
  warn: (...args: unknown[]) => console.warn(...args),
  error: (...args: unknown[]) => console.error(...args),
};
