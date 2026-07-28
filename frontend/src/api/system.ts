import { getWithOptionalSignal } from './helpers';

export interface SystemStatus {
  postgresql: string;
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

/**
 * 后端 /system/status 端点返回的扩展字段。
 * 现有 SystemStatus 接口只覆盖核心 5 个组件状态，此处补充附加信息字段。
 */
export interface ExtendedSystemStatus extends SystemStatus {
  ollama_models?: string[];
  qdrant_collections?: number;
  celery_workers?: string[];
}

export const systemApi = {
  /** 获取系统状态 */
  async status(signal?: AbortSignal): Promise<SystemStatus> {
    return getWithOptionalSignal<SystemStatus>('/system/status', undefined, signal);
  },

  /** 获取可用模型列表 */
  async listModels(signal?: AbortSignal): Promise<ModelsResponse> {
    return getWithOptionalSignal<ModelsResponse>('/system/models', undefined, signal);
  },
};

export default systemApi;
