import { useMemo } from 'react';
import { Card, Col, Row, Statistic } from 'antd';
import { AlertCircle, HardDrive } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { PieChart, BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { formatFileSize, getStatusTextKey } from '../utils/format';
import type { Document } from '../types';

echarts.use([PieChart, BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

export interface DocumentsStatsRowProps {
  documents: Document[];
}

// ===== DocumentsStatsRow: 顶部聚合统计 (状态环形图 + 类型横向条形图 + 总大小 Statistic) =====
// Task 59: 基于当前页 documents 列表聚合统计
export function DocumentsStatsRow({ documents }: DocumentsStatsRowProps) {
  const { t } = useTranslation();

  const stats = useMemo(() => {
    const statusCounts: Record<string, number> = {};
    const typeCounts: Record<string, number> = {};
    let totalSize = 0;
    let failedCount = 0;
    for (const doc of documents) {
      statusCounts[doc.status] = (statusCounts[doc.status] || 0) + 1;
      const ft = (doc.file_type || 'unknown').toLowerCase();
      typeCounts[ft] = (typeCounts[ft] || 0) + 1;
      totalSize += doc.file_size || 0;
      if (doc.status === 'failed') failedCount++;
    }
    return { statusCounts, typeCounts, totalSize, failedCount };
  }, [documents]);

  // 状态环形图 ECharts 配置
  const statusPieOption = useMemo(() => {
    const statusColorMap: Record<string, string> = {
      pending: '#94a3b8',
      parsing: '#3b82f6',
      chunking: '#8b5cf6',
      embedding: '#f59e0b',
      done: '#10b981',
      failed: '#ef4444',
    };
    const data = Object.entries(stats.statusCounts).map(([name, value]) => ({
      name: getStatusTextKey(name),
      value,
      itemStyle: { color: statusColorMap[name] || '#94a3b8' },
    }));
    return {
      tooltip: { trigger: 'item' as const, formatter: '{b}: {c} ({d}%)' },
      legend: { bottom: 0, type: 'scroll' as const, textStyle: { fontSize: 11 } },
      series: [
        {
          type: 'pie',
          radius: ['45%', '70%'],
          center: ['50%', '42%'],
          avoidLabelOverlap: true,
          label: { show: false },
          labelLine: { show: false },
          data: data.length > 0 ? data : [{ name: t('common.noData'), value: 1, itemStyle: { color: '#e2e8f0' } }],
        },
      ],
    };
  }, [stats, t]);

  // 类型横向条形图 ECharts 配置
  const typeBarOption = useMemo(() => {
    const entries = Object.entries(stats.typeCounts).sort((a, b) => b[1] - a[1]);
    const categories = entries.map(([k]) => k.toUpperCase());
    const values = entries.map(([, v]) => v);
    return {
      tooltip: { trigger: 'axis' as const, axisPointer: { type: 'shadow' as const } },
      grid: { left: '3%', right: '8%', bottom: '3%', top: '3%', containLabel: true },
      xAxis: { type: 'value' as const, minInterval: 1 },
      yAxis: {
        type: 'category' as const,
        data: categories.length > 0 ? categories : [t('common.noData')],
      },
      series: [
        {
          type: 'bar',
          data: values.length > 0 ? values : [0],
          itemStyle: { color: '#3b82f6', borderRadius: [0, 4, 4, 0] },
          barMaxWidth: 18,
        },
      ],
    };
  }, [stats, t]);

  return (
    <Row gutter={16} style={{ marginBottom: 16 }}>
      <Col xs={24} sm={8}>
        <Card size="small" title={t('document.statsStatus')}>
          <ReactEChartsCore
            echarts={echarts}
            option={statusPieOption}
            style={{ height: 180, width: '100%' }}
            opts={{ renderer: 'canvas' }}
          />
        </Card>
      </Col>
      <Col xs={24} sm={8}>
        <Card size="small" title={t('document.statsType')}>
          <ReactEChartsCore
            echarts={echarts}
            option={typeBarOption}
            style={{ height: 180, width: '100%' }}
            opts={{ renderer: 'canvas' }}
          />
        </Card>
      </Col>
      <Col xs={24} sm={8}>
        <Card size="small" title={t('document.statsTotalSize')}>
          <div style={{ height: 180, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 16 }}>
            <Statistic
              value={formatFileSize(stats.totalSize)}
              prefix={<HardDrive size={16} />}
            />
            {stats.failedCount > 0 && (
              <Statistic
                title={t('document.statsFailedBadge')}
                value={stats.failedCount}
                valueStyle={{ color: 'var(--accent-danger)' }}
                prefix={<AlertCircle size={16} />}
              />
            )}
          </div>
        </Card>
      </Col>
    </Row>
  );
}
