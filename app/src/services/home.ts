import { apiFetch } from './api';
import type { NotificationItem } from './notifications';

export interface HomeRoutineSummary {
  routine_id: string;
  name: string;
  next_day_label: string | null;
}

export interface HomeData {
  user_name: string;
  streak_days: number;
  today_routine: HomeRoutineSummary | null;
  upcoming_notifications: NotificationItem[];
  recent_volume_kg: number;
}

export function getHome(token: string): Promise<HomeData> {
  return apiFetch<HomeData>('/api/v1/home', { token });
}
