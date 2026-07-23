import { Breadcrumb, Typography, Space, Button } from 'antd';
import { Edit3, Users, RefreshCw, Upload as UploadIcon } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { KnowledgeBase } from '../types';

const { Title, Text } = Typography;

interface Props {
  kb?: KnowledgeBase;
  loading: boolean;
  onEditClick: () => void;
  onCollabClick: () => void;
  onRefreshClick: () => void;
  onUploadClick: () => void;
}

/**
 * 知识库详情页头部 (面包屑 + 标题 + 操作按钮): 从 KnowledgeBaseDetailPage 拆出 (Task 27.1)
 */
export default function KBBreadcrumbHeader({
  kb,
  loading,
  onEditClick,
  onCollabClick,
  onRefreshClick,
  onUploadClick,
}: Props) {
  const { t } = useTranslation();

  return (
    <>
      <Breadcrumb style={{ marginBottom: 16 }}>
        <Breadcrumb.Item>
          <Link to="/knowledge-bases">{t('kb.kb')}</Link>
        </Breadcrumb.Item>
        <Breadcrumb.Item>{kb?.name || t('common.loading')}</Breadcrumb.Item>
      </Breadcrumb>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            {kb?.name || t('common.loading')}
          </Title>
          <Text type="secondary">{kb?.description || ''}</Text>
        </div>
        <Space>
          <Button icon={<Edit3 size={16} />} onClick={onEditClick}>
            {t('kb.edit')}
          </Button>
          <Button icon={<Users size={16} />} onClick={onCollabClick}>
            {t('kb.collaborators')}
          </Button>
          <Button
            icon={<RefreshCw size={16} />}
            onClick={onRefreshClick}
            loading={loading}
          >
            {t('kb.refresh')}
          </Button>
          <Button type="primary" icon={<UploadIcon size={16} />} onClick={onUploadClick}>
            {t('kb.uploadDocument')}
          </Button>
        </Space>
      </div>
    </>
  );
}
