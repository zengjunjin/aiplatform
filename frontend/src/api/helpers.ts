import client, { extractData } from './client';

/**
 * Task 47: 统一的 GET 请求 helper，透传可选的 params 和 signal。
 *
 * signal 传递行为与原各处内联逻辑完全一致：
 * - 无 params 且无 signal → client.get(url) 单参数调用（匹配原 Pattern A）
 * - 有 params 或有 signal → client.get(url, { params?, signal? }) 双参数调用
 *
 * @param url    请求路径
 * @param params 可选的查询参数对象（undefined 表示无参数）
 * @param signal 可选的 AbortSignal
 */
export async function getWithOptionalSignal<T>(
  url: string,
  params?: object,
  signal?: AbortSignal,
): Promise<T> {
  // 无 params 且无 signal: 保持单参数调用，与原 system.ts / documents.ts 行为一致
  if (params === undefined && !signal) {
    const res = await client.get(url);
    return extractData<T>(res);
  }
  // 构建 config: 仅在有值时包含 params / signal 键
  const config: { params?: object; signal?: AbortSignal } = {};
  if (params !== undefined) config.params = params;
  if (signal) config.signal = signal;
  const res = await client.get(url, config);
  return extractData<T>(res);
}
