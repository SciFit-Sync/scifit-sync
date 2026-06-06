import * as SecureStore from 'expo-secure-store';
import { create } from 'zustand';
import { useWorkoutSessionStore } from './workoutSessionStore';

/** JWT payload의 sub(user_id)를 디코딩. 파싱 실패 시 null 반환. */
function _decode_jwt_sub(token: string): string | null {
  try {
    const b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const payload = JSON.parse(atob(b64));
    return typeof payload.sub === 'string' ? payload.sub : null;
  } catch {
    return null;
  }
}

const KEYS = {
  ACCESS_TOKEN: 'scifiit_access_token',
  REFRESH_TOKEN: 'scifiit_refresh_token',
  ONBOARDING_COMPLETE: 'scifiit_onboarding_complete',
} as const;

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  isLoggedIn: boolean;
  isNewUser: boolean;
  isLoading: boolean;
  init: () => Promise<void>;
  setAuth: (params: { access_token: string; refresh_token: string; is_new_user: boolean }) => Promise<void>;
  updateTokens: (params: { access_token: string; refresh_token: string }) => Promise<void>;
  completeOnboarding: () => Promise<void>;
  clearAuth: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  refreshToken: null,
  isLoggedIn: false,
  isNewUser: false,
  isLoading: true,

  init: async () => {
    try {
      const [accessToken, refreshToken, onboardingComplete] = await Promise.all([
        SecureStore.getItemAsync(KEYS.ACCESS_TOKEN),
        SecureStore.getItemAsync(KEYS.REFRESH_TOKEN),
        SecureStore.getItemAsync(KEYS.ONBOARDING_COMPLETE),
      ]);
      if (accessToken) {
        const sub = _decode_jwt_sub(accessToken);
        if (sub) {
          const ws = useWorkoutSessionStore.getState();
          if (ws.owner_user_id && ws.owner_user_id !== sub) {
            ws.clear();
          }
          ws.set_owner(sub);
        }
      }
      set({
        accessToken,
        refreshToken,
        isLoggedIn: !!accessToken,
        isNewUser: onboardingComplete === 'false',
        isLoading: false,
      });
    } catch {
      set({ isLoading: false });
    }
  },

  setAuth: async ({ access_token, refresh_token, is_new_user }) => {
    await Promise.all([
      SecureStore.setItemAsync(KEYS.ACCESS_TOKEN, access_token),
      SecureStore.setItemAsync(KEYS.REFRESH_TOKEN, refresh_token),
      SecureStore.setItemAsync(KEYS.ONBOARDING_COMPLETE, is_new_user ? 'false' : 'true'),
    ]);
    const sub = _decode_jwt_sub(access_token);
    if (sub) {
      const ws = useWorkoutSessionStore.getState();
      if (ws.owner_user_id && ws.owner_user_id !== sub) {
        // 다른 계정으로 로그인 → 이전 운동 세션 초기화
        ws.clear();
      }
      ws.set_owner(sub);
    }
    set({ accessToken: access_token, refreshToken: refresh_token, isLoggedIn: true, isNewUser: is_new_user });
  },

  // refresh token rotation으로 발급받은 새 토큰 쌍을 저장·반영.
  // 로그인 상태/온보딩/세션 소유자는 그대로 두고 토큰만 갱신한다.
  updateTokens: async ({ access_token, refresh_token }) => {
    await Promise.all([
      SecureStore.setItemAsync(KEYS.ACCESS_TOKEN, access_token),
      SecureStore.setItemAsync(KEYS.REFRESH_TOKEN, refresh_token),
    ]);
    set({ accessToken: access_token, refreshToken: refresh_token });
  },

  completeOnboarding: async () => {
    await SecureStore.setItemAsync(KEYS.ONBOARDING_COMPLETE, 'true');
    set({ isNewUser: false });
  },

  clearAuth: async () => {
    await Promise.all([
      SecureStore.deleteItemAsync(KEYS.ACCESS_TOKEN),
      SecureStore.deleteItemAsync(KEYS.REFRESH_TOKEN),
      SecureStore.deleteItemAsync(KEYS.ONBOARDING_COMPLETE),
    ]);
    // 운동 세션 상태는 유지 — 같은 계정으로 재로그인 시 체크 상태 복원을 위해
    // 다른 계정 로그인 시에는 setAuth()에서 clear() 처리
    set({ accessToken: null, refreshToken: null, isLoggedIn: false, isNewUser: false });
  },
}));
