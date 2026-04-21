const BASE_URL = `${import.meta.env.VITE_API_BASE_URL ?? ""}/api/v1`;

class ApiRequestError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

async function extractErrorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) {
        return detail
          .map((d) =>
            d && typeof d === "object" && "msg" in d
              ? String((d as { msg: unknown }).msg)
              : JSON.stringify(d),
          )
          .join("; ");
      }
      return JSON.stringify(detail);
    }
  } catch {
    // response body not JSON — fall through
  }
  return `HTTP ${response.status}`;
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new ApiRequestError(response.status, await extractErrorDetail(response));
  }
  return response.json() as Promise<T>;
}

export { ApiRequestError, BASE_URL, handleResponse };
