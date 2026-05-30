import { apiFetch } from './api';

export interface OnboardParams {
  gender: 'male' | 'female';
  birth_date: string; // "YYYY-MM-DD"
  height_cm: number;
  weight_kg: number;
  career_level: 'beginner' | 'novice' | 'intermediate' | 'advanced';
  default_goals?: string[];
}

/** 온보딩 신체정보 등록 (POST /api/v1/users/me/onboard) */
export async function onboardUser(
  params: OnboardParams,
  token: string,
): Promise<{ user_id: string }> {
  return apiFetch<{ user_id: string }>('/api/v1/users/me/onboard', {
    method: 'POST',
    token,
    body: JSON.stringify(params),
  });
}
