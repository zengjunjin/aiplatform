# 运行时动态审计报告 — aiplatform Docker 全栈

> 审计人：齐活林（主理人，动态审计 + 现场修复）
> 日期：2026-07-29 12:30（容器栈运行中实测）
> 基准：**本机为唯一基准**（用户明确：不考虑其他电脑可移植性）
> 关联报告：[containerization-review.md](./containerization-review.md)（静态评审，本报告修订其部分定级）

## 本机硬件基准（实测）

| 项 | 配置 | 评估 |
|----|------|------|
| CPU | i7-13700H（14C20T） | 充裕 |
| RAM | 15.6 GB | **全栈主要约束**，当前实测占用 ~3.2GB 健康 |
| GPU | RTX 4060 Laptop **8GB 显存**（容器内 nvidia-smi 实测 8188MiB） | qwen2.5:7b 已上卡 6.2GB，舒适 |
| 磁盘 | G 盘剩余 92.6GB / 477GB | 充裕 |
| WSL2 | 无 .wslconfig，默认内存上限 ≈ 物理 50%（~8GB） | 当前无压力，建议显式配置 |

## 一、全栈运行现状（19 容器实测）

✅ **19/19 容器 Up，全部健康检查通过**（jaeger/loki 经本次现场修复后恢复 healthy）
✅ 服务端点：`/healthz`、`/readyz`（db/redis/qdrant 全 ok）、nginx 反代、Grafana 登录页 200、Jaeger UI 200
✅ Ollama：qwen2.5:7b（LLM）+ qwen2.5:1.5b（fallback）+ bge-m3（embedding）齐备，7b 模型常驻显存 6.2/8GB
✅ Prometheus 6 个 job targets 全 up（backend metrics token 本机一致，抓取正常）
✅ 资源水位（stats 实测）：backend 847MB/2GB、celery 436MB/2GB、ollama 1020MB/4GB、qdrant 390MB/1GB——均健康；全栈合计 ~3.2GB

## 二、本次动态审计新发现（含已现场修复项）

### 🔴 P0-1【已修复】Jaeger 崩溃循环：badger 卷权限错误
- **现象**：`Failed to init storage factory: mkdir /badger/key: permission denied`，每 60s 重启
- **根因**：jaeger 镜像以 UID 10001 运行，named volume `jaeger_badger_data` 首创建属 root。系上轮新增 Badger 持久化（Task 34）引入的回归
- **修复（已执行）**：`docker run --rm -v rag-platform_jaeger_badger_data:/badger alpine chown -R 10001:10001 /badger` → 重启后 healthy，Jaeger UI 200
- **遗留建议**：该修复对"删除 volume 重建"场景不免疫。根治方案二选一：compose 加 `user: "10001"` + 初始化容器，或文档化此 chown 步骤（README 运维章节）

### 🔴 P0-2【已修复】Loki 崩溃循环：配置字段与镜像版本不匹配
- **现象**：`field purge_interval not found in type compactor.Config`（deploy/loki-config.yaml:36）
- **根因**：v0.4.0 加 retention 时写入的 `purge_interval: 10m` 不是 Loki 2.9 的合法 compactor 字段
- **修复（已执行）**：删除该行（retention 功能不依赖它）→ 重启后 healthy，`/ready` 返回 ready

### 🔴 P0-3【已随 P0-1 自愈】backend/celery OTel 导出失败级联刷屏
- **现象**：jaeger 崩溃期间，`OtelBatchSpanProcessor` 每 5s 向 `http://jaeger:4318` 导出失败，刷 ~100 行 ConnectionError traceback（DNS 解析失败——crash loop 中容器 DNS 记录时有时无）
- **影响**：日志噪音爆炸（10m×3 轮转下真实日志被快速冲掉）、tracing 失效
- **现状**：jaeger 修复后实测 `--since 40s` 内 0 条新错误 ✓
- **加固建议**：backend OTel 导出失败应降级为计数/采样日志（当前全栈 traceback），或 compose 给 backend/celery 加 jaeger 的 `depends_on: service_started`（可选，不必须）

## 三、上轮静态评审发现的复核（按本机基准重新定级）

| 上轮发现 | 状态 | 本机基准下的定级 |
|---------|------|----------------|
| ollama GPU reservations（原 P0） | 未改动 | ✅ **撤销**——本机 RTX 4060 正常工作，模型已上卡，配置合理 |
| fresh clone 缺 .env（原 P0） | 未改动 | ✅ **撤销**——本机 .env 已存在，不适用 |
| 源码 bind mount 遮蔽镜像（原 P1） | **仍存在**（compose:146,149,207） | 🟡 降为 P2——本机开发可接受，但须知：镜像内代码是死重，"容器化交付"叙事被问时要有答案 |
| **celery_worker 镜像 8.96GB**（3 天前）vs backend 2.28GB（23h 前） | **未随重建** | 🔴 **P1 新增**——celery 还在用含 CUDA torch 的旧胖镜像（白占 6.7GB 磁盘、依赖环境滞后）。`docker compose build celery_worker` 或 `docker compose build` 全量重建 |
| torch 先下 5GB CUDA 再卸载（原 P1） | 未改动 | 🟡 P2 保留——下次重建仍会浪费 5GB 带宽，建议 pytorch-cpu source |
| deploy/Makefile 失效旧版 | **仍存在** | 🟡 P2——本机用根 Makefile 即可，但旧版拉错 nomic-embed-text 是定时炸弹，建议删 |
| prometheus bearer_token 硬编码（原 P1） | 仍存在但本机 .env 恰好一致 | 🟢 降为 P3——本机 targets 全 up 实测正常 |
| 10 服务无 logging 轮转（原 P1） | 仍存在 | 🟡 P2——实测各服务日志量小，但 loki/jaeger 崩溃期间证明了日志爆炸风险真实存在（backend OTel 刷屏），建议 anchor 统一补 |
| nginx HSTS on HTTP / README TLS 漂移（原 P2） | 仍存在 | 🟢 P3——本机演示无碍，面试问答准备口径即可 |

