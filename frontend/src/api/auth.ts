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
    return extractData(res);
  },

  /** 注册 */
  async register(params: RegisterParams): Promise<User> {
    const res = await client.post('/auth/register', params);
    return extractData(res);
  },

  /** 获取当前用户 */
  async getMe(): Promise<User> {
    const res = await client.get('/auth/me');
    return extractData(res);
  },

  /** 登出 */
  async logout(): Promise<void> {
    await client.post('/auth/logout');
  },

  /** 刷新 token */
  async refreshToken(refreshToken: string): Promise<LoginResponse> {
    const res = await client.post('/auth/refresh', { refresh_token: refreshToken });
    return extractData(res);
  },

  /** 修改密码 */
  async changePassword(params: ChangePasswordParams): Promise<void> {
    await client.put('/auth/password', params);
  },

  /** 搜索用户（按用户名） */
  async searchUsers(query: string): Promise<{ id: number; username: string }[]> {
    const res = await client.get('/users/search', { params: { q: query } });
    return extractData(res);
  },
};

export default authApi;
