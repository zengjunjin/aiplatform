import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Table,
  Tag,
  Button,
  Space,
  Popconfirm,
  App as AntdApp,
  Card,
  Skeleton,
  Empty,
} from 'antd';
import { Users, Shield, UserX } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { usersApi } from '../api';
import { useAuthStore } from '../store/auth';
import type { User } from '../types';
import { getErrorMessage } from '../utils/errorReporter';
import { useApiToast } from '../hooks/useApiToast';

export default function UsersPage() {
  const { t } = useTranslation();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(100);
  const [total, setTotal] = useState(0);
  const currentUser = useAuthStore((s) => s.user);
  const { message } = AntdApp.useApp();
  const { runWithToast } = useApiToast();

  const fetchUsers = useCallback(async (p = page, ps = pageSize, signal?: AbortSignal) => {
    setLoading(true);
    try {
      const data = await usersApi.list({ page: p, page_size: ps }, signal);
      if (signal?.aborted) return;
      setUsers(data.items || []);
      setTotal(data.total || 0);
    } catch (e: unknown) {
      if (signal?.aborted) return;
      message.error(getErrorMessage(e) || t('user.loadFailed'));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [page, pageSize, message, t]);

  // Task 45: 使用 fetchUsersRef 模式避免 useEffect 依赖告警
  // (参考 DocumentsPage.tsx 的 fetchDocumentsRef 模式)
  const fetchUsersRef = useRef(fetchUsers);
  fetchUsersRef.current = fetchUsers;

  // Task 23 (P1-FE-09): AbortController 防止组件卸载后 setState
  useEffect(() => {
    const abortController = new AbortController();
    fetchUsersRef.current(page, pageSize, abortController.signal);
    return () => { abortController.abort(); };
  }, []);

  const handleRoleChange = async (userId: number, role: 'user' | 'admin') => {
    await runWithToast(() => usersApi.updateRole(userId, role), {
      successKey: 'user.roleUpdated',
      errorKey: 'user.operationFailed',
      onSuccess: () => fetchUsers(page, pageSize),
    });
  };

  const handleStatusChange = async (userId: number, active: boolean) => {
    try {
      await usersApi.updateStatus(userId, active);
      message.success(active ? t('user.userEnabled') : t('user.userDisabled'));
      fetchUsers(page, pageSize);
    } catch (e: unknown) {
      message.error(getErrorMessage(e) || t('user.operationFailed'));
    }
  };

  const columns = [
    {
      title: t('user.id'),
      dataIndex: 'id',
      key: 'id',
      width: 80,
    },
    {
      title: t('user.username'),
      dataIndex: 'username',
      key: 'username',
    },
    {
      title: t('user.email'),
      dataIndex: 'email',
      key: 'email',
    },
    {
      title: t('user.role'),
      dataIndex: 'role',
      key: 'role',
      render: (role: string) => (
        <Tag color={role === 'admin' ? 'red' : 'blue'}>
          {role === 'admin' ? t('user.admin') : t('user.normalUser')}
        </Tag>
      ),
    },
    {
      title: t('user.status'),
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active: boolean) => (
        <Tag color={active ? 'green' : 'default'}>
          {active ? t('user.active') : t('user.disabled')}
        </Tag>
      ),
    },
    {
      title: t('user.actions'),
      key: 'actions',
      width: 280,
      render: (_: unknown, record: User) => (
        <Space>
          {record.id === currentUser?.id ? (
            <Tag color="default">{t('user.currentUser')}</Tag>
          ) : (
            <>
              <Popconfirm
                title={record.role === 'admin' ? t('user.setUserConfirm') : t('user.setAdminConfirm')}
                onConfirm={() => handleRoleChange(record.id, record.role === 'admin' ? 'user' : 'admin')}
                okText={t('user.confirm')}
                cancelText={t('user.cancel')}
              >
                <Button
                  type="link"
                  size="small"
                  icon={<Shield size={14} />}
                >
                  {record.role === 'admin' ? t('user.removeAdmin') : t('user.setAdmin')}
                </Button>
              </Popconfirm>
              <Popconfirm
                title={record.is_active ? t('user.disableConfirm') : t('user.enableConfirm')}
                description={record.is_active ? t('user.disableHint') : ''}
                onConfirm={() => handleStatusChange(record.id, !record.is_active)}
                okText={t('user.confirm')}
                cancelText={t('user.cancel')}
              >
                <Button
                  type="link"
                  size="small"
                  danger={record.is_active}
                  icon={<UserX size={14} />}
                >
                  {record.is_active ? t('user.disable') : t('user.enable')}
                </Button>
              </Popconfirm>
            </>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Card
        title={
          <Space>
            <Users size={20} />
            <span>{t('user.management')}</span>
            <Tag color="blue">{t('user.userCount', { count: total })}</Tag>
          </Space>
        }
      >
        {loading ? (
          <Skeleton active paragraph={{ rows: 8 }} />
        ) : users.length === 0 ? (
          <Empty description={t('user.noUsers')} />
        ) : (
          <Table
            dataSource={users}
            columns={columns}
            rowKey="id"
            pagination={{
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              onChange: (p, ps) => {
                setPage(p);
                setPageSize(ps);
                fetchUsers(p, ps);
              },
            }}
          />
        )}
      </Card>
    </div>
  );
}
