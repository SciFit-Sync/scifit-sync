import { ApiError } from "../../../services/api";
import { finish_with_recovery } from "../finishRecovery";

/**
 * do_finish의 멱등 복구 결정 로직(순수 헬퍼) 단위 테스트.
 *
 * WR04 자체는 navigation/QueryClient/Zustand 의존이 커서 풀 렌더가 무겁다.
 * 스펙 §4.3의 복구 분기를 provider 없이 헬퍼 단위로 검증한다.
 */
describe("finish_with_recovery", () => {
  it("성공 시 finished_at을 전달하고 done을 반환한다", async () => {
    const finish = jest.fn().mockResolvedValue(undefined);
    const retry = jest.fn();
    const out = await finish_with_recovery({
      finish,
      retry,
      retry_session_id: "s1",
      finished_at: "2026-06-07T00:00:00.000Z",
    });
    expect(out).toEqual({ kind: "done" });
    expect(finish).toHaveBeenCalledWith("2026-06-07T00:00:00.000Z");
    expect(retry).not.toHaveBeenCalled();
  });

  it("409(이미 완료)는 에러 없이 done으로 취급하고 재시도하지 않는다", async () => {
    const finish = jest
      .fn()
      .mockRejectedValue(
        new ApiError("이미 종료된 세션입니다.", {
          status: 409,
          code: "CONFLICT",
        }),
      );
    const retry = jest.fn();
    const out = await finish_with_recovery({
      finish,
      retry,
      retry_session_id: "s1",
    });
    expect(out).toEqual({ kind: "done" });
    expect(retry).not.toHaveBeenCalled();
  });

  it("abort 시 body 없이 1회 재시도하고 성공하면 done", async () => {
    const finish = jest
      .fn()
      .mockRejectedValue(
        new ApiError("요청 시간이 초과되었습니다.", {
          status: 0,
          aborted: true,
        }),
      );
    const retry = jest.fn().mockResolvedValue(undefined);
    const out = await finish_with_recovery({
      finish,
      retry,
      retry_session_id: "s1",
    });
    expect(out).toEqual({ kind: "done" });
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("네트워크(status 0) 재시도가 409면 done", async () => {
    const finish = jest
      .fn()
      .mockRejectedValue(new ApiError("네트워크", { status: 0 }));
    const retry = jest
      .fn()
      .mockRejectedValue(new ApiError("이미 종료", { status: 409 }));
    const out = await finish_with_recovery({
      finish,
      retry,
      retry_session_id: "s1",
    });
    expect(out).toEqual({ kind: "done" });
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("abort이지만 재시도용 세션 id가 없으면 재시도하지 않고 error", async () => {
    const finish = jest
      .fn()
      .mockRejectedValue(new ApiError("타임아웃", { status: 0, aborted: true }));
    const retry = jest.fn();
    const out = await finish_with_recovery({
      finish,
      retry,
      retry_session_id: null,
    });
    expect(out.kind).toBe("error");
    expect(retry).not.toHaveBeenCalled();
  });

  it("재시도가 비-409 에러로 실패하면 그 메시지로 error", async () => {
    const finish = jest
      .fn()
      .mockRejectedValue(new ApiError("타임아웃", { status: 0, aborted: true }));
    const retry = jest
      .fn()
      .mockRejectedValue(new ApiError("서버 오류", { status: 500 }));
    const out = await finish_with_recovery({
      finish,
      retry,
      retry_session_id: "s1",
    });
    expect(out).toEqual({ kind: "error", message: "서버 오류" });
  });

  it("일반 에러(409/abort 아님)는 메시지를 담아 error", async () => {
    const finish = jest.fn().mockRejectedValue(new Error("뭔가 잘못됨"));
    const retry = jest.fn();
    const out = await finish_with_recovery({
      finish,
      retry,
      retry_session_id: "s1",
    });
    expect(out).toEqual({ kind: "error", message: "뭔가 잘못됨" });
    expect(retry).not.toHaveBeenCalled();
  });
});
