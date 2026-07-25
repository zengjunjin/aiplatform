import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import type { KnowledgeBase } from '../types';

type TFunction = ReturnType<typeof useTranslation>['t'];

export interface KbOption {
  label: string;
  value: number;
}

/**
 * 知识库下拉选项构建 hook
 * 抽取自 DocumentsPage / NewSessionModal 中重复的 useMemo(knowledgeBases.map(...)) 逻辑，
 * 消除两处完全相同的 label 拼接代码。
 *
 * @param knowledgeBases 知识库列表
 * @param t i18n 翻译函数（来自 useTranslation()）
 * @param withDocCount 是否在 label 中包含文档数（默认 true，保持与原实现一致）
 */
export function useKbOptions(
  knowledgeBases: KnowledgeBase[],
  t: TFunction,
  withDocCount: boolean = true,
): KbOption[] {
  return useMemo(
    () =>
      knowledgeBases.map((kb) => ({
        label: withDocCount
          ? `${kb.name} (${kb.doc_count || 0} ${t('kb.documents', { count: kb.doc_count || 0 })})`
          : kb.name,
        value: kb.id,
      })),
    [knowledgeBases, t, withDocCount],
  );
}
