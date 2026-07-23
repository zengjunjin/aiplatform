import { useMemo } from 'react';
import { Card, Select, DatePicker, Space } from 'antd';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';
import type { KnowledgeBase } from '../../types';
import { FEEDBACK_TYPE_LABELS } from '../../constants/feedback';

const { RangePicker } = DatePicker;

interface FeedbackFilterBarProps {
  knowledgeBases: KnowledgeBase[];
  selectedKbId: number | undefined;
  dateRange: [dayjs.Dayjs, dayjs.Dayjs] | null;
  selectedType: string | undefined;
  onKbChange: (val: number | undefined) => void;
  onDateRangeChange: (dates: [dayjs.Dayjs, dayjs.Dayjs] | null) => void;
  onTypeChange: (val: string | undefined) => void;
}

/**
 * Task 4.2: 从 FeedbackPage 抽出的筛选条件栏。
 * Task 5.6: kbOptions 和 typeOptions 用 useMemo 缓存。
 */
export default function FeedbackFilterBar({
  knowledgeBases,
  selectedKbId,
  dateRange,
  selectedType,
  onKbChange,
  onDateRangeChange,
  onTypeChange,
}: FeedbackFilterBarProps) {
  const { t } = useTranslation();

  // Task 5.6: kbOptions useMemo 缓存
  const kbOptions = useMemo(
    () => knowledgeBases.map((kb) => ({ label: kb.name, value: kb.id })),
    [knowledgeBases],
  );

  // Task 5.6: typeOptions useMemo 缓存
  const typeOptions = useMemo(
    () =>
      Object.entries(FEEDBACK_TYPE_LABELS).map(([value, label]) => ({
        label: t(label),
        value,
      })),
    [t],
  );

  return (
    <Card style={{ marginBottom: 24 }}>
      <Space wrap>
        <Select
          placeholder={t('feedback.filterByKB')}
          allowClear
          style={{ width: 200 }}
          value={selectedKbId}
          onChange={onKbChange}
          options={kbOptions}
        />
        <RangePicker
          value={dateRange}
          onChange={(dates) => {
            onDateRangeChange(dates as [dayjs.Dayjs, dayjs.Dayjs] | null);
          }}
        />
        <Select
          placeholder={t('feedback.filterByType')}
          allowClear
          style={{ width: 180 }}
          value={selectedType}
          onChange={onTypeChange}
          options={typeOptions}
        />
      </Space>
    </Card>
  );
}
