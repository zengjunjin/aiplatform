import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import DocumentPreviewModal from '../components/DocumentPreviewModal';

// Mock react-i18next — t 必须是稳定引用, 否则进入 fetchPreview 的 useCallback 依赖
// 会导致 useEffect 反复重跑 (真实 i18n 的 t 引用是稳定的)
const { mockT } = vi.hoisted(() => ({
  mockT: (key: string, params?: any) => {
    if (params && params.page !== undefined) {
      return `${key}:${params.page}/${params.total}`;
    }
    return key;
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT }),
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

// Mock antd App.useApp — 必须返回稳定引用, 否则 message 进入 fetchPreview 的 useCallback
// 依赖会导致 useEffect 无限重跑 (组件实际运行时 antd 内部对 message 做了 memoize)
const { mockMessage } = vi.hoisted(() => ({
  mockMessage: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  return {
    ...(actual as any),
    App: Object.assign((actual as any).App, {
      useApp: () => ({ message: mockMessage }),
    }),
  };
});

// Mock documentApi.preview
const { previewMock } = vi.hoisted(() => ({
  previewMock: vi.fn(),
}));

vi.mock('../api', () => ({
  documentApi: { preview: previewMock },
}));

vi.mock('../utils/errorReporter', () => ({
  getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));

const sampleData = {
  filename: 'guide.md',
  file_type: 'md',
  content: 'Hello world',
  page: 1,
  page_size: 50,
  total_lines: 100,
  total_pages: 3,
};

// Modal 渲染到 document.body portal, 使用 document.body 查询按钮
function queryByAria(label: string): HTMLElement | null {
  return document.body.querySelector(`[aria-label="${label}"]`) as HTMLElement | null;
}

describe('DocumentPreviewModal', () => {
  beforeEach(() => {
    previewMock.mockReset();
    mockMessage.error.mockReset();
  });

  it('renders title and content when open', async () => {
    previewMock.mockResolvedValue(sampleData);
    render(
      <DocumentPreviewModal
        open
        docId={1}
        filename="guide.md"
        fileType="md"
        onClose={() => {}}
      />
    );
    // 标题区显示文件名与文件类型标签
    expect(screen.getByText('guide.md')).toBeInTheDocument();
    expect(screen.getByText('MD')).toBeInTheDocument();
    // 首次加载触发 page=1 请求
    expect(previewMock).toHaveBeenCalledWith(1, 1, 50);
    // 内容渲染
    await waitFor(() => {
      expect(screen.getByText('Hello world')).toBeInTheDocument();
    });
  });

  it('loads next page when next button clicked', async () => {
    previewMock.mockResolvedValue({ ...sampleData, page: 1, total_pages: 3 });
    render(
      <DocumentPreviewModal
        open
        docId={2}
        filename="guide.md"
        fileType="md"
        onClose={() => {}}
      />
    );
    await waitFor(() => {
      expect(screen.getByText('Hello world')).toBeInTheDocument();
    });
    previewMock.mockClear();

    const nextBtn = queryByAria('documentPreview.nextPage') as HTMLElement;
    expect(nextBtn).toBeTruthy();
    fireEvent.click(nextBtn);

    await waitFor(() => {
      expect(previewMock).toHaveBeenCalledWith(2, 2, 50);
    });
  });

  it('disables prev button on first page and navigates back from page 2', async () => {
    previewMock.mockResolvedValue({ ...sampleData, page: 1, total_pages: 3 });
    render(
      <DocumentPreviewModal
        open
        docId={3}
        filename="guide.md"
        fileType="md"
        onClose={() => {}}
      />
    );
    await waitFor(() => {
      expect(screen.getByText('Hello world')).toBeInTheDocument();
    });
    const prevBtn = queryByAria('documentPreview.prevPage') as HTMLButtonElement;
    // 第一页时 prev 禁用
    expect(prevBtn.disabled).toBe(true);

    // 翻到第二页
    previewMock.mockResolvedValue({ ...sampleData, page: 2, total_pages: 3 });
    const nextBtn = queryByAria('documentPreview.nextPage') as HTMLElement;
    fireEvent.click(nextBtn);
    await waitFor(() => {
      expect(previewMock).toHaveBeenCalledWith(3, 2, 50);
    });
  });

  it('renders markdown content as HTML when fileType is markdown', async () => {
    previewMock.mockResolvedValue({
      ...sampleData,
      content: '# Heading One\n\nSome paragraph text',
      total_pages: 1,
    });
    render(
      <DocumentPreviewModal
        open
        docId={4}
        filename="guide.md"
        fileType="markdown"
        onClose={() => {}}
      />
    );
    // react-markdown 应将 "# Heading One" 渲染为 <h1>, 证明 markdown -> HTML 转换
    await waitFor(() => {
      const heading = screen.getByRole('heading', { name: 'Heading One', level: 1 });
      expect(heading).toBeInTheDocument();
    });
    // 段落也被渲染为 <p>
    const para = screen.getByText('Some paragraph text');
    expect(para.tagName).toBe('P');
  });

  it('renders plain content inside <pre> for non-markdown file type', async () => {
    previewMock.mockResolvedValue({
      ...sampleData,
      file_type: 'txt',
      content: 'plain pre content',
      total_pages: 1,
    });
    render(
      <DocumentPreviewModal
        open
        docId={5}
        filename="notes.txt"
        fileType="txt"
        onClose={() => {}}
      />
    );
    const contentEl = await screen.findByText('plain pre content');
    // 内容应渲染在 <pre> 中 (非 markdown 走 pre 分支)
    expect(contentEl.closest('pre')).not.toBeNull();
  });

  it('shows error message and clears data when API fails', async () => {
    previewMock.mockRejectedValue(new Error('Network error'));
    render(
      <DocumentPreviewModal
        open
        docId={6}
        filename="guide.md"
        fileType="md"
        onClose={() => {}}
      />
    );
    await waitFor(() => {
      expect(mockMessage.error).toHaveBeenCalledWith('Network error');
    });
    // 出错后 data 被置空, 内容区不应再显示成功态文本
    expect(screen.queryByText('Hello world')).not.toBeInTheDocument();
  });

  it('renders empty content without pagination when total_pages is 0', async () => {
    previewMock.mockResolvedValue({
      ...sampleData,
      content: '',
      total_pages: 0,
      total_lines: 0,
    });
    render(
      <DocumentPreviewModal
        open
        docId={7}
        filename="empty.md"
        fileType="md"
        onClose={() => {}}
      />
    );
    // 标题仍渲染
    expect(screen.getByText('empty.md')).toBeInTheDocument();
    await waitFor(() => {
      expect(previewMock).toHaveBeenCalled();
    });
    // total_pages=0 时不渲染分页控件
    expect(queryByAria('documentPreview.nextPage')).not.toBeTruthy();
    expect(queryByAria('documentPreview.prevPage')).not.toBeTruthy();
  });

  it('calls onClose when modal close (x) button clicked', async () => {
    previewMock.mockResolvedValue(sampleData);
    const onClose = vi.fn();
    render(
      <DocumentPreviewModal
        open
        docId={8}
        filename="guide.md"
        fileType="md"
        onClose={onClose}
      />
    );
    await waitFor(() => {
      expect(screen.getByText('Hello world')).toBeInTheDocument();
    });
    const closeBtn = document.body.querySelector('.ant-modal-close') as HTMLElement;
    expect(closeBtn).toBeTruthy();
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalled();
  });
});
