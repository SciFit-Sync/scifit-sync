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
