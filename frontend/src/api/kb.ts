import client, { extractData } from './client';
import type { KnowledgeBase, PaginatedResponse, CollaboratorInfo } from '../types';

export interface CreateKBParams {
  name: string;
  description?: string;
}

export interface UpdateKBParams {
  name?: string;
  description?: string;
}

export interface AddCollaboratorParams {
  user_id: number;
  permission: string;
}

export const kbApi = {
  /** 获取知识库列表 */
  async list(page = 1, pageSize = 100): Promise<PaginatedResponse<KnowledgeBase>> {
    const res = await client.get('/knowledge-bases', {
      params: { page, page_size: pageSize },
    });
    return extractData(res) as PaginatedResponse<KnowledgeBase>;
  },

  /** 获取知识库详情 */
  async get(id: number): Promise<KnowledgeBase> {
    const res = await client.get(`/knowledge-bases/${id}`);
    return extractData(res);
  },

  /** 创建知识库 */
  async create(params: CreateKBParams): Promise<KnowledgeBase> {
    const res = await client.post('/knowledge-bases', params);
    return extractData(res);
  },

  /** 更新知识库 */
  async update(id: number, params: UpdateKBParams): Promise<KnowledgeBase> {
    const res = await client.put(`/knowledge-bases/${id}`, params);
    return extractData(res);
  },

  /** 删除知识库 */
  async delete(id: number): Promise<void> {
    await client.delete(`/knowledge-bases/${id}`);
  },

  /** 获取协作者列表 */
  async getCollaborators(kbId: number): Promise<CollaboratorInfo[]> {
    const res = await client.get(`/knowledge-bases/${kbId}/collaborators`);
    return extractData(res);
  },

  /** 添加协作者 */
  async addCollaborator(kbId: number, params: AddCollaboratorParams): Promise<CollaboratorInfo> {
    const res = await client.post(`/knowledge-bases/${kbId}/collaborators`, params);
    return extractData(res);
  },

  /** 移除协作者 */
  async removeCollaborator(kbId: number, userId: number): Promise<void> {
    await client.delete(`/knowledge-bases/${kbId}/collaborators/${userId}`);
  },
};

export default kbApi;
