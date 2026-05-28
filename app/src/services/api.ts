const API_BASE = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';

export async function apiFetch<T>(
  path: string,
  options: RequestInit & { token?: string } = {},
): Promise<T> {
  const { token, headers: extraHeaders, ...rest } = options;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(extraHeaders as Record<string, string>),
  };
  const res = await fetch(`${API_BASE}${path}`, { ...rest, headers });
  const json = await res.json();
  if (!json.success) {
    // Pydantic validation 에러는 details.errors 안에 구체적인 내용이 있음
    const detail = json.error?.details?.errors?.[0];
    const detail_msg = detail?.ctx?.error ?? detail?.msg;
    throw new Error(detail_msg ?? json.error?.message ?? '오류가 발생했습니다.');
  }
  return json.data as T;
}
