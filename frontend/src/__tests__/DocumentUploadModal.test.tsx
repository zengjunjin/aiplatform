import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import DocumentUploadModal from '../components/DocumentUploadModal';

// Mock react-i18next — 稳定 t 引用
const { mockT } = vi.hoisted(() => ({
  mockT: (key: string, _params?: any) => key,
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT }),
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

// Mock antd App.useApp — 稳定 message 引用
const { mockMessage } = vi.hoisted(() => ({
  mockMessage: {
    success: vi.fn(),
    error: vi.fn(),
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

// Mock documentApi.upload
const { uploadMock } = vi.hoisted(() => ({
  uploadMock: vi.fn(),
}));

vi.mock('../api', () => ({
  documentApi: { upload: uploadMock },
}));

vi.mock('../utils/errorReporter', () => ({
  getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));

describe('DocumentUploadModal', () => {
  beforeEach(() => {
    uploadMock.mockReset();
    mockMessage.success.mockReset();
    mockMessage.error.mockReset();
  });

  it('renders upload dragger and title when open', () => {
    render(
      <DocumentUploadModal open kbId={1} onClose={() => {}} onUploaded={() => {}} />
    );
    expect(screen.getByText('kb.uploadModalTitle')).toBeInTheDocument();
    expect(screen.getByText('kb.uploadDragText')).toBeInTheDocument();
    expect(screen.getByText('kb.uploadDragHint')).toBeInTheDocument();
    // 文件输入存在
    expect(document.querySelector('input[type="file"]')).toBeTruthy();
  });

  it('updates progress bar via onUploadProgress callback', async () => {
    uploadMock.mockImplementation(
      (_kbId: number, _file: File, onProgress?: (l: number, t: number) => void) => {
        if (onProgress) onProgress(50, 100);
        return Promise.resolve({ document_id: 1, status: 'done', task_id: 't1' });
      }
    );
    render(
      <DocumentUploadModal open kbId={1} onClose={() => {}} onUploaded={() => {}} />
    );
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['content'], 'doc.pdf', { type: 'application/pdf' });
    fireEvent.change(input, { target: { files: [file] } });

    // 进度条应显示 50%
    await waitFor(() => {
      const progressText = document.querySelector('.ant-progress-text');
      expect(progressText?.textContent).toContain('50');
    });
    // 上传成功后显示成功消息
    await waitFor(() => {
      expect(mockMessage.success).toHaveBeenCalledWith('kb.uploadSuccess');
    });
  });

  it('shows error message and closes modal when upload fails', async () => {
    uploadMock.mockRejectedValue(new Error('Upload failed'));
    const onClose = vi.fn();
    render(
      <DocumentUploadModal open kbId={1} onClose={onClose} onUploaded={() => {}} />
    );
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['content'], 'doc.pdf', { type: 'application/pdf' });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(mockMessage.error).toHaveBeenCalledWith('Upload failed');
    });
    // 失败后也关闭 modal
    expect(onClose).toHaveBeenCalled();
  });

  it('restricts file types via accept attribute', () => {
    render(
      <DocumentUploadModal open kbId={1} onClose={() => {}} onUploaded={() => {}} />
    );
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    // 仅允许 pdf/docx/md/markdown/txt
    expect(input.accept).toBe('.pdf,.docx,.md,.markdown,.txt');
  });

  it('calls onUploaded and onClose after successful upload', async () => {
    uploadMock.mockResolvedValue({ document_id: 9, status: 'done', task_id: 't9' });
    const onClose = vi.fn();
    const onUploaded = vi.fn();
    render(
      <DocumentUploadModal open kbId={2} onClose={onClose} onUploaded={onUploaded} />
    );
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['content'], 'note.md', { type: 'text/markdown' });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
    expect(onUploaded).toHaveBeenCalled();
    expect(mockMessage.success).toHaveBeenCalledWith('kb.uploadSuccess');
  });

  it('passes kbId and file to upload API', async () => {
    uploadMock.mockResolvedValue({ document_id: 1, status: 'done', task_id: 't1' });
    render(
      <DocumentUploadModal open kbId={7} onClose={() => {}} onUploaded={() => {}} />
    );
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['data'], 'report.txt', { type: 'text/plain' });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(uploadMock).toHaveBeenCalledWith(7, file, expect.any(Function));
    });
  });
});
