/**
 * 진행 중인 운동 세션 상태를 앱 메모리에 보존하는 스토어.
 * 루틴 상세 화면을 나갔다 돌아와도 체크 상태와 세션 ID가 유지된다.
 * 세션 완료(finishSession) 또는 앱 재시작 시 초기화된다.
 */
import { create } from 'zustand';

interface WorkoutSessionState {
  /** 현재 진행 중인 루틴 ID */
  routine_id: string | null;
  /** 백엔드 세션 ID */
  session_id: string | null;
  /** set_id → 체크 여부 */
  checked_sets: Record<string, boolean>;

  set_session: (routine_id: string, session_id: string) => void;
  toggle_set: (set_id: string, is_done: boolean) => void;
  clear: () => void;
}

export const useWorkoutSessionStore = create<WorkoutSessionState>((set) => ({
  routine_id: null,
  session_id: null,
  checked_sets: {},

  set_session: (routine_id, session_id) =>
    set({ routine_id, session_id }),

  toggle_set: (set_id, is_done) =>
    set((state) => ({
      checked_sets: { ...state.checked_sets, [set_id]: is_done },
    })),

  clear: () =>
    set({ routine_id: null, session_id: null, checked_sets: {} }),
}));
