const API_BASE = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';

export interface ChatMessageItem {
  message_id: string;
  role: 'user' | 'assistant';
  content: string;
  paper_ids: string[] | null;
  created_at: string;
}

export interface ChatHistoryData {
  session_id: string;
  items: ChatMessageItem[];
}

export interface SendMessageCallbacks {
  on_session_id: (session_id: string) => void;
  on_chunk: (chunk: string) => void;
  on_done: () => void;
  on_error: (msg: string) => void;
  on_sources?: (sources: { doi: string; pmid?: string; title?: string }[]) => void;
}

/**
 * 챗봇 메시지 전송 (SSE 스트리밍).
 * React Native 환경에서 fetch ReadableStream이 지원 안 되는 경우가 있어 XHR 사용.
 */
export function sendChatMessage(
  content: string,
  token: string,
  callbacks: SendMessageCallbacks,
  session_id?: string,
): Promise<void> {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    let last_index = 0;
    let finished = false;
    let done_called = false;

    const finish = () => {
      if (!finished) {
        finished = true;
        resolve();
      }
    };

    xhr.open('POST', `${API_BASE}/api/v1/chat/messages`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.setRequestHeader('Content-Type', 'application/json');

    xhr.onprogress = () => {
      const new_text = xhr.responseText.slice(last_index);
      last_index = xhr.responseText.length;
      const lines = new_text.split('\n');
      for (const line of lines) {
        if (!line.startsWith('data:')) continue;
        const raw = line.slice(5).trim();
        if (raw === '[DONE]') {
          if (!done_called) { done_called = true; callbacks.on_done(); }
          finish();
          return;
        }
        try {
          const ev = JSON.parse(raw);
          if (ev.type === 'session') callbacks.on_session_id(ev.session_id);
          else if (ev.type === 'chunk') callbacks.on_chunk(ev.content ?? '');
          else if (ev.type === 'sources') callbacks.on_sources?.(ev.sources ?? []);
          else if (ev.type === 'error') {
            callbacks.on_error(ev.message ?? '오류가 발생했습니다.');
            finish();
          }
        } catch {
          // 파싱 불가 라인 무시
        }
      }
    };

    xhr.onload = () => {
      if (xhr.status !== 200) {
        try {
          const json = JSON.parse(xhr.responseText) as { error?: { message?: string } };
          callbacks.on_error(json.error?.message ?? '메시지 전송에 실패했습니다.');
        } catch {
          callbacks.on_error('메시지 전송에 실패했습니다.');
        }
      } else if (!done_called) {
        // [DONE] 없이 스트림이 끝난 경우 fallback
        done_called = true;
        callbacks.on_done();
      }
      finish();
    };

    xhr.onerror = () => {
      callbacks.on_error('네트워크 오류가 발생했습니다.');
      finish();
    };

    xhr.send(JSON.stringify({ content, session_id: session_id ?? null }));
  });
}
