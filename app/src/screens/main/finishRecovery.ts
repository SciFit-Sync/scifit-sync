import { ApiError } from "../../services/api";

/**
 * do_finish의 멱등 복구 결정 로직을 순수 함수로 추출한 것.
 *
 * WR04는 navigation/QueryClient/Zustand 의존이 커서 풀 렌더 테스트가 무겁다.
 * 복구 분기(409=success, abort/네트워크=멱등 재시도 1회)는 이 헬퍼에서
 * provider 없이 단위 테스트한다. do_finish는 이 헬퍼에 위임한다.
 *
 * 규칙(스펙 §4.3):
 *  - 성공 → "done"
 *  - ApiError 409(이미 완료) → "done" (절대 에러로 노출하지 않음)
 *  - ApiError abort/status 0 + 재시도용 세션 id 존재 → body 없이 1회 재시도.
 *    재시도 성공 또는 409 → "done"
 *  - 그 외 → { kind: "error", message }
 */
export type FinishOutcome = { kind: "done" } | { kind: "error"; message: string };

export interface FinishRecoveryDeps {
  /** 첫 시도. 클라가 계산한 finished_at(있으면) 포함. */
  finish: (finished_at?: string) => Promise<unknown>;
  /** body 없이 멱등 재시도. */
  retry: () => Promise<unknown>;
  /** 멱등 재시도 시 사용할 세션 id (없으면 재시도하지 않음). */
  retry_session_id: string | null;
  /** 클라가 계산한 finished_at (없으면 undefined). */
  finished_at?: string;
}

export async function finish_with_recovery(
  deps: FinishRecoveryDeps,
): Promise<FinishOutcome> {
  try {
    await deps.finish(deps.finished_at);
    return { kind: "done" };
  } catch (e: unknown) {
    // 409(이미 완료) → success 취급. 절대 에러로 노출하지 않는다.
    if (e instanceof ApiError && e.status === 409) {
      return { kind: "done" };
    }
    // abort/네트워크(status 0) → 멱등 재시도 1회
    if (
      e instanceof ApiError &&
      (e.aborted || e.status === 0) &&
      deps.retry_session_id
    ) {
      try {
        await deps.retry();
        return { kind: "done" };
      } catch (e2: unknown) {
        if (e2 instanceof ApiError && e2.status === 409) {
          return { kind: "done" };
        }
        const msg2 =
          e2 instanceof Error ? e2.message : "운동 완료 처리에 실패했습니다.";
        return { kind: "error", message: msg2 };
      }
    }
    const msg = e instanceof Error ? e.message : "운동 완료 처리에 실패했습니다.";
    return { kind: "error", message: msg };
  }
}
