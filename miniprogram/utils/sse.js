// utils/sse.js — SSE 流式请求解析
// 小程序 wx.request 的 enableChunked 模式手动解析 SSE 帧
const config = require('./config.js');

/**
 * ArrayBuffer 转字符串（UTF-8 解码）
 */
function arrayBufferToString(buffer) {
  if (typeof buffer === 'string') return buffer;
  if (!buffer) return '';
  const bytes = new Uint8Array(buffer);
  let result = '';
  let i = 0;
  while (i < bytes.length) {
    const byte1 = bytes[i++];
    if (byte1 < 0x80) {
      // ASCII
      result += String.fromCharCode(byte1);
    } else if (byte1 < 0xE0) {
      // 2-byte UTF-8
      const byte2 = bytes[i++];
      result += String.fromCharCode(((byte1 & 0x1F) << 6) | (byte2 & 0x3F));
    } else if (byte1 < 0xF0) {
      // 3-byte UTF-8（中文在此范围）
      const byte2 = bytes[i++];
      const byte3 = bytes[i++];
      result += String.fromCharCode(((byte1 & 0x0F) << 12) | ((byte2 & 0x3F) << 6) | (byte3 & 0x3F));
    } else {
      // 4-byte UTF-8（emoji 等）
      const byte2 = bytes[i++];
      const byte3 = bytes[i++];
      const byte4 = bytes[i++];
      const codePoint = ((byte1 & 0x07) << 18) | ((byte2 & 0x3F) << 12) | ((byte3 & 0x3F) << 6) | (byte4 & 0x3F);
      // 转为 UTF-16 代理对
      const surrogate1 = 0xD800 + ((codePoint - 0x10000) >> 10);
      const surrogate2 = 0xDC00 + ((codePoint - 0x10000) & 0x3FF);
      result += String.fromCharCode(surrogate1, surrogate2);
    }
  }
  return result;
}

/**
 * 解析一段 SSE 文本中的全部事件帧（兼容一帧或多帧）
 */
function parseSseFrames(raw, handlers) {
  const frames = String(raw).split('\n\n');
  for (const frame of frames) {
    const lines = frame.split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith('data:')) continue;

      const jsonStr = trimmed.slice(5).trim();
      if (!jsonStr || jsonStr === '[DONE]') continue;

      try {
        const payload = JSON.parse(jsonStr);
        const eventType = payload.type || '';
        if (eventType === config.sseEvents.PHASE && handlers.onPhase) {
          handlers.onPhase(payload);
        } else if (eventType === config.sseEvents.STEP && handlers.onStep) {
          handlers.onStep(payload);
        } else if (eventType === config.sseEvents.DONE && handlers.onDone) {
          handlers.onDone(payload);
        } else if (eventType === config.sseEvents.ERROR && handlers.onError) {
          handlers.onError(payload);
        } else if (eventType === 'token' && handlers.onChunk) {
          handlers.onChunk(payload);
        }
      } catch (e) {
        // 半条消息（多字节字符被 16KB 分片截断）忽略，等下次拼接后重试
        console.warn('SSE frame parse error:', jsonStr, e);
      }
    }
  }
}

/**
 * SSE 流式请求
 * @param {Object} options
 * @param {string} options.url - 请求路径
 * @param {Object} [options.data] - 请求数据
 * @param {Function} [options.onPhase] - phase 事件回调 (节点开始)
 * @param {Function} [options.onStep] - step 事件回调 (节点完成)
 * @param {Function} [options.onDone] - done 事件回调 (最终报告)
 * @param {Function} [options.onError] - error 事件回调
 * @param {Function} [options.onChunk] - 原始文本 chunk 回调 (报告流式文本)
 * @returns {Object} 包含 abort 方法的控制器
 */
