import { memo, Fragment, type ReactNode, type KeyboardEvent } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Tag } from 'antd';

interface Props {
  content: string;
  /** 点击引用标记 [n] 时的回调 */
  onReferenceClick?: (refIndex: number) => void;
}

/**
 * 将文本中的 [数字] 引用标记渲染为可点击的 chip (Antd Tag)。
 * 没有匹配到的文本正常渲染。
 * 可点击时支持键盘访问 (Tab + Enter/Space)。
 */
function renderTextWithReferences(
  text: string,
  onReferenceClick?: (refIndex: number) => void,
): ReactNode[] {
  const regex = /\[(\d+)\]/g;
  const parts: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = regex.exec(text)) !== null) {
    // 匹配前的纯文本
    if (match.index > lastIndex) {
      parts.push(
        <Fragment key={`text-${key++}`}>{text.slice(lastIndex, match.index)}</Fragment>,
      );
    }
    // 引用 chip
    const refIndex = parseInt(match[1], 10);
    const clickable = !!onReferenceClick;
    parts.push(
      <Tag
        key={`ref-${key++}`}
        color="blue"
        role={clickable ? 'button' : undefined}
        tabIndex={clickable ? 0 : undefined}
        aria-label={clickable ? `引用 ${refIndex}` : undefined}
        style={{
          cursor: clickable ? 'pointer' : 'default',
          fontSize: 11,
          borderRadius: 10,
          padding: '0 6px',
          margin: '0 2px',
          lineHeight: '18px',
          display: 'inline-block',
          userSelect: 'none',
          verticalAlign: 'baseline',
        }}
        onClick={clickable ? () => onReferenceClick!(refIndex) : undefined}
        onKeyDown={
          clickable
            ? (e: KeyboardEvent<HTMLElement>) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onReferenceClick!(refIndex);
                }
              }
            : undefined
        }
      >
        {`[${refIndex}]`}
      </Tag>,
    );
    lastIndex = regex.lastIndex;
  }

  // 剩余文本
  if (lastIndex < text.length) {
    parts.push(<Fragment key={`text-${key++}`}>{text.slice(lastIndex)}</Fragment>);
  }

  return parts;
}

/**
 * 处理 react-markdown 传给 p/li 等组件的 children：
 * 把字符串子节点中的 [n] 替换为可点击 chip，其他子节点原样保留。
 */
function processChildren(
  children: ReactNode,
  onReferenceClick?: (refIndex: number) => void,
): ReactNode {
  if (typeof children === 'string') {
    return renderTextWithReferences(children, onReferenceClick);
  }
  if (Array.isArray(children)) {
    return children.map((child, idx) => {
      if (typeof child === 'string') {
        return (
          <Fragment key={`pc-${idx}`}>
            {renderTextWithReferences(child, onReferenceClick)}
          </Fragment>
        );
      }
      return child;
    });
  }
  return children;
}

function MarkdownRendererBase({ content, onReferenceClick }: Props) {
  const components: Components = {
    code({ className, children, ...props }) {
      const match = /language-(\w+)/.exec(className || '');
      const isBlock = !!match;
      return isBlock ? (
        <SyntaxHighlighter
          // react-syntax-highlighter 类型定义不精确，oneDark 实际为 Record<string, CSSProperties>
          style={oneDark as any}
          language={match![1]}
          PreTag="div"
          aria-label={`代码块 (${match![1]})`}
        >
          {String(children).replace(/\n$/, '')}
        </SyntaxHighlighter>
      ) : (
        <code className={className} {...props}>
          {children}
        </code>
      );
    },
    // 段落: 处理 [n] 引用
    p({ children, ...props }) {
      return <p {...props}>{processChildren(children, onReferenceClick)}</p>;
    },
    // 列表项: 处理 [n] 引用
    li({ children, ...props }) {
      return <li {...props}>{processChildren(children, onReferenceClick)}</li>;
    },
    // 表格单元格: 处理 [n] 引用
    td({ children, ...props }) {
      return <td {...props}>{processChildren(children, onReferenceClick)}</td>;
    },
    // 图片: 确保有 alt 文本（WCAG 1.1.1）
    img({ alt, src, ...props }) {
      return <img alt={alt || '无描述图片'} src={src} {...props} />;
    },
  };

  return (
    <div className="markdown-content">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

export const MarkdownRenderer = memo(MarkdownRendererBase);
