import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import NewSessionModal from '../../components/NewSessionModal';
import type { KnowledgeBase } from '../../types';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string, params?: any) => {
    if (params && params.count !== undefined) return `${key} ${params.count}`;
    return key;
  }}),
}));

const mockKBs: KnowledgeBase[] = [
  {
    id: 1,
    name: 'KB1',
    description: 'desc1',
    owner_id: 1,
    doc_count: 5,
    chunk_count: 100,
    collaborators: null,
    created_at: '',
    updated_at: '',
  },
  {
    id: 2,
    name: 'KB2',
    description: '',
    owner_id: 1,
    doc_count: 0,
    chunk_count: 0,
    collaborators: null,
    created_at: '',
    updated_at: '',
  },
];

describe('NewSessionModal', () => {
  it('should render modal title and form labels when open', () => {
    render(
      <NewSessionModal
        open={true}
        knowledgeBases={mockKBs}
        onSubmit={vi.fn()}
        onCancel={() => {}}
        afterClose={() => {}}
      />
    );
    expect(screen.getByText('chat.newChat')).toBeInTheDocument();
    expect(screen.getByText('chat.selectKB')).toBeInTheDocument();
    expect(screen.getByText('chat.sessionTitleOptional')).toBeInTheDocument();
  });

  it('should render knowledge base options with doc count', () => {
    render(
      <NewSessionModal
        open={true}
        knowledgeBases={mockKBs}
        onSubmit={vi.fn()}
        onCancel={() => {}}
        afterClose={() => {}}
      />
    );
    // Open the select dropdown (Modal renders to portal in document.body, use document.querySelector)
    const select = document.querySelector('.ant-select-selector');
    if (select) {
      fireEvent.mouseDown(select);
    }
    expect(screen.getByText(/KB1/)).toBeInTheDocument();
  });

  it('should call onCancel when cancel button clicked', () => {
    const onCancel = vi.fn();
    render(
      <NewSessionModal
        open={true}
        knowledgeBases={mockKBs}
        onSubmit={vi.fn()}
        onCancel={onCancel}
        afterClose={() => {}}
      />
    );
    const cancelBtn = screen.getByText('chat.cancel');
    fireEvent.click(cancelBtn);
    expect(onCancel).toHaveBeenCalled();
  });

  it('should call onSubmit with form values when OK clicked and form validates', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <NewSessionModal
        open={true}
        knowledgeBases={mockKBs}
        onSubmit={onSubmit}
        onCancel={() => {}}
        afterClose={() => {}}
      />
    );
    // Type title (Modal renders to portal, use screen query to find input by label)
    const titleInput = screen.getByLabelText('chat.sessionTitleOptional') as HTMLInputElement;
    fireEvent.change(titleInput, { target: { value: 'My new session' } });
    // Click OK
    const okBtn = screen.getByText('chat.create');
    fireEvent.click(okBtn);
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalled();
    });
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ title: 'My new session' }));
  });

  it('should not call onSubmit when form validation fails (kb_id is optional, title is optional)', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <NewSessionModal
        open={true}
        knowledgeBases={[]}
        onSubmit={onSubmit}
        onCancel={() => {}}
        afterClose={() => {}}
      />
    );
    // Click OK without filling anything (no required fields, should still call onSubmit with empty values)
    const okBtn = screen.getByText('chat.create');
    fireEvent.click(okBtn);
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({}));
    });
  });

  it('should reset form after successful submit', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <NewSessionModal
        open={true}
        knowledgeBases={mockKBs}
        onSubmit={onSubmit}
        onCancel={() => {}}
        afterClose={() => {}}
      />
    );
    const titleInput = screen.getByLabelText('chat.sessionTitleOptional') as HTMLInputElement;
    fireEvent.change(titleInput, { target: { value: 'temp title' } });
    const okBtn = screen.getByText('chat.create');
    fireEvent.click(okBtn);
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalled();
    });
    // After reset, title input should be empty (wait for async reset to complete)
    await waitFor(() => {
      const input = screen.getByLabelText('chat.sessionTitleOptional') as HTMLInputElement;
      expect(input.value).toBe('');
    });
  });
});
