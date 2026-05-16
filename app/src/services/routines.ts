import { apiFetch } from './api';

export interface RoutineExerciseItem {
  routine_exercise_id: string;
  exercise_id: string;
  exercise_name: string;
  equipment_name: string | null;
  order_index: number;
  sets: number;
  reps_min: number | null;
  reps_max: number | null;
  weight_kg: number | null;
  rest_seconds: number;
  note: string | null;
}

export interface RoutineDayItem {
  routine_day_id: string;
  day_number: number;
  label: string;
  exercises: RoutineExerciseItem[];
}

export interface RoutineDetail {
  routine_id: string;
  name: string;
  fitness_goals: string[] | null;
  split_type: string | null;
  generated_by: string;
  status: string;
  session_minutes: number | null;
  ai_reasoning: string | null;
  days: RoutineDayItem[];
  created_at: string;
  updated_at: string;
}

export interface RoutineDeleteData {
  routine_id: string;
  deleted_at: string;
}

export interface RoutineNameData {
  routine_id: string;
  name: string;
}

export function getRoutineDetail(token: string, routine_id: string): Promise<RoutineDetail> {
  return apiFetch<RoutineDetail>(`/api/v1/routines/${routine_id}`, { token });
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