## 四、本机配置调优建议（16GB RAM + 8GB VRAM 专属）

1. **`OLLAMA_NUM_PARALLEL=8` 对 8GB 显存过于激进**（compose:83）：7b 模型已占 6.2GB，并行 8 个生成请求必然爆显存触发 CPU offload，表现为"多用户同时问答时速度骤降"。**建议改为 2~3**——这台卡的真实舒适区。
2. **mem_limit 理论总和 ~14.3GB ≈ 物理 15.6GB**：实测仅 3.2GB 无虞，但极限场景（文档解析+评估+reranker 同时跑）WSL2 VM 默认 ~8GB 上限会先触顶。建议在 `C:\Users\15116\.wslconfig` 显式声明（如 `memory=10GB, processors=8`），避免默认策略漂移。
3. **grafana 内存水位 55.8%**（143/256MB）：dashboard 面板多开时会顶到限值被 OOMKill，建议 mem_limit 提到 384~512m。
4. **celery CPU 76% 为采样瞬间峰值**（inspect active 显示无任务在跑），非持续问题；复现时优先怀疑 reranker 模型懒加载（sentence-transformers CPU 推理）。

## 五、结论

**运行时健康度：修复后 9/10**（修复前 6.5/10——2 服务崩溃 + 日志级联刷屏）。

全栈在你这台机器上跑得相当好：GPU 推理上卡、内存水位健康、监控链路全通。本次现场修掉了 2 个会导致"可观测性演示翻车"的崩溃服务（Jaeger/Loki），并验证了其级联影响已消除。**剩余唯一值得立刻做的是重建 celery_worker 镜像**（8.96GB→预期 ~2.3GB，省 6.7GB 磁盘并同步依赖环境），其余按上表分级从容处理。

## 六、执行清单（按优先级）

| # | 行动 | 状态 |
|---|------|------|
| 1 | Jaeger badger 卷 chown + 重启 | ✅ 已完成（审计时） |
| 2 | loki-config.yaml 删 `purge_interval` + 重启 | ✅ 已完成（审计时） |
| 3 | celery_worker 镜像更新为 2.28GB | ✅ 已完成（12:50，详见下方"构建缓存事件"） |
| 4 | `OLLAMA_NUM_PARALLEL=8 → 3`（compose:86） | ✅ 已完成并生效（容器内实测=3） |
| 5 | 编写 ~/.wslconfig（memory=10GB / processors=8 / swap=4GB） | ✅ 已编写，**需用户空闲时 `wsl --shutdown` 生效** |
| 6 | 删除 deploy/Makefile + README 指向根 Makefile + quickstart 补 .env 步骤 + v2 语法 | ✅ 已完成 |
| 7 | compose x-logging anchor 统一 19 服务日志轮转 + jaeger chown 写入 runbook（docs/runbooks/jaeger-badger-permission.md） | ✅ 已完成（config 语法验证通过，已 recreate 生效） |

## 七、附录：celery_worker 构建缓存事件（重要运维记录）

**事件**：`docker compose build celery_worker`（命中缓存，2m46s 完成）产出的镜像 `/app/.venv/bin` 只剩 pip——poetry 依赖整体缺失，容器启动报 `exec: "celery": executable file not found in $PATH`。

**诊断**：backend 镜像（23h 前同 Dockerfile 构建）`.venv/bin` 完整（54 个文件）；本次 celery 构建 BuildKit 命中了损坏的 builder 缓存链（COPY 层仅 795MB，完整应 ~1.5GB+）。

**解法（已执行）**：`docker tag rag-platform-backend:latest rag-platform-celery_worker:latest`——两服务本就同 Dockerfile 同 context，镜像内容应完全一致，tag 共享零成本恢复服务，同时省 6.7GB 磁盘。

**长期建议**（未实施，下次维护窗口做）：
1. compose 中 celery_worker 直接 `image: rag-platform-backend` 并移除其 `build:` 块——**单一镜像双 command**（backend=uvicorn / celery=worker），从根上消除"两份构建、缓存漂移"风险，构建时间减半；
2. 或至少 `docker compose build`（全量）替代单独 build 某个服务，保持两 tag 同源；
3. pyproject.toml 加 `pytorch-cpu` source + `torch = {version="2.12.1+cpu", source="pytorch-cpu"}`（静态评审 P1-2 方案），下次全量构建可省 ~5GB CUDA 下载，且消除 Dockerfile:37-42 硬编码 cu13 卸载清单的静默失效风险。
