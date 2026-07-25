# RAG 知识库平台前端

RAG 知识库平台的前端应用，基于 React 18 + TypeScript 构建，同时通过 Tauri 2 打包为桌面客户端。

## 技术栈

- **框架**：React 18 + TypeScript 5.5
- **UI 组件**：Ant Design 5 + lucide-react 图标
- **状态管理**：Zustand 4
- **路由**：React Router 6
- **构建工具**：Vite 5
- **桌面端**：Tauri 2
- **图表**：ECharts 6 + echarts-for-react
- **国际化**：i18next + react-i18next（中/英）
- **测试**：Vitest 4 + @testing-library/react + jsdom
- **其他**：axios、dayjs、react-markdown、react-syntax-highlighter

## 快速开始

### 前置依赖

- Node.js 18+
- npm

### 安装与运行

```bash
# 1. 安装依赖
npm install

# 2. 启动 Web 开发服务器（默认监听 5173，代理 /api 至 8000）
npm run dev

# 3. 启动 Tauri 桌面客户端开发模式（需 Rust 工具链）
npm run tauri:dev
```

开发模式下，Vite 会自动代理以下路径到后端 `http://localhost:8000`：

- `/api`
- `/healthz`
- `/readyz`

## 项目结构

```
frontend/
├── src/
│   ├── pages/             # 页面组件（Login/Register/Dashboard/KnowledgeBases/Documents/Chat/Evaluation/Feedback/System/Users/Sessions）
│   ├── components/        # 通用组件（Layout/MessageBubble/MarkdownRenderer/各种 Modal 等）
│   ├── hooks/             # 自定义 Hooks（useWebSocket/useApiToast/useKbOptions）
│   ├── store/             # Zustand 状态（auth/chat/kb）
│   ├── api/               # 后端 API 封装（client/auth/chat/documents/kb/evaluation/users/system）
│   ├── utils/             # 工具函数（format/logger/tauri/chart/errorReporter/health）
│   ├── i18n/              # 国际化资源（zh-CN/en-US）
│   ├── styles/            # 全局样式与主题
│   ├── constants/         # 常量定义
│   ├── types/             # TypeScript 类型定义
│   ├── __tests__/         # 单元/组件/页面测试
│   ├── App.tsx            # 根组件与路由配置
│   └── main.tsx           # 应用入口
├── src-tauri/             # Tauri 桌面端配置与 Rust 工程文件
│   └── tauri.conf.json    # Tauri 配置（窗口、CSP、打包目标等）
├── vite.config.ts         # Vite 构建配置（代理、压缩、分包）
├── package.json           # 依赖与脚本
└── tsconfig.json          # TypeScript 配置
```

## 测试

```bash
# 运行全部测试（vitest run，单次执行）
npm test

# 监听模式
npm run test:watch

# 生成覆盖率报告（@vitest/coverage-v8）
npm run test:coverage
```

测试文件位于 `src/__tests__/` 下，按 `api/`、`components/`、`utils/` 以及页面级别组织，测试环境通过 `src/test/setup.ts` 初始化。

## 构建

### Web 构建

```bash
# 类型检查 + 生产构建，产物输出至 dist/
npm run build

# 本地预览生产构建
npm run preview
```

构建特性（见 `vite.config.ts`）：

- 生产构建自动移除 `console.log/info/debug` 与 `debugger`
- 输出 gzip（`.gz`）与 brotli（`.br`）压缩产物
- 通过 `manualChunks` 对 vendor / antd / echarts / markdown / i18n 进行分包以优化缓存

### 桌面端构建

```bash
# 打包 Tauri 桌面应用（Windows 下生成 NSIS 安装包）
npm run tauri:build
```

Tauri 配置（见 `src-tauri/tauri.conf.json`）：

- 产品名：`RAG知识库平台`，标识：`com.rag.platform`
- 默认窗口：1200×800，最小 800×600
- 打包目标：NSIS（Windows）
- CSP：限制 script/style/img/font/connect 来源，connect 允许 `http://localhost:8000` 及其 WebSocket

## 代码规范

```bash
# ESLint + TypeScript 类型检查
npm run lint
```

## 部署

部署相关说明请参考根目录 `README.md`，包含前端静态资源的部署与 Tauri 安装包的分发策略。
