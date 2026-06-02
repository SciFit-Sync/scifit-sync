import { apiFetch } from './api';

export interface SessionCalendarItem {
  date: string;
  session_id: string;
  routine_id: string | null;
  routine_name: string | null;
  fitness_goals: string[];
  duration_minutes: number | null;
  gym_name: string | null;
  total_volume_kg: number;
  total_weight_kg: number;
  total_sets: number;
}

export interface SessionCalendarData {
  year: number;
  month: number;
  records: SessionCalendarItem[];
  total_session_count: number;
}

export interface RecentSessionItem {
  session_id: string;
  routine_name: string | null;
  date: string;
}

export interface SessionStatsData {
  total_sessions: number;
  total_volume_kg: number;
  total_weight_kg: number;
  total_duration_minutes: number;
  total_sets: number;
  weekly_session_count: number;
  streak_days: number;
  total_calories_kcal: number;
  recent_session: RecentSessionItem | null;
}

export function getSessions(token: string, year?: number, month?: number): Promise<SessionCalendarData> {
  const params = year != null && month != null ? `?year=${year}&month=${month}` : '';
  return apiFetch<SessionCalendarData>(`/api/v1/sessions${params}`, { token });
}

export function getSessionStats(token: string): Promise<SessionStatsData> {
  return apiFetch<SessionStatsData>('/api/v1/sessions/stats', { token });
}

// ── 세션 시작 / 세트 기록 / 완료 ─────────────────────────────────────────────

export interface StartSessionData {
  session_id: string;
  routine_id: string | null;
  routine_name: string | null;
  gym_id: string | null;
  started_at: string;
}

export interface StartSessionBody {
  routine_id?: string;
  routine_day_id?: string;
  gym_id?: string;
}

export interface LogSetBody {
  exercise_id: string;
  routine_exercise_id?: string;
  set_number: number;
  weight_kg?: number | null;
  reps: number;
  is_completed: boolean;
}

export function startSession(token: string, body: StartSessionBody): Promise<StartSessionData> {
  return apiFetch<StartSessionData>('/api/v1/sessions', {
    token,
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function logSet(token: string, session_id: string, body: LogSetBody): Promise<unknown> {
  return apiFetch<unknown>(`/api/v1/sessions/${session_id}/sets`, {
    token,
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function finishSession(token: string, session_id: string): Promise<unknown> {
  return apiFetch<unknown>(`/api/v1/sessions/${session_id}/finish`, {
    token,
    method: 'PATCH',
    body: JSON.stringify({}),
  });
}

// ── 볼륨 분석 / 근육 부위별 분석 ─────────────────────────────────────────────

export interface VolumeAnalysisItem {
  date: string;       // YYYY-MM-DD
  volume_kg: number;
}

export interface VolumeAnalysisData {
  items: VolumeAnalysisItem[];
}

export interface MuscleVolumeItem {
  muscle: string;         // MuscleGroup.name_ko (예: "가슴", "광배근")
  weekly_volume: number;
  optimal_min: number;
  optimal_max: number;
  status: 'OPTIMAL' | 'LOW' | 'HIGH';
}

export interface MuscleVolumeData {
  period: string;
  volume_by_muscle: MuscleVolumeItem[];
  ai_coach_message: string;
}

export function getVolumeAnalysis(token: string, days: number): Promise<VolumeAnalysisData> {
  return apiFetch<VolumeAnalysisData>(`/api/v1/sessions/analysis/volume?days=${days}`, { token });
}

export function getMuscleVolumeAnalysis(token: string, period: 'WEEK' | 'MONTH'): Promise<MuscleVolumeData> {
  return apiFetch<MuscleVolumeData>(`/api/v1/sessions/analysis/muscle-volume?period=${period}`, { token });
}
