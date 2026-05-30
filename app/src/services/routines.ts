import { apiFetch } from './api';

export interface SetItem {
  set_number: number;
  weight_kg: number | null;
  reps: number | null;
  rest_seconds: number;
  completed: boolean;
  completed_at: string | null;
}

export interface MuscleActivationDetailItem {
  muscle: string;
  muscle_en: string;
  percentage: number | null;
  type: string;
}

export interface ExerciseDetailItem {
  order: number;
  exercise_id: string;
  name: string;
  name_en: string | null;
  gif_url: string | null;
  thumbnail_url: string | null;
  category: string | null;
  equipment: string | null;
  muscle_activation: MuscleActivationDetailItem[];
  sets: SetItem[];
  ai_reasoning: string | null;
  is_replaceable: boolean;
}

export interface AIRoutineDetail {
  routine_id: string;
  title: string;
  goal: string | null;
  estimated_duration_min: number | null;
  default_rest_seconds: number | null;
  created_by: string;
  created_at: string;
  exercises: ExerciseDetailItem[];
}

export function getAIRoutineDetail(token: string, routine_id: string): Promise<AIRoutineDetail> {
  return apiFetch<AIRoutineDetail>(`/api/v1/routines/${routine_id}/ai-detail`, { token });
}

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
