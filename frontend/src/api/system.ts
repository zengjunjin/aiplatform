import client, { extractData } from './client';

export interface SystemStatus {
  status: string;
  postgres: string;
  redis: string;
  ollama: string;
  qdrant: string;
  celery: string;
}

export interface ModelInfo {
  name: string;
  display_name: string;
  source: string;
  status: string;
}

export interface ModelsResponse {
  models: ModelInfo[];
  default_model: string;
}

export const systemApi = {
  /** 获取系统状态 */
  async status(): Promise<SystemStatus> {
    const res = await client.get('/system/status');
    return extractData(res);
  },

  /** 获取可用模型列表 */
  async listModels(): Promise<ModelsResponse> {
    const res = await client.get('/system/models');
    return extractData(res);
  },
};

export default systemApi;
