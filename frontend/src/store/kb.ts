import { create } from 'zustand';
import { kbApi, documentApi } from '../api';
import type { KnowledgeBase, Document, DocumentProgress } from '../types';

interface KBState {
  knowledgeBases: KnowledgeBase[];
  documents: Record<number, Document[]>;
  docTotal: Record<number, number>;
  loading: boolean;
  loadingDocs: Record<number, boolean>;
  error: string | null;
  // Task 49: 轮询进度连续失败达上限后置 true, 供 UI 显示"进度获取失败, 点击重试"
  pollError: boolean;
  fetchKBs: (signal?: AbortSignal) => Promise<void>;
  createKB: (name: string, description: string) => Promise<KnowledgeBase>;
  updateKB: (id: number, name: string, description: string) => Promise<KnowledgeBase>;
  deleteKB: (id: number) => Promise<void>;
  fetchDocuments: (kbId: number, page?: number, pageSize?: number, signal?: AbortSignal) => void;
  uploadDocument: (kbId: number, file: File, onProgress?: (progress: number) => void) => Promise<void>;
  deleteDocument: (kbId: number, docId: number) => Promise<void>;
  reparseDocument: (kbId: number, docId: number, force?: boolean) => Promise<void>;
  getProgress: (docId: number, signal?: AbortSignal) => Promise<DocumentProgress>;
  pollProgress: (docId: number, onUpdate: (p: DocumentProgress) => void, signal?: AbortSignal) => () => void;
}

export const useKBStore = create<KBState>((set, get) => ({
  knowledgeBases: [],
  documents: {},
  docTotal: {},
  loading: false,
  loadingDocs: {},
  error: null,
  pollError: false,

  fetchKBs: async (signal?: AbortSignal) => {
    set({ loading: true, error: null });
    try {
      const data = await kbApi.list(1, 100, signal);
      set({ knowledgeBases: data.items || [] });
    } catch (e: unknown) {
      // 组件卸载 abort 后的 CanceledError 静默处理，不写入 error 状态
      if (e instanceof Error && e.name === 'CanceledError') return;
      set({ error: e instanceof Error ? e.message : String(e) });
    } finally {
      set({ loading: false });
    }
  },

  createKB: async (name, description) => {
    const kb = await kbApi.create({ name, description });
    set((state) => ({ knowledgeBases: [kb, ...state.knowledgeBases] }));
    return kb;
  },

  updateKB: async (id, name, description) => {
    const kb = await kbApi.update(id, { name, description });
    set((state) => ({
      knowledgeBases: state.knowledgeBases.map((k) => (k.id === id ? kb : k)),
    }));
    return kb;
  },

  deleteKB: async (id) => {
    await kbApi.delete(id);
    set((state) => ({
      knowledgeBases: state.knowledgeBases.filter((kb) => kb.id !== id),
      documents: { ...state.documents, [id]: [] },
    }));
  },

  fetchDocuments: async (kbId, page = 1, pageSize = 20, signal?: AbortSignal) => {
    set((state) => ({ loadingDocs: { ...state.loadingDocs, [kbId]: true } }));
    try {
      const data = await documentApi.list(kbId, page, pageSize, signal);
      set((state) => ({
        documents: { ...state.documents, [kbId]: data.items || [] },
        docTotal: { ...state.docTotal, [kbId]: data.total || 0 },
      }));
    } catch (e: unknown) {
      // 组件卸载 abort 后的 CanceledError 静默处理
      if (e instanceof Error && e.name === 'CanceledError') return;
      throw e;
    } finally {
      set((state) => ({ loadingDocs: { ...state.loadingDocs, [kbId]: false } }));
    }
  },

  uploadDocument: async (kbId, file, onProgress) => {
    await documentApi.upload(kbId, file, (loaded, total) => {
      if (onProgress && total > 0) {
        onProgress(Math.round((loaded / total) * 100));
      }
    });
    await get().fetchDocuments(kbId);
  },

  deleteDocument: async (kbId, docId) => {
    await documentApi.delete(docId);
    set((state) => ({
      documents: {
        ...state.documents,
        [kbId]: (state.documents[kbId] || []).filter((d) => d.id !== docId),
      },
    }));
  },

  reparseDocument: async (kbId, docId, force) => {
    await documentApi.reparse(docId, force);
    await get().fetchDocuments(kbId);
  },

  getProgress: async (docId, signal?: AbortSignal) => {
    return documentApi.getProgress(docId, ...(signal ? [signal] : []));
  },

  pollProgress: (docId, onUpdate, signal?: AbortSignal) => {
    let stopped = false;
    let timer: number;
    let errorCount = 0;
    const MAX_ERRORS = 5;

    const poll = async () => {
      if (stopped) return;
      try {
        const progress = await get().getProgress(docId, ...(signal ? [signal] : []));
        errorCount = 0;
        onUpdate(progress);
        if (progress.status === 'done' || progress.status === 'failed') {
          return;
        }
        // 根据状态调整轮询间隔
        const interval = progress.status === 'embedding' ? 1000 : 2000;
        timer = window.setTimeout(poll, interval);
      } catch (e) {
        // 组件卸载 abort 后的 CanceledError 静默停止轮询
        if (e instanceof Error && e.name === 'CanceledError') return;
        errorCount++;
        console.error('poll progress error:', e);
        if (errorCount >= MAX_ERRORS) {
          console.error('poll progress: max errors reached, stopping');
          // Task 49: 上报轮询失败状态, 供 UI 显示"进度获取失败, 点击重试"
          set({ pollError: true });
          return;
        }
        timer = window.setTimeout(poll, 2000);
      }
    };

    poll();

    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  },
}));
