import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock the axios client - use vi.hoisted for hoisted mock compatibility
const { mockGet, mockPost, mockPut, mockDelete } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPut: vi.fn(),
  mockDelete: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  default: {
    get: mockGet,
    post: mockPost,
    put: mockPut,
    delete: mockDelete,
  },
  extractData: (res: any) => res.data.data,
  API_BASE: '/api/v1',
}));

// Mock the store for streamChat
vi.mock('../../store/auth', () => ({
  useAuthStore: {
    getState: () => ({ token: 'test-token' }),
  },
}));

import { chatApi, feedbackApi } from '../../api/chat';

describe('chatApi', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('listSessions', () => {
    it('should call GET /chat/sessions', async () => {
      const mockResponse = {
        data: {
          data: { items: [], total: 0, page: 1, page_size: 20 },
        },
      };
      mockGet.mockResolvedValue(mockResponse);

      const result = await chatApi.listSessions();

      expect(mockGet).toHaveBeenCalledWith('/chat/sessions', {
        params: { page: 1, page_size: 20 },
      });
      expect(result.items).toEqual([]);
    });
  });

  describe('createSession', () => {
    it('should call POST /chat/sessions', async () => {
      const newSession = { id: 1, user_id: 1, kb_id: 1, title: 'New', created_at: '', updated_at: '' };
      const mockResponse = { data: { data: newSession } };
      mockPost.mockResolvedValue(mockResponse);

      const result = await chatApi.createSession({ kb_id: 1, title: 'New' });

      expect(mockPost).toHaveBeenCalledWith('/chat/sessions', { kb_id: 1, title: 'New' });
      expect(result).toEqual(newSession);
    });
  });

  describe('updateSession', () => {
    it('should call PUT /chat/sessions/:id', async () => {
      const updated = { id: 1, user_id: 1, kb_id: null, title: 'Updated', created_at: '', updated_at: '' };
      const mockResponse = { data: { data: updated } };
      mockPut.mockResolvedValue(mockResponse);

      const result = await chatApi.updateSession(1, { title: 'Updated' });

      expect(mockPut).toHaveBeenCalledWith('/chat/sessions/1', { title: 'Updated' });
      expect(result).toEqual(updated);
    });
  });

  describe('deleteSession', () => {
    it('should call DELETE /chat/sessions/:id', async () => {
      mockDelete.mockResolvedValue({ data: {} });

      await chatApi.deleteSession(1);

      expect(mockDelete).toHaveBeenCalledWith('/chat/sessions/1');
    });
  });

  describe('getSession', () => {
    it('should call GET /chat/sessions/:id', async () => {
      const mockResponse = {
        data: {
          data: {
            session: { id: 1, user_id: 1, kb_id: null, title: 'S1', created_at: '', updated_at: '' },
            messages: [],
          },
        },
      };
      mockGet.mockResolvedValue(mockResponse);

      const result = await chatApi.getSession(1);

      expect(mockGet).toHaveBeenCalledWith('/chat/sessions/1');
      expect(result.session).toBeDefined();
      expect(result.messages).toEqual([]);
    });
  });

  describe('getMessages', () => {
    it('should call GET /chat/sessions/:id/messages', async () => {
      const mockResponse = { data: { data: [] } };
      mockGet.mockResolvedValue(mockResponse);

      const result = await chatApi.getMessages(1, 1, 50);

      expect(mockGet).toHaveBeenCalledWith('/chat/sessions/1/messages', {
        params: { page: 1, page_size: 50 },
      });
      expect(result).toEqual([]);
    });
  });
});

describe('feedbackApi', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('submitFeedback', () => {
    it('should call POST /chat/messages/:id/feedback', async () => {
      const mockResponse = {
        data: { data: { id: 1, message_id: 100, user_id: 1, rating: 1, comment: null, feedback_type: null, created_at: '' } },
      };
      mockPost.mockResolvedValue(mockResponse);

      const result = await feedbackApi.submitFeedback(100, { rating: 1 });

      expect(mockPost).toHaveBeenCalledWith('/chat/messages/100/feedback', { rating: 1 });
      expect(result.rating).toBe(1);
    });
  });

  describe('getFeedback', () => {
    it('should call GET /chat/messages/:id/feedback', async () => {
      const mockResponse = {
        data: { data: { id: 1, message_id: 100, user_id: 1, rating: 1, comment: 'Good', feedback_type: null, created_at: '' } },
      };
      mockGet.mockResolvedValue(mockResponse);

      const result = await feedbackApi.getFeedback(100);

      expect(mockGet).toHaveBeenCalledWith('/chat/messages/100/feedback');
      expect(result).toBeDefined();
    });
  });

  describe('getStats', () => {
    it('should call GET /chat/feedback/stats', async () => {
      const mockResponse = {
        data: { data: { total_feedback: 10, positive_rate: 0.8, negative_rate: 0.2, by_type: {} } },
      };
      mockGet.mockResolvedValue(mockResponse);

      const result = await feedbackApi.getStats();

      expect(mockGet).toHaveBeenCalledWith('/chat/feedback/stats', { params: {} });
      expect(result.total_feedback).toBe(10);
    });
  });
});