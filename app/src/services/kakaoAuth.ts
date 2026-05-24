import { login } from '@react-native-seoul/kakao-login';

const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';

export interface KakaoAuthResult {
  accessToken: string;
  refreshToken: string;
  isNewUser: boolean;
  message?: string;
}

export async function signInWithKakao(): Promise<KakaoAuthResult> {
  const { accessToken: kakaoToken } = await login();

  const response = await fetch(`${API_BASE_URL}/api/v1/auth/kakao`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ access_token: kakaoToken }),
  });

  const data = await response.json();

  if (!data.success) {
    throw new Error(data.error?.message ?? '카카오 로그인에 실패했습니다.');
  }

  const { access_token, refresh_token, is_new_user, message } = data.data;
  return {
    accessToken: access_token,
    refreshToken: refresh_token,
    isNewUser: is_new_user,
    message,
  };
}
