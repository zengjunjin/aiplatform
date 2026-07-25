import { useState, useEffect, useMemo } from 'react';
import {
  Card,
  Button,
  Modal,
  Form,
  Input,
  Typography,
  Empty,
  Statistic,
  Row,
  Col,
  App as AntdApp,
  Spin,
} from 'antd';
import { Plus, FileText, Database, Layers, CalendarPlus } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import dayjs from 'dayjs';
import { useKBStore } from '../store/kb';
import { getErrorMessage, isFormValidationError } from '../utils/errorReporter';
import { useApiToast } from '../hooks/useApiToast';
import { KBCard } from './KnowledgeBasesPage.parts';

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

const { Title, Text } = Typography;
const { TextArea } = Input;

export default function KnowledgeBasesPage() {
  const { t } = useTranslation();
  // 精细化订阅
  const knowledgeBases = useKBStore((s) => s.knowledgeBases);
  const loading = useKBStore((s) => s.loading);
  const fetchKBs = useKBStore((s) => s.fetchKBs);
  const createKB = useKBStore((s) => s.createKB);
  const deleteKB = useKBStore((s) => s.deleteKB);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();
  const { runWithToast } = useApiToast();

  useEffect(() => {
    fetchKBs();
  }, [fetchKBs]);

  // Task 41: 顶部聚合统计 (总 KB / 总文档 / 总 chunk / 本周新增 KB)
  const aggregated = useMemo(() => {
    let totalDocs = 0;
    let totalChunks = 0;
    let weeklyNew = 0;
    const weekAgo = dayjs().subtract(7, 'day');
    // 近 7 天 KB 创建趋势 sparkline 数据: 按日统计新建 KB 数
    const dailyCounts: number[] = [];
    const dailyLabels: string[] = [];
    for (let i = 6; i >= 0; i--) {
      const day = dayjs().subtract(i, 'day');
      const next = day.add(1, 'day');
      const count = knowledgeBases.filter((kb) => {
        if (!kb.created_at) return false;
        const c = dayjs(kb.created_at);
        return c.isAfter(day.subtract(1, 'ms')) && c.isBefore(next);
      }).length;
      dailyCounts.push(count);
      dailyLabels.push(day.format('MM-DD'));
    }
    for (const kb of knowledgeBases) {
      totalDocs += kb.doc_count || 0;
      totalChunks += kb.chunk_count || 0;
      if (kb.created_at && dayjs(kb.created_at).isAfter(weekAgo)) {
        weeklyNew++;
      }
    }
    return { totalDocs, totalChunks, weeklyNew, dailyCounts, dailyLabels };
  }, [knowledgeBases]);

  // Task 41: sparkline option (近 7 天 KB 新建趋势)
  const sparklineOption = useMemo(() => {
    return {
      tooltip: { trigger: 'axis' as const },
      grid: { left: 0, right: 0, bottom: 0, top: 4, containLabel: false },
      xAxis: { type: 'category' as const, data: aggregated.dailyLabels, show: false },
      yAxis: { type: 'value' as const, show: false, minInterval: 1 },
      series: [
        {
          type: 'line',
          data: aggregated.dailyCounts,
          smooth: true,
          symbol: 'none',
          areaStyle: { opacity: 0.25 },
          lineStyle: { width: 2 },
          itemStyle: { color: '#3b82f6' },
        },
      ],
    };
  }, [aggregated]);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      await createKB(values.name, values.description || '');
      message.success(t('kb.createSuccess'));
      setModalOpen(false);
      form.resetFields();
    } catch (e: unknown) {
      if (isFormValidationError(e)) return; // 表单验证错误
      message.error(getErrorMessage(e) || t('kb.createFailed'));
      setModalOpen(false);
    }
  };

  const handleDelete = async (id: number, _name: string) => {
    await runWithToast(() => deleteKB(id), {
      successKey: 'kb.deleteSuccess',
      errorKey: 'kb.deleteFailed',
    });
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>
          {t('kb.myKnowledgeBases')}
        </Title>
        <Button type="primary" icon={<Plus size={16} />} onClick={() => setModalOpen(true)}>
          {t('kb.newKnowledgeBase')}
        </Button>
      </div>

      {/* Task 41: 顶部聚合统计 4 卡 + 近 7 天 KB 新建 sparkline */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title={t('kb.totalKBs')}
              value={knowledgeBases.length}
              prefix={<Database size={16} />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title={t('kb.totalDocs')}
              value={aggregated.totalDocs}
              prefix={<FileText size={16} />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title={t('kb.totalChunks')}
              value={aggregated.totalChunks}
              prefix={<Layers size={16} />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title={t('kb.weeklyNewKBs')}
              value={aggregated.weeklyNew}
              prefix={<CalendarPlus size={16} />}
              valueStyle={{ color: 'var(--accent-success)' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 近 7 天 KB 新建趋势 sparkline (KB 数 > 0 时显示) */}
      {knowledgeBases.length > 0 && (
        <Card size="small" style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <div style={{ flexShrink: 0 }}>
              <Text style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
                {t('kb.weeklyNewTrend')}
              </Text>
            </div>
            <div style={{ flex: 1, height: 48 }}>
              <ReactEChartsCore
                echarts={echarts}
                option={sparklineOption}
                style={{ height: '100%', width: '100%' }}
                opts={{ renderer: 'canvas' }}
              />
            </div>
          </div>
        </Card>
      )}

      <Spin spinning={loading}>
        {knowledgeBases.length === 0 ? (
          <Empty description={t('kb.noKBs')}>
            <Button type="primary" onClick={() => setModalOpen(true)}>
              {t('kb.createFirstKB')}
            </Button>
          </Empty>
        ) : (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
              gap: 16,
            }}
          >
            {knowledgeBases.map((kb) => (
              <KBCard
                key={kb.id}
                kb={kb}
                onNavigate={(id) => navigate(`/knowledge-bases/${id}`)}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}
      </Spin>

      <Modal
        title={t('kb.newKnowledgeBase')}
        open={modalOpen}
        onOk={handleCreate}
        onCancel={() => setModalOpen(false)}
        transitionName=""
        maskTransitionName=""
        okText={t('kb.create')}
        cancelText={t('kb.cancel')}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label={t('kb.kbName')}
            rules={[{ required: true, message: t('kb.kbNameRequired') }]}
          >
            <Input placeholder={t('kb.kbNamePlaceholder')} maxLength={100} />
          </Form.Item>
          <Form.Item name="description" label={t('kb.description')}>
            <TextArea rows={3} placeholder={t('kb.descriptionPlaceholder')} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
