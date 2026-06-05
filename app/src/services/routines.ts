import { apiFetch } from './api';

// ── 목록 ──────────────────────────────────────────────────────────────────────

export interface RoutineSummary {
  routine_id: string;
  name: string;
  fitness_goals: string[] | null;
  target_muscle_names: string[] | null;
  split_type: string | null;
  generated_by: string;
  status: string;
  gym_id: string | null;
  gym_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface RoutineListData {
  items: RoutineSummary[];
}

export function listRoutines(token: string): Promise<RoutineListData> {
  return apiFetch<RoutineListData>('/api/v1/routines', { token });
}

// ── AI 루틴 생성 (SSE) ────────────────────────────────────────────────────────

/** 한국어 목표 → 영어 API 값 */
export const GOAL_MAP: Record<string, string> = {
  근비대: 'hypertrophy',
  근력: 'strength',
  체력: 'endurance',
  다이어트: 'weight_loss',
};

/** 한국어 목표 → 표시용 한국어 레이블 (역방향) */
export const GOAL_LABELS: Record<string, string> = {
  hypertrophy: '근비대',
  strength: '근력',
  endurance: '체력',
  weight_loss: '다이어트',
  rehabilitation: '재활',
};

/** 한국어 부위 → 영어 API 값 */
export const BODY_PART_MAP: Record<string, string> = {
  어깨: 'shoulder',
  등: 'back',
  가슴: 'chest',
  하체: 'legs',
  팔: 'arms',
  복근: 'abs',
};

function parse_session_minutes(time: string): number {
  if (time.includes('120')) return 120;
  const match = time.match(/\d+/);
  return match ? parseInt(match[0], 10) : 60;
}

export interface GenerateRoutineParams {
  goal: string;         // 한국어 (근비대 / 근력 / 체력 / 다이어트)
  body_parts: string[]; // 한국어 배열 (어깨 / 등 / 가슴 / 하체 / 팔 / 복근)
  session_time: string; // 한국어 (30분 / 60분 / 90분 / 120분 +)
  injury: string;       // 자유 텍스트
  gym_id?: string | null; // user 기본 헬스장 (머신 후보 포함용; 미전달 시 서버가 기본 gym으로 fallback)
}

export interface SSECallbacks {
  on_started?: (routine_id: string) => void;
  on_chunk?: (content: string) => void;
  on_day_complete?: (day: number, data: unknown) => void;
  on_done?: (routine_id: string, name: string) => void;
  on_error?: (message: string) => void;
}

/**
 * POST /api/v1/routines/generate 를 SSE 스트림으로 호출한다.
 * returns: cleanup 함수 (abort 용)
 */
export function generateRoutineSSE(
  token: string,
  params: GenerateRoutineParams,
  callbacks: SSECallbacks,
): () => void {
  const API_BASE = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';

  const body = JSON.stringify({
    goals: [GOAL_MAP[params.goal] ?? params.goal],
    target_muscle_group_ids: params.body_parts.map((p) => BODY_PART_MAP[p] ?? p),
    session_minutes: parse_session_minutes(params.session_time),
    injury: params.injury || null,
    gym_id: params.gym_id ?? null,
  });

  const xhr = new XMLHttpRequest();
  let last_index = 0;

  xhr.open('POST', `${API_BASE}/api/v1/routines/generate`);
  xhr.setRequestHeader('Authorization', `Bearer ${token}`);
  xhr.setRequestHeader('Content-Type', 'application/json');
  xhr.setRequestHeader('Accept', 'text/event-stream');

  xhr.onprogress = () => {
    const new_text = xhr.responseText.slice(last_index);
    last_index = xhr.responseText.length;
    const lines = new_text.split('\n');
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const data_str = line.slice(6).trim();
      if (data_str === '[DONE]') return;
      try {
        const event = JSON.parse(data_str) as Record<string, unknown>;
        switch (event.type) {
          case 'started':
            callbacks.on_started?.(event.routine_id as string);
            break;
          case 'chunk':
            callbacks.on_chunk?.(event.content as string);
            break;
          case 'day_complete':
            callbacks.on_day_complete?.(event.day as number, event.data);
            break;
          case 'done':
            callbacks.on_done?.(event.routine_id as string, event.name as string);
            break;
          case 'error':
            callbacks.on_error?.((event.message as string) ?? 'AI 오류가 발생했습니다.');
            break;
        }
      } catch {
        // SSE 파싱 오류 무시
      }
    }
  };

  xhr.onerror = () => {
    callbacks.on_error?.('네트워크 오류가 발생했습니다.');
  };

  xhr.onload = () => {
    if (xhr.status !== 200) {
      try {
        const json = JSON.parse(xhr.responseText) as { error?: { message?: string } };
        callbacks.on_error?.(json.error?.message ?? '오류가 발생했습니다.');
      } catch {
        callbacks.on_error?.('오류가 발생했습니다.');
      }
    }
  };

  xhr.send(body);
  return () => xhr.abort();
}

// ── AI 루틴 상세 ──────────────────────────────────────────────────────────────

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

// ── 루틴 상세 ─────────────────────────────────────────────────────────────────

export interface MuscleActivationItem {
  muscle: string;       // 한국어 근육명
  activation_pct: number | null;
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
  has_paper: boolean;
  gif_url: string | null;
  muscle_activation: MuscleActivationItem[];
}

export interface PaperItem {
  paper_id: string;
  title: string;
  authors: string | null;
  journal: string | null;
  year: number | null;
  doi: string | null;
  pmid: string | null;
  doi_url: string | null;
  relevance_summary: string | null;
}

export interface ExercisePapersData {
  routine_exercise_id: string;
  items: PaperItem[];
}

export function getExercisePapers(
  token: string,
  routine_id: string,
  routine_exercise_id: string,
): Promise<ExercisePapersData> {
  return apiFetch<ExercisePapersData>(
    `/api/v1/routines/${routine_id}/exercises/${routine_exercise_id}/paper`,
    { token },
  );
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
  target_muscle_names: string[] | null;
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

export function updateRoutineExercise(
  token: string,
  routine_id: string,
  routine_exercise_id: string,
  exercise_id: string,
): Promise<RoutineExerciseItem> {
  return apiFetch<RoutineExerciseItem>(
    `/api/v1/routines/${routine_id}/exercises/${routine_exercise_id}`,
    {
      method: 'PATCH',
      token,
      body: JSON.stringify({ exercise_id }),
    },
  );
}
