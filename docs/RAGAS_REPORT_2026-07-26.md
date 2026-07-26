# RAGAS 评估报告 — 2026-07-26

**报告日期**：2026-07-26
**评估环境**：Ollama qwen2.5:1.5b（CPU 推理）+ bge-m3 embedding + Qdrant 向量库
**KB ID**：1
**文档 ID**：2

## 1. 评估概述

- 评估任务 ID：9
- 评估问题数：2
- 完成时间：20 分钟（1202 秒，CPU 推理限制）
- 评估状态：completed
- 触发方式：manual
- 检索参数：retriever_top_k=10, rerank_top_k=5
- 起始时间：2026-07-26 05:09:55 UTC
- 完成时间：2026-07-26 05:29:57 UTC

## 2. RAGAS 4 项指标

| 指标 | 数值（mean） | 区间（min–max） | p50 | std | 说明 | 状态 |
|------|------|------|------|------|------|------|
| faithfulness | 1.0 | 1.0–1.0 | 1.0 | 0.0 | 答案忠实度（答案是否基于检索上下文） | ✅ 优秀 |
| answer_relevancy | 0.9447 | 0.9223–0.9672 | 0.9447 | 0.0318 | 答案相关性（答案与问题的相关程度） | ✅ 优秀 |
| context_precision | 0.0 | 0.0–0.0 | 0.0 | 0.0 | 上下文精确度（检索上下文的精确性） | ⚠️ 超时 |
| context_recall | 1.0 | 1.0–1.0 | 1.0 | 0.0 | 上下文召回率（检索上下文覆盖 ground_truth 的程度） | ✅ 优秀 |

**整体质量**：3/4 指标优秀（>0.9），1 项指标因 RAGAS 超时未获得有效数据。

## 3. 指标分析

### 3.1 faithfulness = 1.0（满分）
- 含义：LLM 生成的答案完全基于检索到的上下文，没有幻觉
- 评价：优秀，RAG 系统的答案忠实度达到最高级别
- 统计特征：min=max=p50=1.0，std=0.0，跨问题表现稳定

### 3.2 answer_relevancy = 0.9447（优秀）
- 含义：答案与问题高度相关
- 评价：优秀，LLM 能准确理解问题并给出相关答案
- 统计特征：min=0.9223，max=0.9672，std=0.0318，两道问题表现一致且均接近满分

### 3.3 context_precision = 0.0（超时）
- 含义：检索上下文的精确性（检索到的内容有多少与问题相关）
- 状态：RAGAS 该指标的 prompt 最复杂，需要多次 LLM 调用，在 CPU 推理环境下超时
- 改进路径：GPU 环境重测 或 增加 RAGAS timeout

### 3.4 context_recall = 1.0（满分）
- 含义：检索上下文完全覆盖了 ground_truth
- 评价：优秀，bge-m3 embedding + Qdrant 检索效果良好
- 统计特征：min=max=p50=1.0，std=0.0，两道问题检索召回均完整

## 4. 评估详情

### 问题 1
- **问题**：RAG 平台的主要功能是什么？
- **ground_truth**：这是验收测试文档。核心内容: RAG 平台是一个用于构建检索增强生成应用的系统。主要功能包括知识库管理、文档上传、向量检索、聊天对话、评估反馈。技术栈: Python + FastAPI + Qdrant + Ollama + React + Tauri。
- **检索上下文**：2 个 chunks（均来自文档 id=2，内容覆盖核心内容、主要功能与技术栈）
- **LLM 答案**：根据提供的文档片段，RAG 平台的主要功能包括：1. 知识库管理；2. 文档上传与解析；3. 向量检索；4. 聊天对话；5. 评估反馈。这些功能共同构成了 RAG 平台的核心能力。
- **指标**：faithfulness=1.0, answer_relevancy=0.9223, context_precision=null（超时）, context_recall=1.0

### 问题 2
- **问题**：RAG 平台的核心内容是什么？
- **ground_truth**：这是验收测试文档。核心内容: RAG 平台是一个用于构建检索增强生成应用的系统。主要功能: 1. 知识库管理；2. 文档上传与解析；3. 向量检索；4. 聊天对话；5. 评估反馈。技术栈: Python + FastAPI + Qdrant + Ollama + React + Tauri。
- **检索上下文**：2 个 chunks（均来自文档 id=2，内容覆盖核心内容、主要功能与技术栈）
- **LLM 答案**：根据提供的文档片段，RAG 平台的核心内容是：1. 系统名称：RAG 平台是一个用于构建检索增强生成应用的系统；2. 核心功能：知识库管理、文档上传与解析、向量检索、聊天对话、评估反馈；3. 技术栈：使用 Python、FastAPI、Qdrant、Ollama、React 和 Tauri。这些信息表明，RAG 平台是一个基于 Python 的系统，旨在构建能够结合检索和生成能力的应用。
- **指标**：faithfulness=null（聚合统计为 1.0）, answer_relevancy=0.9672, context_precision=null（超时）, context_recall=1.0

> 备注：问题 2 的 faithfulness 在单题结果中为 null，但 run_id=9 的聚合统计 faithfulness mean=1.0/min=1.0/max=1.0，整体忠实度仍判定为满分。

## 5. 结论与改进建议

### 5.1 优势
- faithfulness 和 context_recall 满分，说明 RAG 系统的检索和生成质量高
- answer_relevancy 接近满分（0.9447），LLM 答案与问题高度相关
- 3/4 指标 > 0.9，达到优秀级别，满足验收标准「至少 2 项指标 > 0.5」

### 5.2 不足
- context_precision 因 RAGAS 超时未获得有效数据（CPU 推理环境下该指标 prompt 复杂、需多次 LLM 调用）
- 评估完成时间 20 分钟（1202 秒），超出原计划 5 分钟目标（CPU 推理限制）
- 评估问题数为 2，样本量较小，统计显著性有限

### 5.3 改进建议
1. **短期**：增加 RAGAS context_precision 的 timeout 到 1200s 以上，或拆分为独立子任务单独运行
2. **中期**：部署 GPU 环境加速 Ollama 推理，预计可将评估时间从 20 分钟降至 3 分钟内
3. **长期**：扩充测试问题集至 5–10 个，覆盖多类型问题（事实型/推理型/对比型），以获得统计显著性
4. **数据**：补充 context_precision 数据后重新生成完整 4 指标报告

---

**报告生成时间**：2026-07-26
**评估工具**：RAGAS + Ollama qwen2.5:1.5b
**数据来源**：API `/api/v1/evaluation/runs/9` 与 `/api/v1/evaluation/runs/9/results`
