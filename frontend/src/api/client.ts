import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { useAuthStore } from '../store/auth';
import type { ApiResponse } from '../types';
import { isTauri } from '../utils/tauri';

/** API 基础路径：Tauri 环境下使用完整 URL，浏览器环境使用相对路径 */
export const API_BASE = isTauri() ? 'http://localhost:8000/api/v1' : '/api/v1';

const client = axios.create({
  baseURL: API_BASE,
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
});

interface RetryConfig extends InternalAxiosRequestConfig {
  _retryCount?: number;
}

const MAX_RETRIES = 2;
const RETRY_DELAY = 1000;

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
  return responseData?.message || error.message || '请求失败';
}

client.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

client.interceptors.response.use(
  (response) => {
    const data = response.data as ApiResponse;
    if (data.code !== 0 && data.code !== undefined) {
      return Promise.reject(new Error(data.message || '请求失败'));
    }
    return response;
  },
  async (error: AxiosError) => {
    const config = error.config as RetryConfig;
    
    if (!config) {
      return Promise.reject(error);
    }
    
    if (error.response?.status === 401) {
      useAuthStore.getState().logout();
      // Tauri 环境下不能用 window.location.href 做页面跳转
      // 使用 React Router 的 navigate 由各页面自行处理
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
