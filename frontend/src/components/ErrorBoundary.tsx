import { Component, ErrorInfo, ReactNode } from 'react';
import { Result, Button, Typography } from 'antd';

const { Paragraph } = Typography;

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onReset?: () => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error);
    console.error('Component stack:', errorInfo.componentStack);
    this.setState({ errorInfo });
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
    if (this.props.onReset) {
      this.props.onReset();
    }
  };

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const isDev = import.meta.env.DEV;

      return (
        <div style={{ padding: 48, display: 'flex', justifyContent: 'center' }}>
          <Result
            status="error"
            title="页面出错了"
            subTitle={this.state.error?.message || '发生了未知错误，请刷新页面重试'}
            extra={[
              <Button key="reload" type="primary" onClick={this.handleReload}>
                刷新页面
              </Button>,
              <Button key="retry" onClick={this.handleReset}>
                重试
              </Button>,
            ]}
          >
            {isDev && this.state.error && (
              <div style={{ textAlign: 'left', maxWidth: 600, margin: '0 auto' }}>
                <Paragraph type="secondary" style={{ marginBottom: 8 }}>
                  错误详情（仅供参考）：
                </Paragraph>
                <pre
                  style={{
                    background: 'var(--bg-tertiary)',
                    padding: 16,
                    borderRadius: 8,
                    overflow: 'auto',
                    maxHeight: 200,
                    fontSize: 12,
                    color: 'var(--text-secondary)',
                  }}
                >
                  {this.state.error.toString()}
                </pre>
              </div>
            )}
          </Result>
        </div>
      );
    }

    return this.props.children;
  }
}
