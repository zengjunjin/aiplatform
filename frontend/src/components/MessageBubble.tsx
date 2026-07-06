import { memo } from 'react';
import { Avatar, Card, Tooltip, Button, Tag } from 'antd';
import { App as AntdApp } from 'antd';
import { User, Bot, Copy, RefreshCw } from 'lucide-react';
import { MarkdownRenderer } from './MarkdownRenderer';
import { copyToClipboard, formatTime } from '../utils/format';
import type { Reference } from '../types';

interface Props {
  role: 'user' | 'assistant';
  content: string;
  isStreaming?: boolean;
  references?: Reference[];
  createdAt?: string;
  onCopy?: () => void;
  onRegenerate?: () => void;
}

function MessageBubbleBase({
  role,
  content,
  isStreaming,
  references,
  createdAt,
  onRegenerate,
}: Props) {
  const { message } = AntdApp.useApp();
  const handleCopy = async () => {
    const ok = await copyToClipboard(content).catch(() => false);
    if (ok) {
      message.success('已复制');
    } else {
      message.error('复制失败');
    }
  };

  return (
    <div
      style={{
        display: 'flex',
        gap: 12,
        marginBottom: 24,
        flexDirection: role === 'user' ? 'row-reverse' : 'row',
      }}
    >
      <Avatar
        style={{
          backgroundColor: role === 'user' ? '#1677ff' : '#52c41a',
          flexShrink: 0,
        }}
        icon={role === 'user' ? <User size={18} /> : <Bot size={18} />}
      />
      <div style={{ maxWidth: '70%' }}>
        <Card
          size="small"
          style={{
            background: role === 'user' ? '#e6f4ff' : '#fff',
            border: 'none',
            boxShadow: '0 1px 2px rgba(0,0,0,0.06)',
          }}
        >
          {content ? (
            <MarkdownRenderer content={content} />
          ) : (
            isStreaming && (
              <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                <span className="thinking-dots">
                  <span></span>
                  <span></span>
                  <span></span>
                </span>
                <span style={{ color: '#999', fontSize: 13, marginLeft: 4 }}>
                  正在思考...
                </span>
              </div>
            )
          )}

          {role === 'assistant' && !isStreaming && content && (
            <div
              style={{
                marginTop: 8,
                paddingTop: 8,
                borderTop: '1px solid #f0f0f0',
                display: 'flex',
                gap: 8,
                fontSize: 12,
                color: '#999',
                alignItems: 'center',
              }}
            >
              <Tooltip title="复制">
                <Button
                  type="text"
                  size="small"
                  icon={<Copy size={14} />}
                  onClick={handleCopy}
                />
              </Tooltip>
              {onRegenerate && (
                <Tooltip title="重新生成">
                  <Button
                    type="text"
                    size="small"
                    icon={<RefreshCw size={14} />}
                    onClick={onRegenerate}
                  />
                </Tooltip>
              )}
              {references && references.length > 0 && (
                <Tag color="blue" style={{ marginLeft: 'auto' }}>
                  📚 {references.length} 个引用
                </Tag>
              )}
            </div>
          )}
        </Card>
        <div
          style={{
            fontSize: 11,
            color: '#bbb',
            marginTop: 4,
            textAlign: role === 'user' ? 'right' : 'left',
          }}
        >
          {createdAt ? formatTime(createdAt) : ''}
        </div>
      </div>
    </div>
  );
}

export const MessageBubble = memo(MessageBubbleBase);
