import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock API before importing store
vi.mock('../api', () => ({
  kbApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
  documentApi: {
    list: vi.fn(),
    upload: vi.fn(),
    delete: vi.fn(),
    reparse: vi.fn(),
    getProgress: vi.fn(),
  },
}));

import { useKBStore } from '../store/kb';
import { kbApi, documentApi } from '../api';

describe('kbStore', () => {
  beforeEach(() => {
    useKBStore.setState({
      knowledgeBases: [],
      documents: {},
      loading: false,
      loadingDocs: {},
      error: null,
    });
    vi.clearAllMocks();
  });

  describe('fetchKBs', () => {
    it('should fetch and set knowledge bases', async () => {
      const mockKBs = [
        { id: 1, name: 'KB1', description: 'desc1', owner_id: 1, doc_count: 5, chunk_count: 100, collaborators: null, created_at: '', updated_at: '' },
        { id: 2, name: 'KB2', description: 'desc2', owner_id: 1, doc_count: 3, chunk_count: 50, collaborators: null, created_at: '', updated_at: '' },
      ];
      vi.mocked(kbApi.list).mockResolvedValue({ items: mockKBs, total: 2, page: 1, page_size: 100 });

      await useKBStore.getState().fetchKBs();

      const state = useKBStore.getState();
      expect(state.knowledgeBases).toEqual(mockKBs);
      expect(state.loading).toBe(false);
    });

    it('should set error on failure', async () => {
      vi.mocked(kbApi.list).mockRejectedValue(new Error('Network error'));

      await useKBStore.getState().fetchKBs();

      expect(useKBStore.getState().error).toBe('Network error');
      expect(useKBStore.getState().loading).toBe(false);
    });
  });

  describe('createKB', () => {
    it('should create a knowledge base and prepend to list', async () => {
      const newKB = { id: 3, name: 'New KB', description: 'new', owner_id: 1, doc_count: 0, chunk_count: 0, collaborators: null, created_at: '', updated_at: '' };
      vi.mocked(kbApi.create).mockResolvedValue(newKB);

      const result = await useKBStore.getState().createKB('New KB', 'new');

      expect(result).toEqual(newKB);
      expect(useKBStore.getState().knowledgeBases).toEqual([newKB]);
    });
  });

  describe('updateKB', () => {
    it('should update a knowledge base in the list', async () => {
      const existingKB = { id: 1, name: 'Old', description: 'old', owner_id: 1, doc_count: 0, chunk_count: 0, collaborators: null, created_at: '', updated_at: '' };
      const updatedKB = { id: 1, name: 'Updated', description: 'new desc', owner_id: 1, doc_count: 0, chunk_count: 0, collaborators: null, created_at: '', updated_at: '' };
      useKBStore.setState({ knowledgeBases: [existingKB] });
      vi.mocked(kbApi.update).mockResolvedValue(updatedKB);

      const result = await useKBStore.getState().updateKB(1, 'Updated', 'new desc');

      expect(result).toEqual(updatedKB);
      expect(useKBStore.getState().knowledgeBases[0].name).toBe('Updated');
    });
  });

  describe('deleteKB', () => {
    it('should delete a knowledge base from the list', async () => {
      const kb1 = { id: 1, name: 'KB1', description: '', owner_id: 1, doc_count: 0, chunk_count: 0, collaborators: null, created_at: '', updated_at: '' };
      const kb2 = { id: 2, name: 'KB2', description: '', owner_id: 1, doc_count: 0, chunk_count: 0, collaborators: null, created_at: '', updated_at: '' };
      useKBStore.setState({ knowledgeBases: [kb1, kb2] });

      await useKBStore.getState().deleteKB(1);

      expect(kbApi.delete).toHaveBeenCalledWith(1);
      expect(useKBStore.getState().knowledgeBases).toHaveLength(1);
      expect(useKBStore.getState().knowledgeBases[0].id).toBe(2);
    });
  });

  describe('fetchDocuments', () => {
    it('should fetch and set documents for a kb', async () => {
      const mockDocs = [
        { id: 1, kb_id: 1, uploader_id: 1, filename: 'doc1.pdf', file_path: '', file_type: 'pdf', file_size: 1024, file_hash: '', status: 'done' as const, chunk_count: 10, error_message: null, created_at: '', updated_at: '' },
      ];
      vi.mocked(documentApi.list).mockResolvedValue({ items: mockDocs, total: 1, page: 1, page_size: 200 } as any);

      await useKBStore.getState().fetchDocuments(1);

      expect(useKBStore.getState().documents[1]).toEqual(mockDocs);
    });
  });

  describe('deleteDocument', () => {
    it('should delete a document from the store', async () => {
      const doc = { id: 1, kb_id: 1, uploader_id: 1, filename: 'doc1.pdf', file_path: '', file_type: 'pdf', file_size: 1024, file_hash: '', status: 'done' as const, chunk_count: 10, error_message: null, created_at: '', updated_at: '' };
      useKBStore.setState({ documents: { 1: [doc] } });

      await useKBStore.getState().deleteDocument(1, 1);

      expect(documentApi.delete).toHaveBeenCalledWith(1);
      expect(useKBStore.getState().documents[1]).toHaveLength(0);
    });
  });

  describe('reparseDocument', () => {
    it('should call reparse API and refresh documents', async () => {
      const doc = { id: 1, kb_id: 1, uploader_id: 1, filename: 'doc1.pdf', file_path: '', file_type: 'pdf', file_size: 1024, file_hash: '', status: 'done' as const, chunk_count: 10, error_message: null, created_at: '', updated_at: '' };
      useKBStore.setState({ documents: { 1: [doc] } });
      vi.mocked(documentApi.reparse).mockResolvedValue({ document_id: 1, task_id: 'task-1' });
      vi.mocked(documentApi.list).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 } as any);

      await useKBStore.getState().reparseDocument(1, 1);

      expect(documentApi.reparse).toHaveBeenCalledWith(1, undefined);
    });
  });
});