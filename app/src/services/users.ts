import { apiFetch } from './api';

export interface ProfileData {
  gender?: string;
  birth_date?: string;
  age?: number;
  height_cm?: number;
  default_goals?: string[];
  career_level?: string;
}

export interface BodyMeasurementData {
  weight_kg?: number;
  skeletal_muscle_kg?: number;
  body_fat_pct?: number;
  measured_at?: string;
}

export interface GymData {
  gym_id: string;
  name: string;
  is_primary: boolean;
}

export interface MeData {
  user_id: string;
  email: string;
  username: string;
  name: string;
  provider: string;
  profile?: ProfileData;
  latest_measurement?: BodyMeasurementData;
  gyms: GymData[];
}

export interface OneRMData {
  id: string;
  exercise_id: string;
  exercise_name?: string;
  weight_kg: number;
  source: string;
  estimated_at: string;
}

// GET /api/v1/users/me
export async function getMe(token: string): Promise<MeData> {
  return apiFetch<MeData>('/api/v1/users/me', { token });
}

// GET /api/v1/users/me/1rm
export async function getMyOneRMs(token: string): Promise<OneRMData[]> {
  const data = await apiFetch<{ items: OneRMData[] }>('/api/v1/users/me/1rm', { token });
  return data.items;
}
