import { useState, useCallback, useEffect, useRef } from 'react';
import {
  Modal,
  Divider,
  Form,
  AutoComplete,
  Select,
  Button,
  Tag,
  Empty,
  List,
  Avatar,
  Popconfirm,
  Skeleton,
  App as AntdApp,
} from 'antd';
import { Users, UserPlus, UserX } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { kbApi } from '../api';
import authApi from '../api/auth';
import type { CollaboratorInfo } from '../types';
import { getErrorMessage, isFormValidationError } from '../utils/errorReporter';
import { useApiToast } from '../hooks/useApiToast';

interface Props {
  open: boolean;
  kbId: number;
  onClose: () => void;
}

/**
 * 知识库协作者管理 Modal: 从 KnowledgeBaseDetailPage 拆出 (Task 27.1)
 * 内部维护 collaborators/userOptions/searching/addCollabForm 状态, open 变 true 时自动拉取协作者列表.
 */
export default function KBCollaboratorModal({ open, kbId, onClose }: Props) {
  const { t } = useTranslation();
  const { message } = AntdApp.useApp();
  const { runWithToast } = useApiToast();
  const [collaborators, setCollaborators] = useState<CollaboratorInfo[]>([]);
  const [collabLoading, setCollabLoading] = useState(false);
  const [userOptions, setUserOptions] = useState<{ value: number; label: string }[]>([]);
  const [searching, setSearching] = useState(false);
  const [addCollabForm] = Form.useForm();
  // debounce 计时器 ref: 用户搜索 300ms 防抖, 避免每次按键都发请求
  const searchTimerRef = useRef<ReturnType<typeof setTimeout>>();

  const fetchCollaborators = useCallback(async () => {
    setCollabLoading(true);
    try {
      const data = await kbApi.getCollaborators(kbId);
      setCollaborators(data);
    } catch (e: unknown) {
      message.error(getErrorMessage(e) || t('errors.loadCollaboratorsFailed'));
    } finally {
      setCollabLoading(false);
    }
  }, [kbId, message, t]);

  // open 变 true 时拉取协作者列表 (替代原 handleOpenCollab 内的 fetchCollaborators 调用)
  useEffect(() => {
    if (open) {
      fetchCollaborators();
    }
  }, [open, fetchCollaborators]);

  // 组件卸载时清理 debounce 计时器, 避免在已卸载组件上 setState
  useEffect(() => {
    return () => {
      if (searchTimerRef.current) {
        clearTimeout(searchTimerRef.current);
      }
    };
  }, []);

  // handleUserSearch: 300ms 防抖包裹, 避免用户快速输入时每个按键都触发一次搜索请求
  const handleUserSearch = useCallback((query: string) => {
    if (searchTimerRef.current) {
      clearTimeout(searchTimerRef.current);
    }
    if (!query || query.length < 1) {
      setUserOptions([]);
      return;
    }
    searchTimerRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const users = await authApi.searchUsers(query);
        setUserOptions(users.map((u) => ({ value: u.id, label: `${u.username} (ID: ${u.id})` })));
      } catch {
        setUserOptions([]);
      } finally {
        setSearching(false);
      }
    }, 300);
  }, []);

  const handleAddCollaborator = async () => {
    try {
      const values = await addCollabForm.validateFields();
      await kbApi.addCollaborator(kbId, values);
      message.success(t('kb.collaboratorAdded'));
      addCollabForm.resetFields();
      fetchCollaborators();
    } catch (e: unknown) {
      if (isFormValidationError(e)) return;
      message.error(getErrorMessage(e) || t('kb.operationFailed'));
    }
  };

  const handleRemoveCollaborator = async (userId: number) => {
    await runWithToast(() => kbApi.removeCollaborator(kbId, userId), {
      successKey: 'kb.collaboratorRemoved',
      errorKey: 'kb.operationFailed',
      onSuccess: () => fetchCollaborators(),
    });
  };

  const handleClose = () => {
    addCollabForm.resetFields();
    onClose();
  };

  return (
    <Modal
      title={t('kb.collaborators')}
      open={open}
      onCancel={handleClose}
      transitionName=""
      maskTransitionName=""
      footer={null}
      width={500}
    >
      <Divider orientation="left" style={{ fontSize: 13, marginTop: 0 }}>
        {t('kb.addCollaborator')}
      </Divider>
      <Form form={addCollabForm} layout="inline" style={{ marginBottom: 16 }}>
        <Form.Item
          name="user_id"
          rules={[{ required: true, message: t('kb.userIdRequired') }]}
        >
          <AutoComplete
            options={userOptions}
            onSearch={handleUserSearch}
            placeholder={t('kb.userSearchPlaceholder')}
            style={{ width: 200 }}
            notFoundContent={searching ? t('kb.searching') : t('kb.noUserFound')}
          />
        </Form.Item>
        <Form.Item
          name="permission"
          rules={[{ required: true, message: t('kb.permissionRequired') }]}
        >
          <Select style={{ width: 120 }} placeholder={t('kb.permission')}>
            <Select.Option value="read">{t('kb.permRead')}</Select.Option>
            <Select.Option value="write">{t('kb.permWrite')}</Select.Option>
            <Select.Option value="admin">{t('kb.permAdmin')}</Select.Option>
          </Select>
        </Form.Item>
        <Form.Item>
          <Button type="primary" icon={<UserPlus size={14} />} onClick={handleAddCollaborator}>
            {t('kb.add')}
          </Button>
        </Form.Item>
      </Form>

      <Divider orientation="left" style={{ fontSize: 13 }}>
        {t('kb.currentCollaborators')}
      </Divider>
      {collabLoading ? (
        <Skeleton active paragraph={{ rows: 3 }} />
      ) : collaborators.length === 0 ? (
        <Empty description={t('kb.noCollaborators')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <List
          dataSource={collaborators}
          renderItem={(item: CollaboratorInfo) => (
            <List.Item
              actions={[
                <Popconfirm
                  key="remove"
                  title={t('kb.removeCollaboratorConfirm')}
                  onConfirm={() => handleRemoveCollaborator(item.user_id)}
                  okText={t('kb.delete')}
                  cancelText={t('kb.cancel')}
                >
                  <Button size="small" danger icon={<UserX size={14} />} aria-label={t('kb.removeCollaborator')} />
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                avatar={<Avatar icon={<Users size={16} />} />}
                title={item.username}
                description={
                  <Tag color={item.permission === 'admin' ? 'red' : item.permission === 'write' ? 'blue' : 'default'}>
                    {item.permission === 'admin' ? t('kb.permAdmin') : item.permission === 'write' ? t('kb.permWrite') : t('kb.permRead')}
                  </Tag>
                }
              />
            </List.Item>
          )}
        />
      )}
    </Modal>
  );
}
