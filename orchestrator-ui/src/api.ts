export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

// ---------------------------------------------------------------------------
// Typed API client
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export class ApiClient {
  constructor(private readonly base: string = API_BASE) {}

  async get<T>(path: string, signal?: AbortSignal): Promise<T> {
    const res = await fetch(`${this.base}${path}`, {
      credentials: "include",
      signal,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText);
      throw new ApiError(res.status, text);
    }
    return res.json() as Promise<T>;
  }

  async post<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    const res = await fetch(`${this.base}${path}`, {
      method: "POST",
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: "include",
      signal,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText);
      throw new ApiError(res.status, text);
    }
    return res.json() as Promise<T>;
  }

  async put<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    const res = await fetch(`${this.base}${path}`, {
      method: "PUT",
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: "include",
      signal,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText);
      throw new ApiError(res.status, text);
    }
    return res.json() as Promise<T>;
  }
}

export const apiClient = new ApiClient();

// ---------------------------------------------------------------------------
// SSE client with exponential-backoff reconnect
// ---------------------------------------------------------------------------

export type SseHandler = (event: MessageEvent<string>) => void;
export type SseErrorHandler = (event: Event) => void;

const SSE_BASE_DELAY_MS = 1_000;
const SSE_MAX_DELAY_MS = 30_000;

/**
 * Open an EventSource to `url` and call `onMessage` for each unnamed event.
 * Named event types can be handled via the optional `onEvent` map.
 * On error the connection is closed and re-opened with exponential backoff.
 * Returns a cleanup function that permanently closes the connection.
 */
export function connectSse(
  url: string,
  onMessage: SseHandler,
  onError?: SseErrorHandler,
  onEvent?: Record<string, SseHandler>,
): () => void {
  let es: EventSource | null = null;
  let closed = false;
  let delay = SSE_BASE_DELAY_MS;
  let timer: ReturnType<typeof setTimeout> | null = null;

  function open() {
    if (closed) return;
    es = new EventSource(url, { withCredentials: true });

    es.onmessage = (ev: MessageEvent<string>) => {
      delay = SSE_BASE_DELAY_MS;
      onMessage(ev);
    };

    if (onEvent) {
      for (const [type, handler] of Object.entries(onEvent)) {
        es.addEventListener(type, (ev: Event) => {
          delay = SSE_BASE_DELAY_MS;
          handler(ev as MessageEvent<string>);
        });
      }
    }

    es.onerror = (ev: Event) => {
      onError?.(ev);
      es?.close();
      es = null;
      if (!closed) {
        timer = setTimeout(() => {
          delay = Math.min(delay * 2, SSE_MAX_DELAY_MS);
          open();
        }, delay);
      }
    };
  }

  open();

  return () => {
    closed = true;
    if (timer !== null) clearTimeout(timer);
    es?.close();
  };
}
