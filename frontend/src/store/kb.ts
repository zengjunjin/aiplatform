import { create } from 'zustand';
import { kbApi, documentApi } from '../api';
import type { KnowledgeBase, Document, DocumentProgress } from '../types';

interface KBState {
  knowledgeBases: KnowledgeBase[];
  documents: Record<number, Document[]>;
  loading: boolean;
  loadingDocs: Record<number, boolean>;
  error: string | null;
  fetchKBs: () => Promise<void>;
  createKB: (name: string, description: string) => Promise<KnowledgeBase>;
  updateKB: (id: number, name: string, description: string) => Promise<KnowledgeBase>;
  deleteKB: (id: number) => Promise<void>;
  fetchDocuments: (kbId: number) => Promise<void>;
  uploadDocument: (kbId: number, file: File, onProgress?: (progress: number) => void) => Promise<void>;
  deleteDocument: (kbId: number, docId: number) => Promise<void>;
  reparseDocument: (kbId: number, docId: number) => Promise<void>;
  getProgress: (docId: number) => Promise<DocumentProgress>;
  pollProgress: (docId: number, onUpdate: (p: DocumentProgress) => void) => () => void;
}

export const useKBStore = create<KBState>((set, get) => ({
  knowledgeBases: [],
  documents: {},
  loading: false,
  loadingDocs: {},
  error: null,

  fetchKBs: async () => {
    set({ loading: true, error: null });
    try {
      const data = await kbApi.list(1, 100);
      set({ knowledgeBases: data.items || [] });
    } catch (e: any) {
      set({ error: e.message });
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

  fetchDocuments: async (kbId) => {
    set((state) => ({ loadingDocs: { ...state.loadingDocs, [kbId]: true } }));
    try {
      const data = await documentApi.list(kbId, 1, 200);
      set((state) => ({
        documents: { ...state.documents, [kbId]: data.items || [] },
      }));
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

  reparseDocument: async (kbId, docId) => {
    await documentApi.reparse(docId);
    await get().fetchDocuments(kbId);
  },

  getProgress: async (docId) => {
    return documentApi.getProgress(docId);
  },

  pollProgress: (docId, onUpdate) => {
    let stopped = false;
    let timer: number;

    const poll = async () => {
      if (stopped) return;
      try {
        const progress = await get().getProgress(docId);
        onUpdate(progress);
        if (progress.status === 'done' || progress.status === 'failed') {
          return;
        }
      } catch (e) {
        console.error('poll progress error:', e);
      }
      timer = window.setTimeout(poll, 2000);
    };

    poll();

    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  },
}));
