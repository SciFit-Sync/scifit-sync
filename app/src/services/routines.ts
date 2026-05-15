import { apiFetch } from './api';

export interface RoutineDeleteData {
  routine_id: string;
  deleted_at: string;
}

export interface RoutineNameData {
  routine_id: string;
  name: string;
}

export function deleteRoutine(token: string, routine_id: string): Promise<RoutineDeleteData> {
  return apiFetch<RoutineDeleteData>(`/api/v1/routines/${routine_id}`, {
    method: 'DELETE',
    token,
  });
}

export function renameRoutine(token: string, routine_id: string, name: string): Promise<RoutineNameData> {
  return apiFetch<RoutineNameData>(`/api/v1/routines/${routine_id}/name`, {
    method: 'PATCH',
    token,
    body: JSON.stringify({ name }),
  });
}
