import { Component, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  message: string;
}

/* 全局错误边界：任何渲染异常不至于白屏整个应用 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: '' };

  static getDerivedStateFromError(err: unknown): State {
    return { hasError: true, message: err instanceof Error ? err.message : String(err) };
  }

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div style={{
        minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', gap: 12, background: '#1a1a2e', color: '#e0e0e0',
        fontFamily: '-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif',
      }}>
        <div style={{ fontSize: 40 }}>💥</div>
        <div style={{ fontSize: 16, fontWeight: 600 }}>页面出现异常</div>
        <div style={{ fontSize: 12, color: '#94a3b8', maxWidth: 480, textAlign: 'center', padding: '0 24px' }}>
          {this.state.message || '未知错误'}
        </div>
        <button
          onClick={() => { this.setState({ hasError: false, message: '' }); }}
          style={{
            marginTop: 8, padding: '9px 28px', fontSize: 14, fontWeight: 600, color: '#fff',
            background: '#6366f1', border: 'none', borderRadius: 8, cursor: 'pointer',
          }}
        >
          重试
        </button>
      </div>
    );
  }
}
