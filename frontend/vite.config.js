import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import compression from 'vite-plugin-compression';
export default defineConfig({
    plugins: [
        react(),
        // gzip 压缩产物
        compression({
            algorithm: 'gzip',
            ext: '.gz',
            threshold: 10240,
            deleteOriginFile: false,
        }),
        // brotli 压缩产物（压缩率高于 gzip）
        compression({
            algorithm: 'brotliCompress',
            ext: '.br',
            threshold: 10240,
            deleteOriginFile: false,
        }),
    ],
    // 顶层 esbuild 配置: 生产构建时移除 console.log/info/debug (保留 error/warn) 和 debugger
    esbuild: {
        pure: ['console.log', 'console.info', 'console.debug'],
        drop: ['debugger'],
    },
    server: {
        port: 5173,
        proxy: {
            '/api': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            },
            '/health': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            },
        },
    },
    build: {
        outDir: 'dist',
        sourcemap: false,
        minify: 'esbuild',
        rollupOptions: {
            output: {
                manualChunks: {
                    vendor: ['react', 'react-dom', 'react-router-dom'],
                    antd: ['antd'],
                    icons: ['lucide-react'],
                    // echarts 体积较大，独立分块利于浏览器缓存
                    echarts: ['echarts', 'echarts-for-react'],
                    // markdown 渲染相关依赖独立分块
                    markdown: ['react-markdown', 'remark-gfm'],
                    // i18n 国际化独立分块
                    i18n: ['i18next', 'react-i18next'],
                },
            },
        },
    },
});
