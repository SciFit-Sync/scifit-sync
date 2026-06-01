import { apiFetch } from './api';

export interface RegisterParams {
  username: string;
  password: string;
  name: string;
  email: string;
  gender?: string;
  birth_date?: string;
  height?: number;
  weight?: number;
  career_level?: string;
}

export interface RegisterResult {
  user_id: string;
  username: string;
  otp_code?: string;
}

export interface LoginResult {
  access_token: string;
  refresh_token: string;
  user_id: string;
  username: string;
}

export async function register(params: RegisterParams): Promise<RegisterResult> {
  return apiFetch<RegisterResult>('/api/v1/auth/register', {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

export async function loginApi(email: string, password: string): Promise<LoginResult> {
  return apiFetch<LoginResult>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
}

export async function verifyEmail(
  email: string,
  otp: string,
): Promise<{ verified: boolean; message: string }> {
  return apiFetch<{ verified: boolean; message: string }>('/api/v1/auth/verify-email', {
    method: 'POST',
    body: JSON.stringify({ email, otp }),
  });
}

export interface OnboardParams {
  gender: string;
  birth_date: string;
  height_cm: number;
  weight_kg: number;
  career_level: string;
  default_goals?: string[];
}

export async function onboard(params: OnboardParams, token: string): Promise<void> {
  await apiFetch<{ user_id: string }>('/api/v1/users/me/onboard', {
    method: 'POST',
    token,
    body: JSON.stringify(params),
  });
}

export async function checkUsername(username: string): Promise<{ username: string; available: boolean }> {
  return apiFetch<{ username: string; available: boolean }>(
    `/api/v1/auth/check-username?username=${encodeURIComponent(username)}`,
  );
}
