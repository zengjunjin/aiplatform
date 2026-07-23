import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

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
      docTotal: {},
      loading: false,
      loadingDocs: {},
      error: null,
    });
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
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

    it('should pass force flag to reparse API', async () => {
      vi.mocked(documentApi.reparse).mockResolvedValue({ document_id: 1, task_id: 'task-1' });
      vi.mocked(documentApi.list).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 } as any);

      await useKBStore.getState().reparseDocument(1, 1, true);

      expect(documentApi.reparse).toHaveBeenCalledWith(1, true);
    });
  });

  describe('fetchKBs error handling', () => {
    it('should set error string for non-Error throw', async () => {
      vi.mocked(kbApi.list).mockRejectedValue('string error');

      await useKBStore.getState().fetchKBs();

      expect(useKBStore.getState().error).toBe('string error');
    });
  });

  describe('fetchDocuments', () => {
    it('should set loadingDocs flag during fetch', async () => {
      vi.mocked(documentApi.list).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 } as any);

      const promise = useKBStore.getState().fetchDocuments(1);
      // After starting, loadingDocs should be true
      expect(useKBStore.getState().loadingDocs[1]).toBe(true);

      await promise;
      expect(useKBStore.getState().loadingDocs[1]).toBe(false);
    });

    it('should handle null items in response', async () => {
      vi.mocked(documentApi.list).mockResolvedValue({ items: null as any, total: null as any, page: 1, page_size: 200 } as any);

      await useKBStore.getState().fetchDocuments(1);

      expect(useKBStore.getState().documents[1]).toEqual([]);
      expect(useKBStore.getState().docTotal[1]).toBe(0);
    });
  });

  describe('uploadDocument', () => {
    it('should call upload API with progress callback and refresh docs', async () => {
      const mockFile = new File(['content'], 'test.txt', { type: 'text/plain' });
      const onProgress = vi.fn();
      vi.mocked(documentApi.upload).mockImplementation(async (_kbId, _file, onProgressCb) => {
        onProgressCb?.(50, 100);
        return {} as any;
      });
      vi.mocked(documentApi.list).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 } as any);

      await useKBStore.getState().uploadDocument(1, mockFile, onProgress);

      expect(documentApi.upload).toHaveBeenCalledWith(1, mockFile, expect.any(Function));
      expect(onProgress).toHaveBeenCalledWith(50);
    });

    it('should not call onProgress when total is 0', async () => {
      const mockFile = new File(['content'], 'test.txt', { type: 'text/plain' });
      const onProgress = vi.fn();
      vi.mocked(documentApi.upload).mockImplementation(async (_kbId, _file, onProgressCb) => {
        onProgressCb?.(50, 0);
        return {} as any;
      });
      vi.mocked(documentApi.list).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 } as any);

      await useKBStore.getState().uploadDocument(1, mockFile, onProgress);

      expect(onProgress).not.toHaveBeenCalled();
    });
  });

  describe('getProgress', () => {
    it('should call documentApi.getProgress', async () => {
      const mockProgress = { document_id: 1, status: 'parsing', progress: 50, task_id: 'task-1' };
      vi.mocked(documentApi.getProgress).mockResolvedValue(mockProgress as any);

      const result = await useKBStore.getState().getProgress(1);

      expect(documentApi.getProgress).toHaveBeenCalledWith(1);
      expect(result).toEqual(mockProgress);
    });
  });

  describe('pollProgress', () => {
    it('should poll and stop on done status', async () => {
      vi.useFakeTimers();
      vi.mocked(documentApi.getProgress)
        .mockResolvedValueOnce({ document_id: 1, status: 'parsing', progress: 50, task_id: 't1' } as any)
        .mockResolvedValueOnce({ document_id: 1, status: 'done', progress: 100, task_id: 't1' } as any);

      const onUpdate = vi.fn();
      const stop = useKBStore.getState().pollProgress(1, onUpdate);

      // First poll resolves immediately (parsing)
      await vi.advanceTimersByTimeAsync(0);
      expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({ status: 'parsing' }));

      // Second poll after 2000ms (done)
      await vi.advanceTimersByTimeAsync(2000);
      expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({ status: 'done' }));

      stop();
    });

    it('should stop on failed status', async () => {
      vi.useFakeTimers();
      vi.mocked(documentApi.getProgress).mockResolvedValueOnce({
        document_id: 1,
        status: 'failed',
        progress: 0,
        task_id: 't1',
        error: 'parse error',
      } as any);

      const onUpdate = vi.fn();
      const stop = useKBStore.getState().pollProgress(1, onUpdate);

      await vi.advanceTimersByTimeAsync(0);
      expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({ status: 'failed' }));

      stop();
    });

    it('should return a stop function', () => {
      vi.useFakeTimers();
      vi.mocked(documentApi.getProgress).mockResolvedValue({ document_id: 1, status: 'parsing', progress: 0, task_id: 't1' } as any);

      const stop = useKBStore.getState().pollProgress(1, () => {});

      expect(typeof stop).toBe('function');
      stop();
    });
  });
});