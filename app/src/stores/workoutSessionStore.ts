/**
 * 진행 중인 운동 세션 상태를 AsyncStorage에 영속화하는 스토어.
 * 루틴 상세 화면을 나갔다 돌아오거나 앱을 재시작해도 체크 상태와 세션 ID가 유지된다.
 * 세션 완료(finishSession) 시 clear()로 초기화한다.
 * 로그아웃 후 같은 계정으로 재로그인하면 체크 상태가 복원된다.
 * 다른 계정으로 로그인하면 authStore.setAuth()에서 clear()를 호출한다.
 */
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import AsyncStorage from '@react-native-async-storage/async-storage';

interface WorkoutSessionState {
  /** 세션 소유자 user_id (JWT sub) — 다른 계정 로그인 시 clear 판단에 사용 */
  owner_user_id: string | null;
  /** 현재 진행 중인 루틴 ID */
  routine_id: string | null;
  /** 백엔드 세션 ID */
  session_id: string | null;
  /** 세션 시작 시각 (ISO string) — 완료 시 finished_at 계산에 사용 */
  session_started_at: string | null;
  /** 루틴 상세 페이지 누적 체류 시간 (ms) — 탭 이탈 시마다 합산 */
  page_elapsed_ms: number;
  /** 현재 루틴 상세 페이지 진입 시각 (ms) — 페이지에 있는 동안만 존재, 이탈 시 null */
  detail_page_enter_ms: number | null;
  /** set_id → 체크 여부 */
  checked_sets: Record<string, boolean>;
  /** 스톱워치 일시정지 여부 — 페이지 이탈해도 유지 */
  is_timer_paused: boolean;
  /** 일시정지 시점의 표시값(ms) — 복귀 시 부풀림 방지 */
  frozen_timer_ms: number;
  /** routine_exercise_id → 사용자가 설정한 휴식 시간(초) — 화면 이탈 후 복귀 시에도 유지 */
  rest_seconds_overrides: Record<string, number>;
  /** 일시정지 누적 시간(ms) — 화면 이탈 후 복귀 시에도 유지 */
  pause_offset_ms: number;

  set_owner: (user_id: string) => void;
  set_session: (routine_id: string, session_id: string, started_at: string) => void;
  add_page_elapsed: (ms: number) => void;
  set_detail_page_enter: (ms: number | null) => void;
  toggle_set: (set_id: string, is_done: boolean) => void;
  set_timer_paused: (paused: boolean, frozen_ms?: number) => void;
  set_pause_offset_ms: (ms: number) => void;
  set_rest_seconds: (rex_id: string, seconds: number) => void;
  clear: () => void;
}

export const useWorkoutSessionStore = create<WorkoutSessionState>()(
  persist(
    (set) => ({
      owner_user_id: null,
      routine_id: null,
      session_id: null,
      session_started_at: null,
      page_elapsed_ms: 0,
      detail_page_enter_ms: null,
      checked_sets: {},
      is_timer_paused: false,
      frozen_timer_ms: 0,
      rest_seconds_overrides: {},
      pause_offset_ms: 0,

      set_owner: (user_id) => set({ owner_user_id: user_id }),

      set_session: (routine_id, session_id, started_at) =>
        set({ routine_id, session_id, session_started_at: started_at }),

      add_page_elapsed: (ms) =>
        set((state) => ({ page_elapsed_ms: state.page_elapsed_ms + ms })),

      set_detail_page_enter: (ms) => set({ detail_page_enter_ms: ms }),

      toggle_set: (set_id, is_done) =>
        set((state) => ({
          checked_sets: { ...state.checked_sets, [set_id]: is_done },
        })),

      set_timer_paused: (paused, frozen_ms = 0) =>
        set({ is_timer_paused: paused, frozen_timer_ms: frozen_ms }),

      set_pause_offset_ms: (ms) => set({ pause_offset_ms: ms }),

      set_rest_seconds: (rex_id, seconds) =>
        set((state) => ({
          rest_seconds_overrides: { ...state.rest_seconds_overrides, [rex_id]: seconds },
        })),

      clear: () =>
        set({
          owner_user_id: null,
          routine_id: null,
          session_id: null,
          session_started_at: null,
          page_elapsed_ms: 0,
          detail_page_enter_ms: null,
          checked_sets: {},
          is_timer_paused: false,
          frozen_timer_ms: 0,
          rest_seconds_overrides: {},
          pause_offset_ms: 0,
        }),
    }),
    {
      name: 'workout-session',
      storage: createJSONStorage(() => AsyncStorage),
    },
  ),
);
