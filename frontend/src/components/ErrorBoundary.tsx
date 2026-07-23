import { Component, ErrorInfo, ReactNode } from 'react';
import { Result, Button, Typography } from 'antd';
import { reportError } from '../utils/errorReporter';
import { globalT } from '../i18n';

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
    // 上报到全局错误收集器（console + localStorage 面包屑，后续可接 Sentry）
    reportError(error, errorInfo);
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
            title={globalT('errorBoundary.title')}
            subTitle={this.state.error?.message || globalT('errorBoundary.unknownError')}
            extra={[
              <Button key="reload" type="primary" onClick={this.handleReload}>
                {globalT('errorBoundary.reload')}
              </Button>,
              <Button key="retry" onClick={this.handleReset}>
                {globalT('errorBoundary.retry')}
              </Button>,
            ]}
          >
            {isDev && this.state.error && (
              <div style={{ textAlign: 'left', maxWidth: 600, margin: '0 auto' }}>
                <Paragraph type="secondary" style={{ marginBottom: 8 }}>
                  {globalT('errorBoundary.detailsLabel')}
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
