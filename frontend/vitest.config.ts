import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
    // 默认 5s 在 CI/慢机器上会 flaky（Layout, FeedbackModal, KBCollaboratorModal 等）
    testTimeout: 15000,
    hookTimeout: 15000,
    coverage: {
      exclude: [
        'src/api/index.ts',
        'src/main.tsx',
        'src/vite-env.d.ts',
        'src/types/**',
        'src/i18n/**/*.json',
        'src/test/**',
        'src/**/*.{config,d}.{ts,js}',
        '**/*.d.ts',
      ],
      thresholds: {
        lines: 70,
        statements: 70,
        branches: 60,
        functions: 70,
      },
    },
  },
});
