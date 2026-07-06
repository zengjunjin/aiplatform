import { useState, useEffect } from 'react';
import {
  Table,
  Tag,
  Button,
  Space,
  Switch,
  Popconfirm,
  App as AntdApp,
  Card,
  Skeleton,
  Empty,
} from 'antd';
import { Users, Shield, UserX } from 'lucide-react';
import { usersApi } from '../api';
import { useAuthStore } from '../store/auth';
import type { User } from '../types';

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(false);
  const currentUser = useAuthStore((s) => s.user);
  const { message } = AntdApp.useApp();

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const data = await usersApi.list({ page: 1, page_size: 50 });
      setUsers(data.items || (data as any) || []);
    } catch (e: any) {
      message.error(e.message || '获取用户列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const handleRoleChange = async (userId: number, role: 'user' | 'admin') => {
    try {
      await usersApi.updateRole(userId, role);
      message.success('角色已更新');
      fetchUsers();
    } catch (e: any) {
      message.error(e.message || '操作失败');
    }
  };

  const handleStatusChange = async (userId: number, active: boolean) => {
    try {
      await usersApi.updateStatus(userId, active);
      message.success(active ? '用户已启用' : '用户已禁用');
      fetchUsers();
    } catch (e: any) {
      message.error(e.message || '操作失败');
    }
  };

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 80,
    },
    {
      title: '用户名',
      dataIndex: 'username',
      key: 'username',
    },
    {
      title: '邮箱',
      dataIndex: 'email',
      key: 'email',
    },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      render: (role: string) => (
        <Tag color={role === 'admin' ? 'red' : 'blue'}>
          {role === 'admin' ? '管理员' : '普通用户'}
        </Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active: boolean) => (
        <Tag color={active ? 'green' : 'default'}>
          {active ? '正常' : '禁用'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 280,
      render: (_: any, record: User) => (
        <Space>
          {record.id === currentUser?.id ? (
            <Tag color="default">当前用户</Tag>
          ) : (
            <>
              <Popconfirm
                title={`确定将用户设为${record.role === 'admin' ? '普通用户' : '管理员'}？`}
                onConfirm={() => handleRoleChange(record.id, record.role === 'admin' ? 'user' : 'admin')}
                okText="确定"
                cancelText="取消"
              >
                <Button
                  type="link"
                  size="small"
                  icon={<Shield size={14} />}
                >
                  {record.role === 'admin' ? '取消管理员' : '设为管理员'}
                </Button>
              </Popconfirm>
              <Popconfirm
                title={record.is_active ? '确定禁用该用户？' : '确定启用该用户？'}
                description={record.is_active ? '禁用后用户将无法登录' : ''}
                onConfirm={() => handleStatusChange(record.id, !record.is_active)}
                okText="确定"
                cancelText="取消"
              >
                <Button
                  type="link"
                  size="small"
                  danger={record.is_active}
                  icon={<UserX size={14} />}
                >
                  {record.is_active ? '禁用' : '启用'}
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
            <span>用户管理</span>
            <Tag color="blue">{users.length} 个用户</Tag>
          </Space>
        }
      >
        {loading ? (
          <Skeleton active paragraph={{ rows: 8 }} />
        ) : users.length === 0 ? (
          <Empty description="暂无用户" />
        ) : (
          <Table
            dataSource={users}
            columns={columns}
            rowKey="id"
            pagination={{ pageSize: 20 }}
          />
        )}
      </Card>
    </div>
  );
}
