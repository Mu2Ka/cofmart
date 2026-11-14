import { initData } from "./telegram";

export type Cafe = { id: number; name: string; timezone: string };
export type MenuItem = {
  id: number;
  cafe_id: number;
  name: string;
  price_minor: number;
};
export type Slot = { id: number; starts_at: string; available: number };
export type ItemInput = { menu_item_id: number; quantity: number };
export type Line = ItemInput & { name: string; price_minor: number };
export type Preview = { cafe_id: number; items: Line[]; total_minor: number };
export type Order = Preview & {
  id: number;
  cafe_name: string;
  timezone: string;
  starts_at: string;
  slot_id: number;
  status: string;
  created_at: string;
};
export type OrderRequest = {
  cafe_id: number;
  slot_id: number;
  items: ItemInput[];
  expected_total_minor: number;
  idempotency_key: string;
};

export class ApiError extends Error {
  constructor(
    message: string,
    public code: string,
    public status: number,
  ) {
    super(message);
  }
}

const base = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

export async function request<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      Authorization: `tma ${initData}`,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: signal ?? AbortSignal.timeout(20000),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    const message =
      typeof error.detail === "string" ? error.detail : error.message;
    throw new ApiError(
      message ?? "Не удалось выполнить запрос. Попробуйте ещё раз.",
      error.code ?? "HTTP_ERROR",
      response.status,
    );
  }
  return response.json();
}
