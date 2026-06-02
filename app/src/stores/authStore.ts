import * as SecureStore from 'expo-secure-store';
import { create } from 'zustand';
import { useWorkoutSessionStore } from './workoutSessionStore';

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
    set({ accessToken: access_token, refreshToken: refresh_token, isLoggedIn: true, isNewUser: is_new_user });
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
    // 로그아웃 시 진행 중인 운동 세션 상태도 함께 초기화
    useWorkoutSessionStore.getState().clear();
    set({ accessToken: null, refreshToken: null, isLoggedIn: false, isNewUser: false });
  },
}));
