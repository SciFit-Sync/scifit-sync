import { apiFetch } from './api';

export interface ExerciseItem {
  exercise_id: string;
  name: string;
  name_en: string;
  category: string;
  gif_url: string | null;
  primary_muscle_groups: string[];
}

export interface ExerciseListData {
  items: ExerciseItem[];
  total_count: number;
  page: number;
}

export function searchExercises(
  token: string,
  keyword: string,
  size = 20,
): Promise<ExerciseListData> {
  const params = new URLSearchParams({ keyword, size: String(size) });
  return apiFetch<ExerciseListData>(`/api/v1/exercises?${params}`, { token });
}
