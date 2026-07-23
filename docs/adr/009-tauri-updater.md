# ADR-009: Tauri 自动更新与签名方案

## 状态

已采纳

## 日期

2026-07-21

## 上下文

平台桌面端基于 Tauri 2 打包 Windows NSIS 安装包，目前存在以下问题：

- **无自动更新机制**：用户需手动到 GitHub Releases 下载新版本覆盖安装，迭代到达率低。
- **未对安装包签名**：Windows SmartScreen 会拦截未签名 exe，用户体验差且存在被中间人替换的风险。
- **CI 未产出可发布产物**：`tauri-ci.yml` 仅做 `cargo check`，未实际生成 NSIS bundle，无法对接 release 流程。

阶段五 Task 48 要求引入 `tauri-plugin-updater`、配置 `bundle.windows.certificateThumbprint` 与 `publish.publicKey`，并新增 `tauri-build` CI job。

### 关键约束冲突

`project_memory.md` 明确记录：

> Tauri `--allow-running-insecure-content` flag is required for HTTPS (tauri.localhost) to load HTTP (localhost:8000) backend resources; cannot be removed even though it weakens security.
> Tauri 2 production mode requires adding `--allow-running-insecure-content` to additionalBrowserArgs in tauri.conf.json.

而 spec Task 48.3 原文要求"移除 `additionalBrowserArgs` 中的 `--allow-running-insecure-content`（需先验证 CSP 允许 http://localhost:8000）"。

### 验证 CSP 是否足以替代 insecure-content flag

当前 `tauri.conf.json` 的 CSP 已配置：

```
connect-src 'self' http://localhost:8000
```

理论上 CSP 的 `connect-src` 已经允许前端向 `http://localhost:8000` 发起 fetch / httpx 调用。但 Tauri 2 生产模式存在两层安全策略叠加：

1. **CSP（应用层）**：由 WebView2 解析，控制 XHR / fetch / WebSocket 等应用层请求。
2. **Chromium 混合内容自动升级（浏览器层）**：当主页面是 HTTPS（`https://tauri.localhost`）时，Chromium 会自动阻止加载 HTTP 子资源（包括 fetch、img、script 等），即使 CSP 允许也会被浏览器层拦截。WebView2 在 Windows 上基于 Chromium，此策略默认开启。

实测：仅配置 CSP `connect-src http://localhost:8000` 而不带 `--allow-running-insecure-content`，Tauri 2 生产模式下前端调用 `http://localhost:8000/api/...` 会失败（被 Chromium 拦截，控制台报 mixed content 错误）。

### 替代方案分析

| 方案 | 是否能移除 insecure-content flag | 评估 |
|------|------|------|
| 仅配置 CSP `connect-src http://localhost:8000` | ❌ | Chromium 混合内容策略会先于 CSP 拦截 |
| 后端 HTTPS 化（localhost 自签证书） | ⚠️ | WebView2 对自签证书不信任，需额外安装根证书，部署复杂度高 |
| 使用 Tauri rust 命令代理 HTTP 请求 | ✅ | 改造量大，所有 axios.fetch 都要改成 invoke('fetch_proxy')，违背"前后端 API 一致"原则 |
| 使用 HTTPS 反向代理到 localhost:8000 | ⚠️ | 桌面端单机部署无法保证用户机器有反向代理 |
| 保留 `--allow-running-insecure-content` flag | ✅ | 当前方案，仅在 localhost 范围内使用，风险可控 |

## 决策

### 1. 保留 `--allow-running-insecure-content`，不移除

经实测与文档分析，移除该 flag 会破坏 Tauri 2 生产模式下前端对 `http://localhost:8000` 后端的访问，**与 project_memory.md 的硬约束一致**。在 ADR 中正式记录此技术决策，作为对 spec Task 48.3 的偏离说明。

**风险缓解**：

- 该 flag 仅影响 WebView2 的混合内容策略，不会绕过 CSP 或 Tauri 的 capability 系统。
- 后端默认监听 `127.0.0.1:8000`，不接受外部网络请求，攻击面限于本机。
- 后续可探索"后端绑定 unix socket + Tauri IPC 代理"方案以彻底移除该 flag。

### 2. Updater 插件：`tauri-plugin-updater` (v2)

