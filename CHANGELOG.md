# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-07-11

### Added
- RAGAS 评估体系，支持自动化 RAG 质量评估（忠实度、相关性、上下文精度、上下文召回）
- 多模型支持：通过 ModelFactory 支持 OpenAI 兼容 API 与 Ollama，可热切换
- 反馈闭环：用户对回答的满意度反馈（点赞/点踩），自动记录用于后续优化
- 性能基准测试（Locust），覆盖 RAG 检索、生成、并发等关键路径
- 深色模式（Dark Mode），支持系统主题跟随与手动切换
- 国际化（i18n），支持中英文语言切换
- PWA 支持，可安装为桌面应用并支持离线缓存
- WebSocket 通知系统，实时推送文档处理状态、系统消息
- 事件驱动架构：核心流程解耦为事件-监听器模式
- API 版本化（v1），为未来 API 演进预留空间
- 数据库连接池可配置（pool_size、max_overflow、pool_timeout）
- 代码质量优化：ESLint、Prettier、pre-commit hooks 统一代码风格

### Changed
- 优化 RAG 检索精度，引入缓存层减少重复 embedding 计算
- 改进前端 UI/UX，提升交互体验
- 重构部分后端代码，消除技术债务

## [0.1.0] - 2026-07-04

### Added
- 核心 RAG 问答功能：混合检索（BM25 + 向量）+ RRF 融合 + Rerank 重排序
- 用户认证与权限管理：JWT 认证（access + refresh token）、RBAC 角色控制
- 文档上传与解析：支持 PDF、DOCX、Markdown、TXT 多格式
- Tauri 桌面端打包：Windows 平台原生桌面应用
- 知识库管理：创建、删除、文档列表
- 流式对话：SSE 流式响应，支持引用来源标注
- 异步文档处理：Celery 异步文档解析与向量入库
- 数据库迁移：Alembic 版本化 schema 管理
- API 限流保护：防止滥用
- Token 黑名单机制：支持主动登出

[Unreleased]: https://github.com/your-username/your-repo/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/your-username/your-repo/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/your-username/your-repo/releases/tag/v0.1.0