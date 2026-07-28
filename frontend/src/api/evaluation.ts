import client, { extractData } from './client';
import { getWithOptionalSignal } from './helpers';
import type { EvaluationRun, EvaluationMetrics } from '../types';

// 兼容旧名称: EvaluationRunItem 是 EvaluationRun 的别名
// (EvaluationPage.tsx 仍引用 EvaluationRunItem, 通过 alias 避免破坏其 import 路径)
export type { EvaluationRun as EvaluationRunItem, EvaluationMetrics };

export interface EvaluationResultItem {
  id: number;
  question: string;
  ground_truth: string;
  generated_answer: string;
  contexts: string[];
  faithfulness: number | null;
  answer_relevancy: number | null;
  context_precision: number | null;
  context_recall: number | null;
}

export interface PaginatedData<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface TriggerEvaluationResponse {
  run_id: number;
  status: string;
  task_id: string;
  message: string;
}

const evaluationApi = {
  /** Trigger a new evaluation run */
  triggerEvaluation: async (kbId: number, numQuestions: number = 50): Promise<TriggerEvaluationResponse> => {
    const resp = await client.post('/evaluation/runs', null, {
      params: { kb_id: kbId, num_questions: numQuestions },
    });
    return extractData<TriggerEvaluationResponse>(resp);
  },

  /** List evaluation runs */
  listRuns: async (params?: {
    kb_id?: number;
    page?: number;
    page_size?: number;
  }, signal?: AbortSignal): Promise<PaginatedData<EvaluationRun>> => {
    // 保持原行为：即使 params 为 undefined 也传 config 对象（测试期望 { params: undefined }）
    const resp = await client.get('/evaluation/runs', {
      params,
      ...(signal ? { signal } : {}),
    });
    return extractData<PaginatedData<EvaluationRun>>(resp);
  },

  /** Get single evaluation run */
  getRun: async (runId: number): Promise<EvaluationRun> => {
    const resp = await client.get(`/evaluation/runs/${runId}`);
    return extractData<EvaluationRun>(resp);
  },

  /** Get per-question results */
  getResults: async (runId: number, page?: number, pageSize?: number, signal?: AbortSignal): Promise<PaginatedData<EvaluationResultItem>> => {
    return getWithOptionalSignal<PaginatedData<EvaluationResultItem>>(
      `/evaluation/runs/${runId}/results`,
      { page, page_size: pageSize },
      signal,
    );
  },

  /** Delete evaluation run */
  deleteRun: async (runId: number): Promise<void> => {
    await client.delete(`/evaluation/runs/${runId}`);
  },
};

export default evaluationApi;