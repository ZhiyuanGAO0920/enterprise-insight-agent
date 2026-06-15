import { useState, useCallback, useRef } from 'react';
import client from '../api/client';

interface SSEEvent {
  type: 'step' | 'phase' | 'token' | 'done';
  node?: string;
  status?: string;
  label?: string;
  text?: string;
  report?: string;
  errors?: any[];
  reflection_passed?: boolean;
  record_id?: number;
  data_sources?: any[];
  followup_questions?: string[];
}

export function useSSE() {
  const [steps, setSteps] = useState<Record<string, string>>({});
  const [streamText, setStreamText] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [finalData, setFinalData] = useState<SSEEvent | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const analyze = useCallback(async (question: string, sessionId: string | null) => {
    setIsStreaming(true);
    setStreamText('');
    setSteps({});
    setFinalData(null);

    const controller = new AbortController();
    abortRef.current = controller;

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

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const event: SSEEvent = JSON.parse(line.slice(6));
            if (event.type === 'step' || event.type === 'phase') {
              setSteps((prev) => ({
                ...prev,
                [event.node!]: event.status === 'done' ? 'done' : 'active',
              }));
            } else if (event.type === 'token') {
              setStreamText((prev) => prev + (event.text || ''));
            } else if (event.type === 'done') {
              setFinalData(event);
            }
          } catch {}
        }
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        console.error('SSE error:', err);
      }
    } finally {
      setIsStreaming(false);
    }
  }, []);

  const abort = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { steps, streamText, isStreaming, finalData, analyze, abort };
}
