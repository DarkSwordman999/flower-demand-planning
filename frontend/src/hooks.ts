import { App } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Загрузка данных с повтором и показом ошибки. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const { message } = App.useApp();
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const reload = useCallback(() => {
    const my = ++seq.current;
    setLoading(true);
    return fn()
      .then((d) => {
        if (my === seq.current) setData(d);
      })
      .catch((e) => message.error(e.message))
      .finally(() => {
        if (my === seq.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    reload();
  }, [reload]);
  return { data, loading, reload, setData };
}

/** Выполнить действие с сообщением об успехе или ошибке. */
export function useAction() {
  const { message } = App.useApp();
  const [busy, setBusy] = useState(false);
  const run = async <T,>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> => {
    setBusy(true);
    try {
      const r = await fn();
      if (ok) message.success(ok);
      return r;
    } catch (e: any) {
      message.error(e.message);
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return { busy, run };
}

export interface Ref {
  id: number;
  name: string;
  [k: string]: any;
}

const cache: Record<string, Promise<Ref[]> | undefined> = {};

/** Справочники для выпадающих списков (кэш на сеанс; refresh — после изменений). */
export function useRefs(kind: "products" | "locations" | "groups" | "suppliers" | "writeoff-reasons") {
  const [items, setItems] = useState<Ref[]>([]);
  useEffect(() => {
    if (!cache[kind]) cache[kind] = api.get<Ref[]>(`/api/nsi/${kind}`).catch(() => []);
    cache[kind]!.then(setItems);
  }, [kind]);
  return items;
}

export function refreshRefs(kind?: string) {
  if (kind) delete cache[kind];
  else Object.keys(cache).forEach((k) => delete cache[k]);
  if (!kind || kind === "settings") settingsCache = undefined;
}

/** Параметры системы (пороги уценки, срок «истекает», горизонт прогноза…) — как их задал директор. */
export interface SystemSettings {
  expiring_days: number;
  markdown_min: number;
  markdown_max: number;
  change_reason_pct: number;
  forecast_horizon: number;
  [k: string]: any;
}

const SETTINGS_DEFAULTS: SystemSettings = { expiring_days: 2, markdown_min: 10, markdown_max: 50, change_reason_pct: 30, forecast_horizon: 14 };
let settingsCache: Promise<SystemSettings> | undefined;

export function useSettings(): SystemSettings {
  const [s, setS] = useState<SystemSettings>(SETTINGS_DEFAULTS);
  useEffect(() => {
    if (!settingsCache) settingsCache = api.get<SystemSettings>("/api/admin/settings").catch(() => SETTINGS_DEFAULTS);
    settingsCache.then((v) => setS({ ...SETTINGS_DEFAULTS, ...v }));
  }, []);
  return s;
}
