import { useState, useEffect, useMemo } from 'react';
import { App as AntdApp, Row, Col, Spin } from 'antd';
import dayjs from 'dayjs';
import { kbApi, systemApi, evaluationApi } from '../api';
import { feedbackApi, chatApi } from '../api/chat';
import type { KnowledgeBase, ChatSession } from '../types';
import type { ExtendedSystemStatus } from '../api/system';
import type { EvaluationRunItem } from '../api/evaluation';
import type { FeedbackStats } from '../api/chat';
import { getErrorMessage, isAuthExpiredError } from '../utils/errorReporter';
import { globalT } from '../i18n';
import { useApiToast } from '../hooks/useApiToast';
import { useAuthStore } from '../store/auth';
import {
  DashboardTopKpis,
  DocTrendChart,
  EvalTrendChart,
  FeedbackPieChart,
  ModelHealthCard,
} from './DashboardPage.parts';
import type { ModelInfoExt } from './DashboardPage.parts';

/** 判定系统是否健康（所有核心组件 up） */
function isSystemHealthy(status: ExtendedSystemStatus | null | undefined): boolean {
  if (!status) return false;
  const keys: (keyof ExtendedSystemStatus)[] = ['postgresql', 'redis', 'ollama', 'qdrant', 'celery'];
  return keys.every((k) => {
    const v = status[k];
    return typeof v === 'string' && v.toLowerCase() === 'up';
  });
}

export default function DashboardPage() {
  const { message } = AntdApp.useApp();
  const { error: toastError } = useApiToast();
  const user = useAuthStore((s) => s.user);
  // 系统状态/评估历史/反馈统计为 admin-only 端点，user 角色调用了必然 403
  // 并弹 "Admin access required" 错误 toast（多账号 CDP 测试 T9 实证）。
  // 非 admin 跳过这 3 路请求，对应卡片展示空态。
  const isAdmin = user?.role === 'admin';

  const [loading, setLoading] = useState(true);
  const [todaySessions, setTodaySessions] = useState(0);
  const [systemStatus, setSystemStatus] = useState<ExtendedSystemStatus | null>(null);
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [evalRuns, setEvalRuns] = useState<EvaluationRunItem[]>([]);
  const [feedbackStats, setFeedbackStats] = useState<FeedbackStats | null>(null);
  const [models, setModels] = useState<ModelInfoExt[]>([]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const start = Date.now();
    setLoading(true);

    const today = dayjs().startOf('day');

    // 6 路并行数据加载，单个失败不阻断整体
    const tasks: Promise<void>[] = [
      // 1. 今日问答数：拉取最近 100 条会话，客户端筛选今日创建
      chatApi
        .listSessions(1, 100, controller.signal)
        .then((res) => {
          if (cancelled) return;
          const items: ChatSession[] = res?.items || [];
          const count = items.filter((s) => dayjs(s.created_at).isAfter(today)).length;
          setTodaySessions(count);
        })
        .catch((e) => {
          // 组件卸载 abort 后的 CanceledError 静默处理
          if (e instanceof Error && e.name === 'CanceledError') return;
          toastError('今日问答数加载失败', e);
        }),

      // 2. 系统健康状态（admin-only，user 跳过）
      isAdmin
        ? systemApi
            .status(controller.signal)
            .then((data) => {
              if (cancelled) return;
              setSystemStatus(data as ExtendedSystemStatus);
            })
            .catch((e) => {
              if (e instanceof Error && e.name === 'CanceledError') return;
              toastError('系统状态加载失败', e);
            })
        : Promise.resolve(),

      // 3. KB 列表（用于文档统计）
      kbApi
        .list(1, 100, controller.signal)
        .then((res) => {
          if (cancelled) return;
          setKbs(res?.items || []);
        })
        .catch((e) => {
          if (e instanceof Error && e.name === 'CanceledError') return;
          toastError('知识库加载失败', e);
        }),

      // 4. 评估历史（admin-only，user 跳过）
      isAdmin
        ? evaluationApi
            .listRuns({ page_size: 20 }, controller.signal)
            .then((res) => {
              if (cancelled) return;
              setEvalRuns(res?.items || []);
            })
            .catch((e) => {
              if (e instanceof Error && e.name === 'CanceledError') return;
              toastError('评估运行加载失败', e);
            })
        : Promise.resolve(),

      // 5. 反馈统计（admin-only，user 跳过）
      isAdmin
        ? feedbackApi
            .getStats(undefined, controller.signal)
            .then((data) => {
              if (cancelled) return;
              setFeedbackStats(data);
            })
            .catch((e) => {
              if (e instanceof Error && e.name === 'CanceledError') return;
              if (!isAuthExpiredError(e)) {
                message.error(getErrorMessage(e) || globalT('common.requestFailed'));
              }
            })
        : Promise.resolve(),

      // 6. 可用模型列表
      systemApi
        .listModels(controller.signal)
        .then((data) => {
          if (cancelled) return;
          setModels((data?.models || []) as ModelInfoExt[]);
        })
        .catch((e) => {
          if (e instanceof Error && e.name === 'CanceledError') return;
          if (!isAuthExpiredError(e)) {
            message.error(getErrorMessage(e) || globalT('common.requestFailed'));
          }
        }),
    ];

    // Task 39 (P1-FE-12): 保存 minLoading 定时器句柄, cleanup 中清理避免卸载后 setState
    let minLoadingTimer: ReturnType<typeof setTimeout> | null = null;

    Promise.allSettled(tasks).then(() => {
      // 保证 loading 至少展示 300ms，避免闪烁
      const elapsed = Date.now() - start;
      const minLoading = 300;
      if (cancelled) return;
      if (elapsed >= minLoading) {
        setLoading(false);
      } else {
        minLoadingTimer = setTimeout(() => {
          if (!cancelled) setLoading(false);
        }, minLoading - elapsed);
      }
    });

    return () => {
      cancelled = true;
      controller.abort();
      if (minLoadingTimer) clearTimeout(minLoadingTimer);
    };
  }, [message, toastError, isAdmin]);

  const { healthy, totalDocs, totalChunks } = useMemo(() => ({
    healthy: isSystemHealthy(systemStatus),
    totalDocs: kbs.reduce((sum, kb) => sum + (kb.doc_count || 0), 0),
    totalChunks: kbs.reduce((sum, kb) => sum + (kb.chunk_count || 0), 0),
  }), [systemStatus, kbs]);

  return (
    <Spin spinning={loading}>
      <div>
        {/* 顶部焦点 KPI 区 */}
        <DashboardTopKpis
          todaySessions={todaySessions}
          healthy={healthy}
          totalDocs={totalDocs}
          totalChunks={totalChunks}
        />

        {/* 4 个小图（grid 布局，每行 2 个） */}
        <Row gutter={[16, 16]}>
          {/* 1. 文档解析趋势 */}
          <Col xs={24} md={12}>
            <DocTrendChart kbs={kbs} />
          </Col>

          {/* 2. 评估指标趋势 */}
          <Col xs={24} md={12}>
            <EvalTrendChart evalRuns={evalRuns} />
          </Col>

          {/* 3. 反馈正负比环形图 */}
          <Col xs={24} md={12}>
            <FeedbackPieChart feedbackStats={feedbackStats} />
          </Col>

          {/* 4. 模型健康 */}
          <Col xs={24} md={12}>
            <ModelHealthCard models={models} />
          </Col>
        </Row>
      </div>
    </Spin>
  );
}
