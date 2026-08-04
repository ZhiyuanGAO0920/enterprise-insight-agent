import { useState, useCallback, useRef } from 'react';
import type { DataSource } from '../lib/report';

interface SSEEvent {
  type: 'step' | 'phase' | 'token' | 'done' | 'heartbeat';
  node?: string;
  status?: string;
  label?: string;
  message?: string;
  text?: string;
  report?: string;
  errors?: { dimension?: string }[];
  reflection_passed?: boolean;
  record_id?: number;
  data_sources?: DataSource[];
  followup_questions?: string[];
  supervisor_plan?: string | null;
}

/* 无数据看门狗：超过该时长没有收到任何字节则判定连接挂死 */
const WATCHDOG_MS = 45_000;

export function useSSE() {
  const [steps, setSteps] = useState<Record<string, string>>({});
  const [phaseTitle, setPhaseTitle] = useState('');
  const [streamText, setStreamText] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [finalData, setFinalData] = useState<SSEEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const watchdogRef = useRef<number | null>(null);
  const timedOutRef = useRef(false);

  const analyze = useCallback(async (question: string, sessionId: string | null) => {
    setIsStreaming(true);
    setStreamText('');
    setSteps({});
    setPhaseTitle('');
    setFinalData(null);
    setError(null);
    timedOutRef.current = false;

    const controller = new AbortController();
    abortRef.current = controller;

    const clearWatchdog = () => {
      if (watchdogRef.current !== null) {
        clearTimeout(watchdogRef.current);
        watchdogRef.current = null;
      }
    };
    const armWatchdog = () => {
      clearWatchdog();
      watchdogRef.current = window.setTimeout(() => {
        timedOutRef.current = true;
        controller.abort();
      }, WATCHDOG_MS);
    };

    try {
      const res = await fetch('/api/v1/analysis/analyze-stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('token')}`,
        },
        body: JSON.stringify({ question, session_id: sessionId }),
        signal: controller.signal,
      });

      // 非 2xx：读出后端 detail 展示真实原因（401/500 不再静默）
      if (!res.ok) {
        let detail = '';
        try {
          const data = await res.json();
          detail = data?.detail || '';
        } catch { /* 响应体非 JSON */ }
        throw new Error(detail || `分析请求失败（HTTP ${res.status}）`);
      }

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      // 首字节也受看门狗保护（LLM 首 token 延迟 10-20s 属正常）
      armWatchdog();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        armWatchdog();
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const event: SSEEvent = JSON.parse(line.slice(6));
            if (event.type === 'heartbeat') continue; /* 后端心跳保活事件，仅用于重置看门狗，忽略内容 */
            if (event.type === 'step' || event.type === 'phase') {
              setSteps((prev) => ({
                ...prev,
                [event.node!]: event.status === 'done' ? 'done' : 'active',
              }));
              /* 阶段开始文案（对齐原生 #pT 标题） */
              if (event.type === 'phase' && event.status === 'start' && event.message) {
                setPhaseTitle(event.message);
              }
            } else if (event.type === 'token') {
              setStreamText((prev) => prev + (event.text || ''));
            } else if (event.type === 'done') {
              setFinalData(event);
            }
          } catch { /* 单条事件解析失败丢弃，不中断流 */ }
        }
      }
    } catch (err: unknown) {
      if (timedOutRef.current) {
        setError('分析超时（45 秒无响应），请重试');
      } else if (err instanceof DOMException && err.name === 'AbortError') {
        /* 用户主动停止：静默 */
      } else if (err instanceof TypeError) {
        setError('网络连接失败，请确认后端服务已启动');
      } else if (err instanceof Error && err.message) {
        setError(err.message);
      } else {
        setError('连接失败，请稍后重试');
      }
    } finally {
      clearWatchdog();
      timedOutRef.current = false;
      setIsStreaming(false);
    }
  }, []);

  const abort = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { steps, phaseTitle, streamText, isStreaming, finalData, error, analyze, abort };
}
