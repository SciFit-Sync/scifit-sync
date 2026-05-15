import { apiFetch } from './api';

export interface SessionItem {
  session_id: string;
  routine_day_id: string | null;
  gym_id: string | null;
  started_at: string;
  finished_at: string | null;
  status: string;
  routine_name: string | null;
  duration_minutes: number | null;
}

export interface SessionListData {
  items: SessionItem[];
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

export function getSessions(token: string, year?: number, month?: number): Promise<SessionListData> {
  const params = year != null && month != null ? `?year=${year}&month=${month}` : '';
  return apiFetch<SessionListData>(`/api/v1/sessions${params}`, { token });
}

export function getSessionStats(token: string): Promise<SessionStatsData> {
  return apiFetch<SessionStatsData>('/api/v1/sessions/stats', { token });
}
