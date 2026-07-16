import client, { extractData, getApiBase } from './client';
import { useAuthStore } from '../store/auth';
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
  /** 获取文档列表 */
  async list(kbId: number, page = 1, pageSize = 20): Promise<{ items: Document[]; total: number; page: number; page_size: number; total_pages: number }> {
    const res = await client.get('/documents', {
      params: { kb_id: kbId, page, page_size: pageSize },
    });
    return extractData(res) as any;
  },

  /** 获取文档详情 */
  async get(docId: number): Promise<Document> {
    const res = await client.get(`/documents/${docId}`);
    return extractData(res);
  },

  /** 上传文档 */
  async upload(
    kbId: number,
    file: File,
    onProgress?: (loaded: number, total: number) => void,
  ): Promise<{ document_id: number; status: string; task_id: string }> {
    const token = useAuthStore.getState().token;
    const formData = new FormData();
    formData.append('file', file);
    formData.append('kb_id', String(kbId));

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${getApiBase()}/documents/upload`);
    xhr.timeout = 120000; // 上传超时 2 分钟
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);

    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(e.loaded, e.total);
      };
    }

    return new Promise((resolve, reject) => {
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            const data = JSON.parse(xhr.responseText);
            resolve(data.data || data);
          } catch {
            reject(new Error('响应解析失败'));
          }
        } else {
          let msg = `上传失败 (${xhr.status})`;
          try {
            const data = JSON.parse(xhr.responseText);
            msg = data.message || msg;
          } catch {}
          reject(new Error(msg));
        }
      };
      xhr.onerror = () => reject(new Error('网络错误'));
      xhr.send(formData);
    });
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
  async getProgress(docId: number): Promise<DocumentProgress> {
    const res = await client.get(`/documents/${docId}/progress`);
    return extractData(res);
  },

  /** 预览文档内容 */
  async preview(docId: number, page = 1, pageSize = 50): Promise<DocumentPreviewData> {
    const res = await client.get(`/documents/${docId}/preview`, {
      params: { page, page_size: pageSize },
    });
    return extractData(res);
  },
};

export default documentApi;
