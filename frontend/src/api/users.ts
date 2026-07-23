import client from './client';
import { getWithOptionalSignal } from './helpers';
import type { User } from '../types';
import type { PaginatedData } from './evaluation';

export interface ListUsersParams {
  page?: number;
  page_size?: number;
  keyword?: string;
}

export const usersApi = {
  /** 获取用户列表 (admin) */
  async list(params: ListUsersParams = {}, signal?: AbortSignal): Promise<PaginatedData<User>> {
    // 兼容两种返回格式: 旧版数组 / PaginatedData
    // 注意: 即使 params 默认为 {} 也需传 config 对象 (测试期望 { params: {} })
    const data = await getWithOptionalSignal<User[] | PaginatedData<User>>('/users', params, signal);
    if (Array.isArray(data)) {
      return { items: data, total: data.length, page: 1, page_size: data.length, total_pages: 1 };
    }
    return data || { items: [], total: 0, page: 1, page_size: 20, total_pages: 0 };
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
