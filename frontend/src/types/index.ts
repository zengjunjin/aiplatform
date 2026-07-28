export interface User {
  id: number;
  username: string;
  email: string;
  role: 'user' | 'admin';
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeBase {
  id: number;
  name: string;
  description: string;
  owner_id: number;
  doc_count: number;
  chunk_count: number;
  collaborators: CollaboratorEntry[] | null;
  created_at: string;
  updated_at: string;
}

export interface CollaboratorEntry {
  user_id: number;
  permission: string;
}

export interface CollaboratorInfo {
  user_id: number;
  username: string;
  permission: string;
}

export interface Document {
  id: number;
  kb_id: number;
  uploader_id: number;
  filename: string;
  file_path: string;
  file_type: string;
  file_size: number;
  file_hash: string;
  status: 'pending' | 'parsing' | 'chunking' | 'embedding' | 'done' | 'failed';
  chunk_count: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentProgress {
  status: string;
  progress: number;
  chunk_count: number;
  error_message: string | null;
}

export interface ChatSession {
  id: number;
  user_id: number;
  kb_id: number | null;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: number;
  session_id: number;
  role: 'user' | 'assistant';
  content: string;
  references: Reference[] | null;
  token_input: number | null;
  token_output: number | null;
  latency_ms: number | null;
  created_at: string;
}

export interface Reference {
  chunk_id: string | number;
  doc_id: number;
  filename: string;
  page: number | null;
  snippet: string;
  score: number;
}

export type SSEEvent =
  | { event: 'searching'; chunks_found?: number }
  | { event: 'delta'; content?: string }
  | { event: 'done'; message_id?: number; references?: Reference[] }
  | { event: 'model'; model_name?: string; display_name?: string; fallback?: boolean }
  | { event: 'error' | 'cancelled' | 'warn'; message?: string };

export interface ApiResponse<T = unknown> {
  code: number;
  message: string;
  data: T;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// Task 55: Message 继承 ChatMessage, 字段名已与后端 MessageOut.references 统一
export interface Message extends ChatMessage {}

export interface MessageWithRefs {
  id?: number;
  role: 'user' | 'assistant';
  content: string;
  references?: Reference[];
  isStreaming?: boolean;
  created_at?: string;
  /** Task 39: token 消耗与响应时长, 仅 assistant 消息有效; 历史消息从后端读取, 流式消息在 done 事件后写入 */
  token_input?: number | null;
  token_output?: number | null;
  latency_ms?: number | null;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user?: User;
}

export interface EvaluationRun {
  id: number;
  knowledge_base_id: number;
  status: string;
  metrics: EvaluationMetrics | null;
  total_questions: number;
  started_at: string | null;
  completed_at: string | null;
  // 以下字段为后端实际返回, 保留原始字段名供 EvaluationPage 等使用方读取
  created_at: string | null;
  error_message: string | null;
}

export interface EvaluationMetrics {
  faithfulness: number;
  answer_relevancy: number;
  context_precision: number;
  context_recall: number;
}

export interface MessageFeedback {
  id: number;
  message_id: number;
  user_id: number;
  rating: number;
  comment: string | null;
  feedback_type: FeedbackType | null;
  created_at: string;
}

export type FeedbackType = 'not_accurate' | 'incomplete' | 'hallucination' | 'irrelevant' | 'too_verbose' | 'too_brief' | 'other';

export interface ModelInfo {
  name: string;
  display_name: string;
  status: string;
}
