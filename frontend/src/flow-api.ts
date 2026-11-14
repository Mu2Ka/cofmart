import { request } from "./api";

export type Product = {
  id: string;
  name: string;
  category: string;
  sizes: Record<string, number>;
  alternative_milk: boolean;
  available: boolean;
  variants: Record<string, { name: string; price: number }>;
};
export type Slots = {
  limit: number;
  free: number;
  reserved: number;
  confirmed: number;
  revision: number;
  active: number;
  completed: number;
};
export type Cafe = {
  id: string;
  name: string;
  open: boolean;
  slots: Slots | null;
  products: Product[];
};
export type Draft = {
  token: string;
  cafe_id: string;
  drink_id: string;
  cafe_name: string;
  drink_name: string;
  comment: string;
  price: number;
  reserved_until: string;
  pickup_label: string;
};
export type Order = {
  transitions: string[];
  number: number;
  reference: string;
  draft: Draft;
  status: string;
  status_label: string;
  revision: number;
  barista_id: number | null;
  rating: number | null;
  created_at: string;
};
export type Favorite = {
  key: string;
  cafe_id: string;
  drink_id: string;
  cafe_name: string;
  drink_name: string;
};
export type State = {
  summaries: Record<string, Record<string, number>>;
  user_id: number;
  admin: boolean;
  staff_cafes: string[];
  cafes: Cafe[];
  categories: Record<string, string>;
  periods: { id: string; label: string }[];
  follow_schedule: boolean;
  schedule_message: string;
  pauses: string[];
  session: string;
  draft: Draft | null;
  orders: Order[];
  favorites: Favorite[];
};
export type Staff = {
  orders: Order[];
  periods: (Slots & { id: string; label: string })[];
  rating_count: number;
  rating_average: number | null;
  baristas: number[];
};
export const loadState = () => request<State>("/flow/state");
export const loadStaff = (id: string) => request<Staff>(`/flow/staff/${id}`);
export const act = (action: string, values: Record<string, unknown> = {}) =>
  request<{ result: unknown }>("/flow/action", { action, ...values });
