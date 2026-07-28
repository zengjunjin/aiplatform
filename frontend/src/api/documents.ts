import client, { extractData } from './client';
import { getWithOptionalSignal } from './helpers';
import { globalT } from '../i18n';
import type { Document, DocumentProgress } from '../types';

export interface DocumentPreviewData {
  filename: string;
  file_type: string;
  content: string;
  page: number;
  page_size: number;
  total_lines: number;
  total_pages: number;
}

export const documentApi = {
  /** 获取文档列表 (kbId 省略时后端返回所有有权限的文档, 实现真正的服务端分页) */
  async list(kbId?: number, page = 1, pageSize = 20, signal?: AbortSignal): Promise<{ items: Document[]; total: number; page: number; page_size: number; total_pages: number }> {
    return getWithOptionalSignal<{ items: Document[]; total: number; page: number; page_size: number; total_pages: number }>(
      '/documents',
      {
        ...(kbId !== undefined ? { kb_id: kbId } : {}),
        page,
        page_size: pageSize,
      },
      signal,
    );
  },

  /** 获取文档详情 */
  async get(docId: number): Promise<Document> {
    const res = await client.get(`/documents/${docId}`);
    return extractData<Document>(res);
  },

  /** 上传文档 */
  async upload(
    kbId: number,
    file: File,
    onProgress?: (loaded: number, total: number) => void,
    signal?: AbortSignal,
  ): Promise<{ document_id: number; status: string; task_id: string }> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('kb_id', String(kbId));

    try {
      const res = await client.post(
        '/documents/upload',
        formData,
        {
          timeout: 120000, // 上传超时 2 分钟
          onUploadProgress: (progressEvent) => {
            if (onProgress && progressEvent.total) {
              onProgress(progressEvent.loaded, progressEvent.total);
            }
          },
          signal,
        },
      );
      return extractData<{ document_id: number; status: string; task_id: string }>(res);
    } catch (error) {
      // 主动 abort 不应显示上传失败提示 (用户已主动关闭 Modal)
      if (signal?.aborted) throw error;
      // client 拦截器已统一提取服务器 message；上传场景无 message 时使用 i18n 兜底
      if (error instanceof Error && error.message) {
        throw error;
      }
      throw new Error(globalT('document.uploadFailed'));
    }
  },

  /** 删除文档 */
  async delete(docId: number): Promise<void> {
    await client.delete(`/documents/${docId}`);
  },

  /** 重新解析文档 */
  async reparse(docId: number, force: boolean = false): Promise<{ document_id: number; task_id: string }> {
    const res = await client.post(`/documents/${docId}/reparse`, null, {
      params: { force },
    });
    return extractData(res);
  },

  /** 获取文档处理进度 */
  async getProgress(docId: number, signal?: AbortSignal): Promise<DocumentProgress> {
    return getWithOptionalSignal<DocumentProgress>(`/documents/${docId}/progress`, undefined, signal);
  },

  /** 预览文档内容 */
  async preview(docId: number, page = 1, pageSize = 50, signal?: AbortSignal): Promise<DocumentPreviewData> {
    const res = await client.get(`/documents/${docId}/preview`, {
      params: { page, page_size: pageSize },
      signal,
    });
    return extractData<DocumentPreviewData>(res);
  },
};

export default documentApi;