- Cargo.toml 添加 `tauri-plugin-updater = "2"`，与 `@tauri-apps/api` v2 兼容。
- 配置位置：`tauri.conf.json` → `plugins.updater`（Tauri 2 的官方位置；spec 提到的 `publish.publicKey` 是 Tauri 1 的字段名，Tauri 2 已迁移到 `plugins.updater`）。
- `endpoints` 指向 GitHub Releases 的 `latest.json`（由 `tauri build` 自动生成）。
- `pubkey` 占位符：`PLACEHOLDER_REPLACE_WITH_REAL_UPDATER_PUBLIC_KEY_BASE64`，生产环境通过 `tauri signer generate` 生成密钥对后替换。
- `windows.installMode: passive`：安装时显示进度但无需用户交互，平衡用户体验与可控性。

### 3. Windows 代码签名

- `bundle.windows.certificateThumbprint`：占位符 `0000000000000000000000000000000000000000`（40 位十六进制 0），生产环境替换为真实 EV 证书 SHA-1 thumbprint。
- `digestAlgorithm: sha256`：现代签名算法，符合 Windows 10+ 要求。
- `timestampUrl: http://timestamp.sectigo.com`：Sectigo 时间戳服务器，保证签名在证书过期后仍有效。
- `webviewInstallMode.downloadBootstrapper`：未安装 WebView2 时自动下载微软官方 bootstrapper。

### 4. CI 流水线：`tauri-build` job

- Runner：`windows-latest`（Tauri 2 Windows bundle 必须 Windows 环境构建）。
- Steps：checkout → setup-node 20 → setup-rust stable → npm ci → `npm run tauri:build` → upload-artifact。
- 通过 `TAURI_SIGNING_PRIVATE_KEY` / `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` secrets 注入 updater 签名密钥；未配置时跳过签名但仍生成 NSIS bundle。
- Artifact 路径：`frontend/src-tauri/target/release/bundle/nsis/*.exe` + `*.sig`，保留 14 天供 release job 引用。
- 仅在 `push` 事件触发（PR 仅跑 audit/check，避免 Windows runner 费用浪费）。

## 后果

### 正面影响

- 桌面端具备 OTA 自动更新能力，用户无需手动下载覆盖安装。
- 生产配置签名后可消除 SmartScreen 警告，提升用户信任度。
- CI 产出可发布的 NSIS bundle artifact，可与 `full-ci.yml` 的 release job 联动。
- Tauri 2 updater 的 `latest.json` 机制天然与 GitHub Releases 集成，无需自建更新分发服务。

### 负面影响

- **保留 `--allow-running-insecure-content`**：偏离 spec Task 48.3 原文，需在 ADR 中明确记录决策理由，并在 PR 描述中说明。
- 签名证书需采购（EV 证书约 ¥3000/年）或使用自签名（用户需手动信任），目前用占位符推迟决策。
- Updater 公钥/私钥对需妥善管理：私钥放 GitHub Secrets，公钥嵌入 `tauri.conf.json`；私钥泄漏后可签发恶意更新。
- Windows runner CI 费用是 Linux 的 2x，PR 不触发 `tauri-build` 以控制成本。
- `tauri-plugin-updater` 增加 Rust 编译时间约 30s，binary 体积增加约 2MB。

## 替代方案

| 方案 | 优点 | 缺点 | 为何未选择 |
|------|------|------|------------|
| 自研更新检查 + 手动下载 | 实现简单，无外部依赖 | 无增量更新、无签名校验、用户体验差 | 不满足"自动更新"需求 |
| electron-updater | 生态成熟，文档丰富 | 与 Tauri 不兼容 | 技术栈不匹配 |
| NsisMSBuild 自部署更新服务器 | 完全可控 | 需自建分发基础设施，运维成本高 | 当前规模不需要 |
| Squirrel.Windows | 成熟的 Windows 更新框架 | 与 Tauri 打包产物不兼容，已停止维护 | 兼容性问题 |
| Tauri 1.x 内置 updater | 无需额外插件 | 项目已用 Tauri 2，降级不可行 | 版本不匹配 |

## 参考

- [Tauri 2 Updater Plugin](https://v2.tauri.app/plugin/updater/)
- [Tauri 2 Windows Signing](https://v2.tauri.app/distribute/sign-windows/)
- [Chromium Mixed Content](https://developer.chrome.com/blog/mixed-content/)
- project_memory.md 中 `--allow-running-insecure-content` 硬约束记录
- 实现：
  - `frontend/src-tauri/Cargo.toml` 添加 `tauri-plugin-updater = "2"`
  - `frontend/src-tauri/tauri.conf.json` 的 `plugins.updater` 与 `bundle.windows` 配置
  - `.github/workflows/tauri-ci.yml` 新增 `tauri-build` job（windows-latest runner）
