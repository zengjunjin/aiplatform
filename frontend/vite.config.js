var __spreadArray = (this && this.__spreadArray) || function (to, from, pack) {
    if (pack || arguments.length === 2) for (var i = 0, l = from.length, ar; i < l; i++) {
        if (ar || !(i in from)) {
            if (!ar) ar = Array.prototype.slice.call(from, 0, i);
            ar[i] = from[i];
        }
    }
    return to.concat(ar || Array.prototype.slice.call(from));
};
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import compression from 'vite-plugin-compression';
// CI 环境下禁用 compression 插件：
// vite-plugin-compression 的 closeBundle 钩子中 fs.writeFile 无 try/catch，
// 在 Linux CI 上可能因路径处理或时序问题导致 vite build 以 exit 1 失败。
// CI 的目的是验证构建能成功，不需要 gzip/brotli 压缩产物。
// 本地构建启用 compression 生成压缩产物供部署使用。
var enableCompression = !process.env.CI;
export default defineConfig({
    plugins: __spreadArray([
        react()
    ], (enableCompression
        ? [
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
        ]
        : []), true),
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
            '/healthz': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            },
            '/readyz': {
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
