import client, { extractData } from './client';

export interface EvaluationRunItem {
  id: number;
  knowledge_base_id: number;
  status: string;
  metrics: EvaluationMetrics | null;
  total_questions: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  error_message: string | null;
}

export interface EvaluationMetrics {
  faithfulness: number;
  answer_relevancy: number;
  context_precision: number;
  context_recall: number;
}

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

const evaluationApi = {
  /** Trigger a new evaluation run */
  triggerEvaluation: async (kbId: number, numQuestions: number = 50) => {
    const resp = await client.post('/evaluation/runs', null, {
      params: { kb_id: kbId, num_questions: numQuestions },
    });
    return extractData(resp);
  },

  /** List evaluation runs */
  listRuns: async (params?: {
    kb_id?: number;
    page?: number;
    page_size?: number;
  }) => {
    const resp = await client.get('/evaluation/runs', { params });
    return extractData<PaginatedData<EvaluationRunItem>>(resp);
  },

  /** Get single evaluation run */
  getRun: async (runId: number) => {
    const resp = await client.get(`/evaluation/runs/${runId}`);
    return extractData<EvaluationRunItem>(resp);
  },

  /** Get per-question results */
  getResults: async (runId: number, page?: number, pageSize?: number) => {
    const resp = await client.get(`/evaluation/runs/${runId}/results`, {
      params: { page, page_size: pageSize },
    });
    return extractData<PaginatedData<EvaluationResultItem>>(resp);
  },

  /** Delete evaluation run */
  deleteRun: async (runId: number) => {
    const resp = await client.delete(`/evaluation/runs/${runId}`);
    return extractData(resp);
  },
};

export default evaluationApi;