import { ApiError, apiFetch } from "../api";

function mockFetchOnce(status: number, body: any) {
  (global as any).fetch = jest.fn().mockResolvedValue({
    status,
    ok: status >= 200 && status < 300,
    json: async () => body,
  });
}

describe("ApiError", () => {
  it("throws ApiError with status/code on non-success body", async () => {
    mockFetchOnce(409, { success: false, error: { code: "CONFLICT", message: "이미 종료된 세션입니다." } });
    await expect(apiFetch("/x", { token: "t" })).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      code: "CONFLICT",
    });
  });

  it("ApiError is an Error with .message", async () => {
    mockFetchOnce(409, { success: false, error: { code: "CONFLICT", message: "이미 종료된 세션입니다." } });
    const err = await apiFetch("/x", { token: "t" }).catch((e) => e);
    expect(err).toBeInstanceOf(Error);
    expect(err.message).toBe("이미 종료된 세션입니다.");
  });
});

describe("timeout", () => {
  it("aborts after timeoutMs and throws ApiError(aborted)", async () => {
    (global as any).fetch = jest.fn((_url, opts: any) =>
      new Promise((_resolve, reject) => {
        opts.signal?.addEventListener("abort", () => reject(Object.assign(new Error("Aborted"), { name: "AbortError" })));
      }),
    );
    const p = apiFetch("/slow", { token: "t", timeoutMs: 20 });
    await expect(p).rejects.toMatchObject({ name: "ApiError", aborted: true, status: 0 });
  });
});
