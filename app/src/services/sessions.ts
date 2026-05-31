import { apiFetch } from './api';

export interface SessionCalendarItem {
  date: string;
  session_id: string;
  routine_name: string | null;
  duration_minutes: number | null;
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
  total_duration_minutes: number;
  total_sets: number;
  weekly_session_count: number;
  streak_days: number;
  recent_session: RecentSessionItem | null;
}

export function getSessions(token: string, year?: number, month?: number): Promise<SessionCalendarData> {
  const params = year != null && month != null ? `?year=${year}&month=${month}` : '';
  return apiFetch<SessionCalendarData>(`/api/v1/sessions${params}`, { token });
}

export function getSessionStats(token: string): Promise<SessionStatsData> {
  return apiFetch<SessionStatsData>('/api/v1/sessions/stats', { token });
}

export interface VolumeAnalysisItem {
  date: string;
  volume_kg: number;
}

export interface VolumeAnalysisData {
  items: VolumeAnalysisItem[];
}

export interface MuscleVolumeItem {
  muscle: string;
  weekly_volume: number;
  optimal_min: number;
  optimal_max: number;
  status: 'LOW' | 'OPTIMAL' | 'HIGH';
}

export interface MuscleVolumeData {
  period: string;
  volume_by_muscle: MuscleVolumeItem[];
  ai_coach_message: string;
}

export function getVolumeAnalysis(token: string, days = 7): Promise<VolumeAnalysisData> {
  return apiFetch<VolumeAnalysisData>(`/api/v1/sessions/analysis/volume?days=${days}`, { token });
}

export function getMuscleVolumeAnalysis(
  token: string,
  period: 'WEEK' | 'MONTH' = 'WEEK'
): Promise<MuscleVolumeData> {
  return apiFetch<MuscleVolumeData>(
    `/api/v1/sessions/analysis/muscle-volume?period=${period}`,
    { token }
  );
}
