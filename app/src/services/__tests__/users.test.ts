import * as api from "../api";
import { ocrInbody } from "../users";

describe("ocrInbody", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("ocrInbody passes timeoutMs 60000 to apiFetch", async () => {
    const spy = jest.spyOn(api, "apiFetch").mockResolvedValue({} as never);
    await ocrInbody("token", "base64img");
    expect(spy).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ timeoutMs: 60000 }),
    );
  });
});
