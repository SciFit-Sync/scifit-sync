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
    body: JSON.stringify({ accessToken }),
  });

  const data = await response.json();

  if (!data.success) {
    throw new Error(data.error?.message ?? '카카오 로그인에 실패했습니다.');
  }

  return data.data as KakaoAuthResult;
}
