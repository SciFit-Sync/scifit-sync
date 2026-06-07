import { useAuthStore } from '../stores/authStore';

const API_BASE = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';
const REFRESH_PATH = '/api/v1/auth/refresh';

/**
 * apiFetch가 던지는 타입드 에러.
 * 호출자는 status(409 등)/code/aborted로 상태충돌·abort·네트워크를 구분해
 * 멱등 재시도 등 복구 분기를 할 수 있다.
 */
export class ApiError extends Error {
  status: number;
  code?: string;
  aborted?: boolean;
  constructor(message: string, opts: { status: number; code?: string; aborted?: boolean }) {
    super(message);
    this.name = 'ApiError';
    this.status = opts.status;
    this.code = opts.code;
    this.aborted = opts.aborted;
  }
}

// 동시 다발 401에서 refresh가 중복 호출되지 않도록 single-flight로 직렬화
let refreshPromise: Promise<boolean> | null = null;

/**
 * 저장된 refresh_token으로 새 access/refresh 토큰을 발급받아 스토어를 갱신한다.
 * 성공 시 true. apiFetch를 재사용하지 않고 raw fetch를 써서 401 재귀를 방지한다.
 */
async function refreshTokens(): Promise<boolean> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    const refresh_token = useAuthStore.getState().refreshToken;
    if (!refresh_token) return false;
    try {
      const res = await fetch(`${API_BASE}${REFRESH_PATH}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token }),
      });
      const json = await res.json().catch(() => null);
      if (!res.ok || !json?.success || !json?.data?.access_token || !json?.data?.refresh_token) {
        return false;
      }
      await useAuthStore.getState().updateTokens({
        access_token: json.data.access_token,
        refresh_token: json.data.refresh_token,
      });
      return true;
    } catch {
      return false;
    }
  })();
  try {
    return await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit & { token?: string; timeoutMs?: number } = {},
): Promise<T> {
  const { token, headers: extraHeaders, timeoutMs = 30000, ...rest } = options;

  const build_headers = (authToken?: string): Record<string, string> => ({
    'Content-Type': 'application/json',
    ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    ...(extraHeaders as Record<string, string>),
  });

  // 매 시도마다 새 AbortController/타이머를 만든다(401 재시도 시 직전 컨트롤러 재사용 금지).
  // timeoutMs 경과 시 controller.abort()로 AbortError를 유발 → ApiError(aborted)로 변환.
  const send = (authToken?: string) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    return fetch(`${API_BASE}${path}`, {
      ...rest,
      headers: build_headers(authToken),
      signal: controller.signal,
    }).finally(() => clearTimeout(timer));
  };

  // abort(타임아웃)·네트워크 오류를 사용자 친화 ApiError(status 0)로 변환한다.
  const send_safe = async (authToken?: string): Promise<Response> => {
    try {
      return await send(authToken);
    } catch (e: any) {
      if (e?.name === 'AbortError') {
        throw new ApiError('요청 시간이 초과되었습니다.', { status: 0, aborted: true });
      }
      throw new ApiError('네트워크 연결을 확인해주세요.', { status: 0 });
    }
  };

  let res = await send_safe(token);

  // access token 만료(401) → 인증 요청에 한해 1회 토큰 갱신 후 원요청 재시도.
  // refresh 엔드포인트 자체는 제외(무한 루프 방지).
  if (res.status === 401 && token && path !== REFRESH_PATH) {
    const refreshed = await refreshTokens();
    if (refreshed) {
      res = await send_safe(useAuthStore.getState().accessToken ?? undefined);
    }
    // refresh 토큰도 만료/무효이거나, 재발급 후 재시도도 여전히 401이면
    // (시계 skew·refresh 직후 family revoke 등) → 로그아웃하여 로그인 화면으로 복귀.
    // 사용자가 깨진/빈 화면에 갇히지 않도록 한다.
    if (!refreshed || res.status === 401) {
      await useAuthStore.getState().clearAuth();
      throw new Error('세션이 만료되었습니다. 다시 로그인해주세요.');
    }
  }

  // 비-JSON 응답(502/504 HTML 에러 페이지, 빈 본문 등) 방어:
  // res.json() SyntaxError 대신 상태코드 기반의 사용자 친화 메시지를 던진다.
  let json: any;
  try {
    json = await res.json();
  } catch {
    if (res.ok) return undefined as T; // 본문 없는 성공 응답(예: 204)
    throw new ApiError(
      res.status >= 500
        ? '서버에 일시적인 문제가 발생했습니다. 잠시 후 다시 시도해주세요.'
        : `요청을 처리할 수 없습니다. (${res.status})`,
      { status: res.status },
    );
  }

  if (!json?.success) {
    // Pydantic validation 에러는 details.errors 안에 구체적인 내용이 있음
    const detail = json?.error?.details?.errors?.[0];
    const detail_msg = detail?.ctx?.error ?? detail?.msg;
    throw new ApiError(detail_msg ?? json?.error?.message ?? '오류가 발생했습니다.', {
      status: res.status,
      code: json?.error?.code,
    });
  }
  return json.data as T;
}
