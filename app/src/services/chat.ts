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
  /** XHR 인스턴스를 받아 abort 가능하게 하는 콜백 (언마운트 정리용) */
  on_abort_fn?: (abort: () => void) => void;
}

/**
 * 챗봇 히스토리 조회 (GET /api/v1/chat/messages?session_id=...)
 */
export async function fetchChatHistory(session_id: string, token: string): Promise<ChatHistoryData> {
  const res = await fetch(`${API_BASE}/api/v1/chat/messages?session_id=${encodeURIComponent(session_id)}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error('채팅 히스토리를 불러오지 못했습니다.');
  const json = await res.json() as { data: ChatHistoryData };
  return json.data;
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
    xhr.timeout = 60000; // LLM 무응답 시 60초 타임아웃

    xhr.onprogress = () => {
      const buffered = xhr.responseText.slice(last_index);
      const nl = buffered.lastIndexOf('\n');
      if (nl === -1) return; // 완결된 라인 없으면 대기
      const consumable = buffered.slice(0, nl);
      last_index += nl + 1; // 개행까지만 소비 (불완전 마지막 라인 보존)
      const lines = consumable.split('\n');
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

    xhr.ontimeout = () => {
      callbacks.on_error('응답 시간이 초과됐습니다. 다시 시도해 주세요.');
      finish();
    };

    // 언마운트 시 abort 가능하도록 abort 함수를 컴포넌트에 전달
    callbacks.on_abort_fn?.(() => {
      if (!finished) {
        finished = true;
        xhr.abort();
        resolve();
      }
    });

    xhr.send(JSON.stringify({ content, session_id: session_id ?? null }));
  });
}
