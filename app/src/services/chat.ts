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

/** 챗봇 대화 이력 조회 */
export async function fetchChatHistory(session_id: string, token: string): Promise<ChatHistoryData> {
  const res = await fetch(`${API_BASE}/api/v1/chat/messages?session_id=${session_id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const json = await res.json().catch(() => ({}));
    throw new Error((json as any).error?.message ?? '대화 이력 조회에 실패했습니다.');
  }
  const json = await res.json();
  if (!json.success) throw new Error(json.error?.message ?? '대화 이력 조회에 실패했습니다.');
  return json.data as ChatHistoryData;
}

export interface SendMessageCallbacks {
  on_session_id: (session_id: string) => void;
  on_chunk: (chunk: string) => void;
  on_done: () => void;
  on_error: (msg: string) => void;
  on_sources?: (sources: { doi: string; pmid?: string; title?: string }[]) => void;
}

/** 챗봇 메시지 전송 (SSE 스트리밍) */
export async function sendChatMessage(
  content: string,
  token: string,
  callbacks: SendMessageCallbacks,
  session_id?: string,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/chat/messages`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ content, session_id: session_id ?? null }),
  });

  if (!res.ok) {
    const json = await res.json().catch(() => ({}));
    throw new Error(json.error?.message ?? '메시지 전송에 실패했습니다.');
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error('스트림을 읽을 수 없습니다.');

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      if (!line.startsWith('data:')) continue;
      const raw = line.slice(5).trim();
      if (raw === '[DONE]') { callbacks.on_done(); return; }
      try {
        const ev = JSON.parse(raw);
        if (ev.type === 'session') callbacks.on_session_id(ev.session_id);
        else if (ev.type === 'chunk') callbacks.on_chunk(ev.content ?? '');
        else if (ev.type === 'sources') callbacks.on_sources?.(ev.sources ?? []);
        else if (ev.type === 'error') callbacks.on_error(ev.message ?? '오류가 발생했습니다.');
      } catch {
        // 파싱 불가 라인 무시
      }
    }
  }
  callbacks.on_done();
}
