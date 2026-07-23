import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import NotFoundPage from '../pages/NotFoundPage';

// Mock react-i18next: 返回中文文本以便断言
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const map: Record<string, string> = {
        'notFound.subtitle': '抱歉,您访问的页面不存在',
        'notFound.backHome': '返回首页',
      };
      return map[key] || key;
    },
  }),
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

describe('NotFoundPage', () => {
  it('should render 404 title', () => {
    render(
      <MemoryRouter>
        <NotFoundPage />
      </MemoryRouter>
    );
    expect(screen.getByText('404')).toBeInTheDocument();
  });

  it('should render not found message', () => {
    render(
      <MemoryRouter>
        <NotFoundPage />
      </MemoryRouter>
    );
    expect(screen.getByText('抱歉,您访问的页面不存在')).toBeInTheDocument();
  });

  it('should render back to home button', () => {
    render(
      <MemoryRouter>
        <NotFoundPage />
      </MemoryRouter>
    );
    expect(screen.getByText('返回首页')).toBeInTheDocument();
  });
});