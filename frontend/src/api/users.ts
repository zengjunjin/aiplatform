import client, { extractData } from './client';
import type { User } from '../types';

export interface ListUsersParams {
  page?: number;
  page_size?: number;
  keyword?: string;
}

export const usersApi = {
  /** 获取用户列表 (admin) */
  async list(params: ListUsersParams = {}): Promise<{ items: User[]; total: number }> {
    const res = await client.get('/users', { params });
    // 兼容两种返回格式
    const data = extractData(res) as any;
    if (Array.isArray(data)) {
      return { items: data, total: data.length };
    }
    return data || { items: [], total: 0 };
  },

  /** 修改用户角色 (admin) */
  async updateRole(userId: number, role: string): Promise<void> {
    await client.put(`/users/${userId}/role`, { role });
  },

  /** 修改用户状态 (admin) */
  async updateStatus(userId: number, is_active: boolean): Promise<void> {
    await client.put(`/users/${userId}/status`, { is_active });
  },
};

export default usersApi;
