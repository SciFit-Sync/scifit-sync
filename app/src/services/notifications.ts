import { apiFetch } from './api';

export interface NotificationItem {
  notification_id: string;
  type: string;
  title: string;
  body: string;
  is_read: boolean;
  data?: Record<string, unknown> | null;
  created_at: string;
}

export interface NotificationListData {
  items: NotificationItem[];
  unread_count: number;
}

export function getNotifications(token: string): Promise<NotificationListData> {
  return apiFetch<NotificationListData>('/api/v1/notifications', { token });
}

export function markNotificationRead(token: string, notification_id: string): Promise<NotificationItem> {
  return apiFetch<NotificationItem>(`/api/v1/notifications/${notification_id}/read`, {
    method: 'PATCH',
    token,
  });
}
