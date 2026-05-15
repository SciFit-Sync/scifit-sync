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
