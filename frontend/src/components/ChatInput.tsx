import { useState, useRef, useEffect } from 'react';
import { Input, Button, Space, Tag } from 'antd';
import { Send, StopCircle, BookOpen, Cpu } from 'lucide-react';

const { TextArea } = Input;

interface Props {
  onSend: (content: string) => void;
  onStop?: () => void;
  streaming: boolean;
  disabled?: boolean;
  placeholder?: string;
  /** 当前会话绑定的知识库名称（不传则显示"通用对话"） */
  kbName?: string;
  /** 当前使用的模型名称 */
  modelName?: string;
}

const MAX_LENGTH = 2000;
const DEFAULT_MODEL = 'Qwen2.5-7B';

export default function ChatInput({
  onSend,
  onStop,
  streaming,
  disabled,
  placeholder = '输入你的问题，Enter 发送，Shift+Enter 换行',
  kbName,
  modelName = DEFAULT_MODEL,
}: Props) {
  const [value, setValue] = useState('');
  const textAreaRef = useRef<HTMLTextAreaElement>(null);

  // 自动聚焦
  useEffect(() => {
    if (!streaming && !disabled) {
      textAreaRef.current?.focus();
    }
  }, [streaming, disabled]);

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed || streaming || disabled) return;
    onSend(trimmed);
    setValue('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div style={{ padding: '12px 24px', background: '#fff', borderTop: '1px solid #f0f0f0' }}>
      <div style={{ maxWidth: 900, margin: '0 auto' }}>
        <Space.Compact style={{ width: '100%' }}>
          <TextArea
            ref={textAreaRef as any}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            autoSize={{ minRows: 2, maxRows: 6 }}
            disabled={streaming || disabled}
            maxLength={MAX_LENGTH}
            style={{ borderRadius: '8px 0 0 8px' }}
          />
          {streaming ? (
            <Button
              danger
              icon={<StopCircle size={18} />}
              onClick={onStop}
              style={{ height: 'auto', borderRadius: '0 8px 8px 0' }}
            >
              停止
            </Button>
          ) : (
            <Button
              type="primary"
              icon={<Send size={18} />}
              onClick={handleSend}
              disabled={!value.trim() || disabled}
              style={{ height: 'auto', borderRadius: '0 8px 8px 0' }}
            >
              发送
            </Button>
          )}
        </Space.Compact>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            marginTop: 4,
            fontSize: 11,
            color: '#bbb',
          }}
        >
          <span>Enter 发送 · Shift+Enter 换行</span>
          <span>
            {value.length} / {MAX_LENGTH}
          </span>
        </div>
        {/* 底部状态栏: 左侧知识库 Tag, 右侧模型 Tag */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginTop: 8,
            paddingTop: 8,
            borderTop: '1px dashed #f0f0f0',
          }}
        >
          <Space size={6}>
            <BookOpen size={12} style={{ color: '#1677ff' }} />
            <Tag color="blue" style={{ margin: 0 }}>
              {kbName || '通用对话'}
            </Tag>
          </Space>
          <Space size={6}>
            <Cpu size={12} style={{ color: '#52c41a' }} />
            <Tag color="green" style={{ margin: 0 }}>
              {modelName}
            </Tag>
          </Space>
        </div>
      </div>
    </div>
  );
}
