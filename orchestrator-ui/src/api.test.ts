import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError, connectSse } from "./api";

// Minimal EventSource stub used across SSE tests.
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onmessage: ((ev: MessageEvent<string>) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  close = vi.fn();
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
}

describe("ApiClient", () => {
  let client: ApiClient;

  beforeEach(() => {
    client = new ApiClient("http://localhost:8000");
    vi.spyOn(globalThis, "fetch").mockReset();
  });

  it("get returns parsed JSON on 200", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ value: 42 }), { status: 200 }),
    );
    const result = await client.get<{ value: number }>("/test");
    expect(result).toEqual({ value: 42 });
  });

  it("get throws ApiError on 401", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("Unauthorized", { status: 401 }),
    );
    await expect(client.get("/test")).rejects.toMatchObject({ status: 401 });
  });

  it("get throws ApiError on 500", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("Internal server error", { status: 500 }),
    );
    const err = await client.get("/test").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
  });

  it("post sends JSON body and returns response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
    );
    const result = await client.post<{ status: string }>("/login", { password: "secret" });
    expect(result).toEqual({ status: "ok" });

    const call = vi.mocked(fetch).mock.calls[0];
    expect(call[1]?.method).toBe("POST");
    expect(call[1]?.body).toBe(JSON.stringify({ password: "secret" }));
  });

  it("post throws ApiError on non-ok response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("Forbidden", { status: 403 }),
    );
    await expect(client.post("/test")).rejects.toMatchObject({ status: 403 });
  });

  it("get includes credentials", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200 }),
    );
    await client.get("/test");
    expect(vi.mocked(fetch).mock.calls[0][1]?.credentials).toBe("include");
  });
});

describe("connectSse", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("opens an EventSource at the given URL", () => {
    const disconnect = connectSse("http://localhost/sse", vi.fn());
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe("http://localhost/sse");
    disconnect();
  });

  it("calls onMessage when an event is received", () => {
    const onMessage = vi.fn();
    const disconnect = connectSse("http://localhost/sse", onMessage);

    const ev = new MessageEvent<string>("message", { data: '{"type":"tick"}' });
    FakeEventSource.instances[0].onmessage?.(ev);

    expect(onMessage).toHaveBeenCalledWith(ev);
    disconnect();
  });

  it("closes the EventSource on disconnect", () => {
    const disconnect = connectSse("http://localhost/sse", vi.fn());
    disconnect();
    expect(FakeEventSource.instances[0].close).toHaveBeenCalled();
  });

  it("calls onError when the EventSource emits an error", () => {
    const onError = vi.fn();
    const disconnect = connectSse("http://localhost/sse", vi.fn(), onError);

    // Suppress the re-open attempt in jsdom
    vi.useFakeTimers();
    FakeEventSource.instances[0].onerror?.(new Event("error"));
    expect(onError).toHaveBeenCalled();
    disconnect();
    vi.useRealTimers();
  });
});