function streamRequest(options) {
  const token = wx.getStorageSync('token');
  const header = {
    'Content-Type': 'application/json',
    'Accept': 'text/event-stream',
  };
  if (token) {
    header['Authorization'] = `Bearer ${token}`;
  }

  let buffer = '';
  let aborted = false;
  let chunked = false; // onChunkReceived 是否触发过（enableChunked 是否生效）
  let gotDone = false;
  let gotError = false;
  let receivedBytes = 0; // 诊断：累计收到的字节数
  let parsedEvents = 0; // 诊断：成功解析的事件数

  const handlers = {
    onPhase: (payload) => { parsedEvents++; if (options.onPhase) options.onPhase(payload); },
    onStep: (payload) => { parsedEvents++; if (options.onStep) options.onStep(payload); },
    onChunk: (payload) => { parsedEvents++; if (options.onChunk) options.onChunk(payload); },
    onDone: (payload) => {
      parsedEvents++;
      gotDone = true;
      if (options.onDone) options.onDone(payload);
    },
    onError: (payload) => {
      parsedEvents++;
      gotError = true;
      if (options.onError) options.onError(payload);
    },
  };

  const task = wx.request({
    url: config.baseUrl + options.url,
    method: 'POST',
    data: options.data,
    header,
    // ⚠️ enableChunked 必须搭配 responseType: 'arraybuffer'，否则 onChunkReceived 不会触发
    responseType: 'arraybuffer',
    enableChunked: true,
    timeout: 420000, // 后端分析上限 420s
    onChunkReceived(res) {
      if (aborted) return;
      chunked = true;
      // 微信 enableChunked 模式下 res.data 是 ArrayBuffer
      const chunk = arrayBufferToString(res.data);
      if (!chunk) return;
      if (!receivedBytes) console.log('[sse] 首个 chunk 到达', chunk.length, 'bytes');
      receivedBytes += chunk.length;

      buffer += chunk;

      // 按 SSE 帧分隔符拆分；最后一段可能不完整（含 16KB 分片截断），保留到下次
      const frames = buffer.split('\n\n');
      buffer = frames.pop();
      parseSseFrames(frames.join('\n\n'), handlers);
    },
    success(res) {
      if (aborted) return;

      // 非 2xx：必须显式报错，否则前端会永久卡在"分析中"
      if (res.statusCode < 200 || res.statusCode >= 300) {
        let detail = '';
        try {
          const d = res.data;
          if (typeof d === 'string') detail = d;
          else if (d && typeof d.detail === 'string') detail = d.detail;
        } catch (e) { /* ignore */ }
        if (res.statusCode === 401) {
          // 与 request.js 一致：登录过期 → 清 token 回登录页
          wx.removeStorageSync('token');
          wx.removeStorageSync('userInfo');
          wx.reLaunch({ url: '/pages/login/login' });
        }
        handlers.onError({
          error: { statusCode: res.statusCode },
          user_message: detail || `请求失败(${res.statusCode})`,
        });
        return;
      }

      if (chunked) {
        // enableChunked 生效：解析残留 buffer（连接结束时最后一段可能没有 \n\n）
        if (buffer.trim()) parseSseFrames(buffer, handlers);
      } else {
        // enableChunked 未生效（低版本/特殊环境）兜底：整个响应体在 res.data 里
        const full = arrayBufferToString(res.data);
        if (full && full.trim()) {
          parseSseFrames(full, handlers);
          buffer = '';
        }
      }

      // 流已结束但既无 done 也无 error：连接被服务端中断，不能继续静默等待
      if (!gotDone && !gotError) {
        console.warn('[sse] 流结束但未收到 done 事件', {
          statusCode: res.statusCode,
          chunked,
          receivedBytes,
          parsedEvents,
          bufferBytes: buffer.length,
          tail: buffer.slice(-200),
        });
        handlers.onError({ user_message: '分析连接中断，请重试' });
      } else {
        console.log('[sse] 请求完成', { statusCode: res.statusCode, chunked, receivedBytes, parsedEvents });
      }
    },
    fail(err) {
      if (aborted) return;
      const errMsg = (err && err.errMsg) || '';
      const userMessage = errMsg.indexOf('timeout') >= 0
        ? '分析超时，请稍后重试'
        : '网络连接失败';
      handlers.onError({ error: err, user_message: userMessage });
    },
  });

  return {
    abort() {
      aborted = true;
      try {
        task.abort();
      } catch (e) {
        // ignore
      }
    },
  };
}

module.exports = { streamRequest };
