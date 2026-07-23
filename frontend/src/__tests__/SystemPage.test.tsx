import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SystemPage from '../pages/SystemPage';

// Mock react-i18next - t 函数引用必须稳定
const stableT = (key: string) => key;
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: stableT }),
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

// Mock i18n
vi.mock('../i18n', () => ({
  globalT: (key: string) => key,
}));

// Mock API
const mockStatus = vi.fn();
vi.mock('../api', () => ({
  systemApi: {
    status: (...args: any[]) => mockStatus(...args),
  },
}));

// Mock antd App
vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  return {
    ...(actual as any),
    App: Object.assign((actual as any).App, {
      useApp: () => ({ message: { success: vi.fn(), error: vi.fn() } }),
    }),
  };
});

describe('SystemPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should render page title', () => {
    mockStatus.mockReturnValue(new Promise(() => {})); // 永不 resolve，保持 loading
    render(
      <MemoryRouter>
        <SystemPage />
      </MemoryRouter>
    );
    expect(screen.getByText('system.title')).toBeInTheDocument();
  });

  it('should show Skeleton in loading state', () => {
    mockStatus.mockReturnValue(new Promise(() => {})); // 永不 resolve
    const { container } = render(
      <MemoryRouter>
        <SystemPage />
      </MemoryRouter>
    );
    // loading 时仍渲染标题，Skeleton 会被 antd 渲染为骨架节点
    expect(screen.getByText('system.title')).toBeInTheDocument();
    // antd Skeleton 渲染为包含 .ant-skeleton 的元素
    expect(container.querySelector('.ant-skeleton')).toBeInTheDocument();
  });

  it('should show Result error when status call fails', async () => {
    mockStatus.mockRejectedValue(new Error('Network error'));
    const { container } = render(
      <MemoryRouter>
        <SystemPage />
      </MemoryRouter>
    );
    await waitFor(() => {
      // Result status="error" 渲染为 ant-result-error
      expect(container.querySelector('.ant-result-error')).toBeInTheDocument();
    });
    expect(screen.getByText('system.loadFailed')).toBeInTheDocument();
  });

  it('should render component cards when status loaded successfully', async () => {
    mockStatus.mockResolvedValue({
      status: 'ok',
      postgresql: 'up',
      redis: 'up',
      ollama: 'up',
      qdrant: 'up',
      celery: 'up',
      ollama_models: ['llama3:8b', 'qwen2:7b'],
      qdrant_collections: 5,
      celery_workers: ['celery@worker1', 'celery@worker2'],
    });

    render(
      <MemoryRouter>
        <SystemPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      // 组件卡片标题
      expect(screen.getByText('system.components.postgresql')).toBeInTheDocument();
      expect(screen.getByText('system.components.redis')).toBeInTheDocument();
      expect(screen.getByText('system.components.ollama')).toBeInTheDocument();
      expect(screen.getByText('system.components.qdrant')).toBeInTheDocument();
      expect(screen.getByText('system.components.celery')).toBeInTheDocument();
    });

    // 健康状态标签（5 个组件都健康，应有 5 个 "system.status.healthy" 文本）
    const healthyTags = screen.getAllByText('system.status.healthy');
    expect(healthyTags.length).toBeGreaterThanOrEqual(5);
  });

  it('should render ollama models, qdrant collections, and celery workers', async () => {
    mockStatus.mockResolvedValue({
      status: 'ok',
      postgresql: 'up',
      redis: 'up',
      ollama: 'up',
      qdrant: 'up',
      celery: 'up',
      ollama_models: ['llama3:8b', 'qwen2:7b'],
      qdrant_collections: 5,
      celery_workers: ['celery@worker1', 'celery@worker2'],
    });

    render(
      <MemoryRouter>
        <SystemPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      // Ollama 模型列表
      expect(screen.getByText('llama3:8b')).toBeInTheDocument();
      expect(screen.getByText('qwen2:7b')).toBeInTheDocument();
      // Celery workers
      expect(screen.getByText('celery@worker1')).toBeInTheDocument();
      expect(screen.getByText('celery@worker2')).toBeInTheDocument();
    });

    // 附加信息卡片标题
    expect(screen.getByText('system.ollamaModels')).toBeInTheDocument();
    expect(screen.getByText('system.qdrantCollections')).toBeInTheDocument();
    expect(screen.getByText('system.celeryWorkers')).toBeInTheDocument();
  });

  it('should show unhealthy tag for down components', async () => {
    mockStatus.mockResolvedValue({
      status: 'degraded',
      postgresql: 'up',
      redis: 'down',
      ollama: 'down: HTTP 500',
      qdrant: 'up',
      celery: 'no_active_workers',
      ollama_models: [],
      qdrant_collections: 0,
      celery_workers: [],
    });

    render(
      <MemoryRouter>
        <SystemPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      // unhealthy 标签应至少出现 3 次（redis、ollama、celery）
      const unhealthyTags = screen.getAllByText('system.status.unhealthy');
      expect(unhealthyTags.length).toBe(3);
    });
  });

  it('should show empty state when ollama_models is empty', async () => {
    mockStatus.mockResolvedValue({
      status: 'ok',
      postgresql: 'up',
      redis: 'up',
      ollama: 'up',
      qdrant: 'up',
      celery: 'up',
      ollama_models: [],
      qdrant_collections: 0,
      celery_workers: [],
    });

    render(
      <MemoryRouter>
        <SystemPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      // 两个空状态：ollama_models 为空、celery_workers 为空
      const emptyTexts = screen.getAllByText('common.noData');
      expect(emptyTexts.length).toBe(2);
    });
  });

  it('should call systemApi.status on mount', async () => {
    mockStatus.mockResolvedValue({
      status: 'ok',
      postgresql: 'up',
      redis: 'up',
      ollama: 'up',
      qdrant: 'up',
      celery: 'up',
    });

    render(
      <MemoryRouter>
        <SystemPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockStatus).toHaveBeenCalled();
    });
  });
});
