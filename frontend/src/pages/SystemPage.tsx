import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Tag,
  Row,
  Col,
  Skeleton,
  Result,
  Statistic,
  List,
  Empty,
  Space,
  Typography,
  Button,
} from 'antd';
import {
  Database as DatabaseIcon,
  DatabaseZap as RedisIcon,
  Bot as BotIcon,
  Layers as LayersIcon,
  Server as ServerIcon,
  RefreshCw,
  Activity as ActivityIcon,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { systemApi } from '../api';
import type { ExtendedSystemStatus } from '../api/system';
import { getErrorMessage } from '../utils/errorReporter';
import { isHealthy } from '../utils/health';

const { Title } = Typography;

interface ComponentConfig {
  key: 'postgresql' | 'redis' | 'ollama' | 'qdrant' | 'celery';
  labelKey: string;
  icon: React.ReactNode;
}

const COMPONENTS: ComponentConfig[] = [
  { key: 'postgresql', labelKey: 'system.components.postgresql', icon: <DatabaseIcon size={20} /> },
  { key: 'redis', labelKey: 'system.components.redis', icon: <RedisIcon size={20} /> },
  { key: 'ollama', labelKey: 'system.components.ollama', icon: <BotIcon size={20} /> },
  { key: 'qdrant', labelKey: 'system.components.qdrant', icon: <LayersIcon size={20} /> },
  { key: 'celery', labelKey: 'system.components.celery', icon: <ServerIcon size={20} /> },
];

export default function SystemPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<ExtendedSystemStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      // Task 30: 传递 signal 支持取消请求；signal 为空时保持单参数调用，兼容测试断言
      const data = (signal
        ? await systemApi.status(signal)
        : await systemApi.status()) as ExtendedSystemStatus;
      setStatus(data);
    } catch (e: unknown) {
      // 组件卸载 abort 后的 CanceledError 静默处理
      if (e instanceof Error && e.name === 'CanceledError') return;
      setError(getErrorMessage(e) || t('system.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  // Task 30: mount 时创建 AbortController，卸载时取消请求
  useEffect(() => {
    const controller = new AbortController();
    fetchStatus(controller.signal);
    return () => controller.abort();
  }, [fetchStatus]);

  if (loading && !status) {
    return (
      <div>
        <Title level={4} style={{ marginBottom: 24 }}>
          <Space>
            <ActivityIcon size={22} />
            <span>{t('system.title')}</span>
          </Space>
        </Title>
        <Skeleton active paragraph={{ rows: 8 }} />
      </div>
    );
  }

  if (error && !status) {
    return (
      <Result
        status="error"
        title={t('system.loadFailed')}
        subTitle={error}
        extra={
          <Button type="primary" onClick={() => fetchStatus()}>
            {t('common.confirm')}
          </Button>
        }
      />
    );
  }

  return (
    <div>
      <Title level={4} style={{ marginBottom: 24 }}>
        <Space>
          <ActivityIcon size={22} />
          <span>{t('system.title')}</span>
          <Button
            icon={<RefreshCw size={14} />}
            onClick={() => fetchStatus()}
            loading={loading}
            size="small"
          >
            {t('evaluation.refresh')}
          </Button>
        </Space>
      </Title>

      {/* 组件状态卡片网格 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        {COMPONENTS.map((cfg) => {
          const value = status?.[cfg.key];
          const healthy = isHealthy(value);
          return (
            <Col xs={24} sm={12} md={8} lg={6} xl={4} key={cfg.key}>
              <Card>
                <Statistic
                  title={
                    <Space>
                      {cfg.icon}
                      <span>{t(cfg.labelKey)}</span>
                    </Space>
                  }
                  valueRender={() => (
                    <Tag color={healthy ? 'green' : 'red'} style={{ fontSize: 14, padding: '2px 12px' }}>
                      {healthy ? t('system.status.healthy') : t('system.status.unhealthy')}
                    </Tag>
                  )}
                />
                {!healthy && value && (
                  <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
                    {value}
                  </div>
                )}
              </Card>
            </Col>
          );
        })}
      </Row>

      {/* 附加信息：ollama 模型 + qdrant collections + celery workers */}
      <Row gutter={[16, 16]}>
        <Col xs={24} md={8}>
          <Card title={t('system.ollamaModels')} style={{ height: '100%' }}>
            {status?.ollama_models && status.ollama_models.length > 0 ? (
              <List
                size="small"
                dataSource={status.ollama_models}
                renderItem={(name) => (
                  <List.Item>
                    <Tag color="blue">{name}</Tag>
                  </List.Item>
                )}
              />
            ) : (
              <Empty description={t('common.noData')} />
            )}
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card title={t('system.qdrantCollections')} style={{ height: '100%' }}>
            <Statistic
              value={status?.qdrant_collections ?? 0}
              suffix={t('system.collectionSuffix')}
            />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card title={t('system.celeryWorkers')} style={{ height: '100%' }}>
            {status?.celery_workers && status.celery_workers.length > 0 ? (
              <List
                size="small"
                dataSource={status.celery_workers}
                renderItem={(name) => (
                  <List.Item>
                    <Tag color="geekblue">{name}</Tag>
                  </List.Item>
                )}
              />
            ) : (
              <Empty description={t('common.noData')} />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
