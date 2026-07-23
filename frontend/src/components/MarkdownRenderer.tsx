import { memo, useMemo, Fragment, type ReactNode, type KeyboardEvent, type CSSProperties } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
// 使用 prism-light 仅打包按需注册的语言，避免引入全部 Prism 语言（节省约 700KB）
import SyntaxHighlighter from 'react-syntax-highlighter/dist/esm/prism-light';
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python';
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript';
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript';
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json';
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash';
import markdown from 'react-syntax-highlighter/dist/esm/languages/prism/markdown';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Tag } from 'antd';
import { globalT } from '../i18n';

// react-syntax-highlighter 的 style 类型定义不精确, oneDark 实际为 Record<string, CSSProperties>
// 显式断言为 SyntaxHighlighterProps.style 期望的类型, 避免 as any
const oneDarkStyle: { [key: string]: CSSProperties } = oneDark as { [key: string]: CSSProperties };

// 仅注册常用语言：未注册的 language 会以纯文本渲染（无高亮但不报错）
SyntaxHighlighter.registerLanguage('python', python);
SyntaxHighlighter.registerLanguage('javascript', javascript);
SyntaxHighlighter.registerLanguage('typescript', typescript);
SyntaxHighlighter.registerLanguage('json', json);
SyntaxHighlighter.registerLanguage('bash', bash);
SyntaxHighlighter.registerLanguage('markdown', markdown);

interface Props {
  content: string;
  /** 点击引用标记 [n] 时的回调 */
  onReferenceClick?: (refIndex: number) => void;
}

/**
 * URL 安全白名单：仅允许 http/https/mailto 协议。
 * 禁止 javascript:、data:、vbscript: 等 XSS 风险协议。
 * 相对 URL（如 `/foo`、`#anchor`）会被解析为当前 origin，可通过白名单。
 */
const SAFE_URL_PROTOCOLS = ['http:', 'https:', 'mailto:'];

const safeUrlTransform = (url: string): string => {
  try {
    const parsed = new URL(
      url,
      typeof window !== 'undefined' ? window.location.origin : 'http://localhost',
    );
    if (!SAFE_URL_PROTOCOLS.includes(parsed.protocol)) return '';
    return url;
  } catch {
    return '';
  }
};

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
        aria-label={clickable ? globalT('markdown.referenceLabel', { n: refIndex }) : undefined}
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

/**
 * 静态 Markdown 渲染规则（不依赖组件 props，提取到模块顶层避免每次渲染重建）。
 */
const staticMarkdownComponents: Components = {
  code({ className, children, ...props }) {
    const match = /language-(\w+)/.exec(className || '');
    if (match) {
      return (
        <SyntaxHighlighter
          style={oneDarkStyle}
          language={match[1]}
          PreTag="div"
          aria-label={globalT('markdown.codeBlockLabel', { lang: match[1] })}
        >
          {String(children).replace(/\n$/, '')}
        </SyntaxHighlighter>
      );
    }
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  },
  // 图片: 确保有 alt 文本（WCAG 1.1.1）
  img({ alt, src, ...props }) {
    return <img alt={alt || globalT('markdown.imageWithoutAlt')} src={src} {...props} />;
  },
};

function MarkdownRendererBase({ content, onReferenceClick }: Props) {
  /**
   * 依赖 onReferenceClick 的渲染规则用 useMemo 缓存，避免每次渲染都生成新函数引用
   * 导致 react-markdown 内部不必要的重渲染（对长文本/流式输出尤为关键）。
   */
  const components = useMemo<Components>(
    () => ({
      ...staticMarkdownComponents,
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
    }),
    [onReferenceClick],
  );

  return (
    <div className="markdown-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={safeUrlTransform}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export const MarkdownRenderer = memo(MarkdownRendererBase);
