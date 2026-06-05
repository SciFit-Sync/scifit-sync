import { apiFetch } from "./api";

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

export interface CoreLiftItem {
  code: string;
  exercise_id: string;
  name: string;
  name_en: string | null;
}

export interface OnboardParams {
  gender: "male" | "female";
  birth_date: string; // "YYYY-MM-DD"
  height_cm: number;
  weight_kg: number;
  career_level: "beginner" | "novice" | "intermediate" | "advanced";
  default_goals?: string[];
}

// GET /api/v1/users/me
export async function getMe(token: string): Promise<MeData> {
  return apiFetch<MeData>("/api/v1/users/me", { token });
}

// GET /api/v1/users/me/1rm
export async function getMyOneRMs(token: string): Promise<OneRMData[]> {
  const data = await apiFetch<{ items: OneRMData[] }>("/api/v1/users/me/1rm", {
    token,
  });
  return data.items;
}

// POST /api/v1/users/me/onboard (온보딩 신체정보 등록)
export async function onboardUser(
  params: OnboardParams,
  token: string,
): Promise<{ user_id: string }> {
  return apiFetch<{ user_id: string }>("/api/v1/users/me/onboard", {
    method: "POST",
    token,
    body: JSON.stringify(params),
  });
}

// PATCH /api/v1/users/me/body
export async function updateBody(
  token: string,
  body: {
    height_cm?: number;
    weight_kg?: number;
    skeletal_muscle_kg?: number;
    body_fat_pct?: number;
    measured_at?: string; // "YYYY-MM-DD"
    birth_date?: string; // "YYYY-MM-DD"
    gender?: string; // "male" | "female"
  },
): Promise<void> {
  await apiFetch("/api/v1/users/me/body", {
    method: "PATCH",
    token,
    body: JSON.stringify(body),
  });
}

// POST /api/v1/users/me/body/ocr (인바디 결과지 사진 → OCR 추출, 저장 X)
export async function ocrInbody(
  token: string,
  image_base64: string,
  mime_type = "image/jpeg",
): Promise<BodyMeasurementData> {
  return apiFetch<BodyMeasurementData>("/api/v1/users/me/body/ocr", {
    method: "POST",
    token,
    body: JSON.stringify({ image_base64, mime_type }),
  });
}

// PATCH /api/v1/users/me/career
export async function updateCareer(
  token: string,
  career_level: string,
): Promise<void> {
  await apiFetch("/api/v1/users/me/career", {
    method: "PATCH",
    token,
    body: JSON.stringify({ career_level }),
  });
}

// PATCH /api/v1/users/me/gym (주 헬스장 변경)
export async function updateMyGym(
  token: string,
  gym_id: string,
): Promise<void> {
  await apiFetch("/api/v1/users/me/gym", {
    method: "PATCH",
    token,
    body: JSON.stringify({ gym_id }),
  });
}

// POST /api/v1/users/me/1rm/bulk (1RM 일괄 저장)
export interface BulkOneRMItem {
  exercise_code: string;
  weight_kg: number;
}
export async function bulkSaveOneRM(
  token: string,
  items: BulkOneRMItem[],
): Promise<void> {
  await apiFetch("/api/v1/users/me/1rm/bulk", {
    method: "POST",
    token,
    body: JSON.stringify({ items }),
  });
}

// GET /api/v1/exercises/core-lifts
export async function getCoreLifts(token: string): Promise<CoreLiftItem[]> {
  const data = await apiFetch<{ items: CoreLiftItem[] }>(
    "/api/v1/exercises/core-lifts",
    { token },
  );
  return data.items;
}

// DELETE /api/v1/auth/withdraw
export async function withdrawUser(
  token: string,
  password?: string,
): Promise<void> {
  await apiFetch("/api/v1/auth/withdraw", {
    method: "DELETE",
    token,
    body: JSON.stringify({ password: password ?? null }),
  });
}
