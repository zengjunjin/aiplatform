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
  referenced_chunks: Reference[] | null;
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

export interface SSEEvent {
  event: 'searching' | 'delta' | 'done' | 'error' | 'model' | 'cancelled' | 'warn';
  chunks_found?: number;
  content?: string;
  message_id?: number;
  references?: Reference[];
  message?: string;
  model_name?: string;
  display_name?: string;
  fallback?: boolean;
}

export interface ApiResponse<T = any> {
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

export interface Message {
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

export interface MessageWithRefs {
  id?: number;
  role: 'user' | 'assistant';
  content: string;
  references?: Reference[];
  isStreaming?: boolean;
  created_at?: string;
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
  rating: number;
  comment: string | null;
  feedback_type: FeedbackType;
  created_at: string;
}

export type FeedbackType = 'not_accurate' | 'incomplete' | 'hallucination' | 'irrelevant' | 'too_verbose' | 'too_brief' | 'other';

export interface ModelInfo {
  name: string;
  display_name: string;
  status: string;
}
