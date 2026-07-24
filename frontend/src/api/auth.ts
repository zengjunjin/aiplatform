import client, { extractData } from './client';
import type { User, LoginResponse } from '../types';

export interface LoginParams {
  username: string;
  password: string;
}

export interface RegisterParams {
  username: string;
  email: string;
  password: string;
}

export interface ChangePasswordParams {
  old_password: string;
  new_password: string;
}

export const authApi = {
  /** 登录 */
  async login(params: LoginParams): Promise<LoginResponse> {
    const res = await client.post('/auth/login', params);
    return extractData<LoginResponse>(res);
  },

  /** 注册 */
  async register(params: RegisterParams): Promise<User> {
    const res = await client.post('/auth/register', params);
    return extractData<User>(res);
  },

  /** 获取当前用户 */
  async getMe(): Promise<User> {
    const res = await client.get('/auth/me');
    return extractData<User>(res);
  },

  /** 登出
   *
   * 传 refresh_token 让后端拉黑，修复"登出后 refresh_token 仍有效 7 天"的安全漏洞。
   * 后端 logout 端点对 refresh_token 可选兼容（不传也返回 200），但前端应主动传。
   */
  async logout(refreshToken?: string | null): Promise<void> {
    await client.post('/auth/logout', refreshToken ? { refresh_token: refreshToken } : undefined);
  },

  /** 刷新 token */
  async refreshToken(refreshToken: string): Promise<LoginResponse> {
    const res = await client.post('/auth/refresh', { refresh_token: refreshToken });
    return extractData<LoginResponse>(res);
  },

  /** 修改密码 */
  async changePassword(params: ChangePasswordParams): Promise<void> {
    await client.put('/auth/password', params);
  },

  /** 搜索用户（按用户名） */
  async searchUsers(query: string): Promise<{ id: number; username: string }[]> {
    const res = await client.get('/users/search', { params: { q: query } });
    return extractData<{ id: number; username: string }[]>(res);
  },
};

export default authApi;
