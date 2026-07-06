import client, { extractData } from './client';

export interface SystemStatus {
  status: string;
  postgres: string;
  redis: string;
  ollama: string;
  qdrant: string;
  celery: string;
}

export const systemApi = {
  /** 获取系统状态 */
  async status(): Promise<SystemStatus> {
    const res = await client.get('/system/status');
    return extractData(res);
  },
};

export default systemApi;
