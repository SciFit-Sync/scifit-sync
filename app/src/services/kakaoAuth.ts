import { login } from '@react-native-seoul/kakao-login';

const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';

export interface KakaoAuthResult {
  accessToken: string;
  refreshToken: string;
  isNewUser: boolean;
  message?: string;
}

export async function signInWithKakao(): Promise<KakaoAuthResult> {
  // 카카오 SDK로 로그인 → accessToken 획득
  const { accessToken } = await login();

  // 우리 서버에 accessToken 전달 → JWT 발급
  const response = await fetch(`${API_BASE_URL}/api/v1/auth/kakao`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ access_token: accessToken }),
  });

  const data = await response.json();

  if (!data.success) {
    throw new Error(data.error?.message ?? '카카오 로그인에 실패했습니다.');
  }

  // 서버는 snake_case로 응답 (D-15) → camelCase로 변환
  const d = data.data as {
    access_token: string;
    refresh_token: string;
    is_new_user: boolean;
    message?: string;
  };

  return {
    accessToken: d.access_token,
    refreshToken: d.refresh_token,
    isNewUser: d.is_new_user,
    message: d.message,
  };
}
