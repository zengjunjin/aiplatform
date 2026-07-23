import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { useAuthStore } from '../store/auth';
import type { ApiResponse } from '../types';
import { isTauri } from '../utils/tauri';
import { addBreadcrumb } from '../utils/errorReporter';
import { globalT } from '../i18n';

/** 获取 API 基础路径：Tauri 环境下使用完整 URL，浏览器环境使用相对路径 */
export const getApiBase = (): string => {
  return isTauri() ? 'http://localhost:8000/api/v1' : '/api/v1';
};

const client = axios.create({
  baseURL: getApiBase(),
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
});

interface RetryConfig extends InternalAxiosRequestConfig {
  _retryCount?: number;
  /** 标记该请求因 401 已尝试过一次 refresh + 重试，避免无限循环 */
  _retry?: boolean;
}

const MAX_RETRIES = 2;
const RETRY_DELAY = 1000;

/**
 * 并发锁：多个请求同时收到 401 时，只允许第一个触发 refreshAccessToken，
 * 其余请求复用同一个 Promise，避免用旧 refreshToken 并发刷新导致轮换失败。
 */
let refreshPromise: Promise<boolean> | null = null;
function refreshAccessTokenOnce(): Promise<boolean> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = useAuthStore.getState().refreshAccessToken().finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

function isRetryableError(error: AxiosError): boolean {
  if (!error.config) return false;
  
  const method = error.config.method?.toUpperCase();
  if (method !== 'GET') return false;
  
  if (!error.response) {
    return true;
  }
  
  const status = error.response.status;
  return status >= 500 || status === 429;
}

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function getErrorMessage(error: AxiosError): string {
  const responseData = error.response?.data as { message?: string } | undefined;
  return responseData?.message || error.message || globalT('common.requestFailed');
}

client.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  // API 面包屑：仅记录 method + url，不记录 body / headers（避免敏感信息泄露）
  addBreadcrumb({
    type: 'api',
    message: `${(config.method || 'GET').toUpperCase()} ${config.url || ''}`,
  });
  return config;
});

client.interceptors.response.use(
  (response) => {
    const data = response.data as ApiResponse;
    if (data.code !== 0 && data.code !== undefined) {
      return Promise.reject(new Error(data.message || globalT('common.requestFailed')));
    }
    return response;
  },
  async (error: AxiosError) => {
    const config = error.config as RetryConfig;

    if (!config) {
      return Promise.reject(error);
    }

    if (error.response?.status === 401) {
      // logout 请求自身的 401：不触发 refresh / logout，直接 reject
      const isLogoutRequest = config.url?.includes('/auth/logout');
      // refresh 请求自身的 401：不再次触发 refresh，避免递归
      const isRefreshRequest = config.url?.includes('/auth/refresh');

      // 仅对普通请求、且未重试过的请求尝试一次 refresh + 重试
      if (!config._retry && !isLogoutRequest && !isRefreshRequest) {
        config._retry = true;
        const ok = await refreshAccessTokenOnce();
        if (ok) {
          // 用新 access_token 重试原请求
          const newToken = useAuthStore.getState().token;
          if (newToken) {
            config.headers.Authorization = `Bearer ${newToken}`;
          }
          return client(config);
        }
        // refresh 失败：refreshAccessToken 内部已 logout
        const msg = getErrorMessage(error);
        return Promise.reject(new Error(msg));
      }

      // 已重试过 / logout / refresh 请求的 401：清理本地态后 reject
      if (!isLogoutRequest && !isRefreshRequest) {
        await useAuthStore.getState().logout();
      }
      const msg = getErrorMessage(error);
      return Promise.reject(new Error(msg));
    }
    
    config._retryCount = config._retryCount || 0;
    
    if (isRetryableError(error) && config._retryCount < MAX_RETRIES) {
      config._retryCount += 1;
      const backoffDelay = RETRY_DELAY * Math.pow(2, config._retryCount - 1);
      
      console.warn(
        `Retrying request (${config._retryCount}/${MAX_RETRIES}):`,
        config.method,
        config.url,
        `after ${backoffDelay}ms`
      );
      
      await delay(backoffDelay);
      return client(config);
    }
    
    const msg = getErrorMessage(error);
    return Promise.reject(new Error(msg));
  }
);

export function extractData<T>(response: { data: ApiResponse<T> }): T {
  return response.data.data;
}

export default client;
