import dayjs from "dayjs";

export const money = (v?: number | null) =>
  v === null || v === undefined ? "—" : v.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const num = (v?: number | null, digits = 1) =>
  v === null || v === undefined ? "—" : v.toLocaleString("ru-RU", { maximumFractionDigits: digits });

export const pct = (v?: number | null) => (v === null || v === undefined ? "—" : `${num(v, 1)} %`);

export const d = (v?: string | null) => (v ? dayjs(v).format("DD.MM.YYYY") : "—");

export const dt = (v?: string | null) => (v ? dayjs(v).format("DD.MM.YYYY HH:mm") : "—");

export const iso = (v: dayjs.Dayjs | null | undefined) => (v ? v.format("YYYY-MM-DD") : undefined);

export const ORDER_COLORS: Record<string, string> = {
  draft: "default",
  approval: "orange",
  approved: "blue",
  sent: "geekblue",
  confirmed: "cyan",
  in_transit: "purple",
  received: "green",
  closed: "default",
  cancelled: "red",
};

export const BATCH_STATES: Record<string, [string, string]> = {
  fresh: ["Свежая", "green"],
  expiring: ["Срок истекает", "orange"],
  marked_down: ["Уценена", "gold"],
  expired: ["Срок истёк", "red"],
  sold: ["Продана", "default"],
  written_off: ["Списана", "default"],
};

export const ONLINE_COLORS: Record<string, string> = {
  new: "blue",
  preorder: "purple",
  reserved: "cyan",
  completed: "green",
  cancelled: "red",
};

export const ALGORITHMS: Record<string, string> = {
  auto: "Автовыбор по ряду",
  seasonal_naive: "Сезонная наивная",
  holt_winters: "Хольт–Уинтерс",
  croston: "Метод Кростона",
};
