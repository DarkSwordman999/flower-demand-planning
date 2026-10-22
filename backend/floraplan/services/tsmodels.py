"""Статистические модели прогнозирования временных рядов спроса (ТЗ 4.8.4, математическое обеспечение).

Все функции работают с дневными рядами numpy (без пропусков, неотрицательные) и возвращают прогноз на h дней.
"""
import math
import warnings

import numpy as np

SEASON = 7          # недельная сезонность
Z = {0.5: 0.0, 0.8: 0.8416, 0.95: 1.6449}


def seasonal_naive(y: np.ndarray, h: int, season: int = SEASON) -> np.ndarray:
    """Продажи того же дня недели: среднее последних двух недель (устойчивее одной)."""
    if len(y) == 0:
        return np.zeros(h)
    if len(y) < season:
        return np.full(h, float(np.mean(y)))
    k = 2 if len(y) >= 2 * season else 1
    last = np.mean([y[len(y) - season * (i + 1): len(y) - season * i] for i in range(k)], axis=0)
    return np.array([last[i % season] for i in range(h)], dtype=float)


def holt_winters(y: np.ndarray, h: int, season: int = SEASON, trend: bool = False) -> np.ndarray:
    """Экспоненциальное сглаживание Хольта–Уинтерса с аддитивной недельной сезонностью
    (с затухающим трендом, если trend=True). Короткий ряд — сезонная наивная модель."""
    if len(y) < 4 * season or np.allclose(y, y[0]):
        return seasonal_naive(y, h, season)
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = ExponentialSmoothing(y.astype(float), trend="add" if trend else None, damped_trend=trend,
                                     seasonal="add", seasonal_periods=season, initialization_method="estimated")
        fit = model.fit(optimized=True)
        f = np.asarray(fit.forecast(h), dtype=float)
    if not np.all(np.isfinite(f)):
        return seasonal_naive(y, h, season)
    return np.clip(f, 0, None)


def croston(y: np.ndarray, h: int, alpha: float = 0.1) -> np.ndarray:
    """Метод Кростона с поправкой Сайнтетоса–Бойлана (SBA) для прерывистого спроса."""
    nz = np.flatnonzero(y > 0)
    if len(nz) == 0:
        return np.zeros(h)
    z = float(y[nz[0]])
    p = float(nz[0] + 1)
    last = nz[0]
    for i in nz[1:]:
        z = z + alpha * (y[i] - z)
        p = p + alpha * ((i - last) - p)
        last = i
    return np.full(h, (1 - alpha / 2) * z / max(p, 1.0))


def is_intermittent(y: np.ndarray) -> bool:
    """Прерывистый спрос: средний интервал между продажами больше 1,32 дня (классификация Сайнтетоса)."""
    nz = np.count_nonzero(y > 0)
    return nz > 0 and len(y) / nz > 1.32


ALGOS = {
    "seasonal_naive": lambda y, h, p: seasonal_naive(y, h),
    "holt_winters": lambda y, h, p: holt_winters(y, h, trend=bool(p.get("trend"))),
    "croston": lambda y, h, p: croston(y, h),
}


def wape(actual, forecast) -> float | None:
    a, f = np.asarray(actual, float), np.asarray(forecast, float)
    s = np.sum(np.abs(a))
    return float(np.sum(np.abs(a - f)) / s) if s > 0 else None


def bias(actual, forecast) -> float | None:
    """Смещение: (Σ прогноз − Σ факт) / Σ факт; > 0 — прогноз завышен."""
    a, f = np.asarray(actual, float), np.asarray(forecast, float)
    s = np.sum(a)
    return float((np.sum(f) - s) / s) if s > 0 else None


def select(y: np.ndarray, holdout: int, params: dict, candidates: list[str]) -> tuple[str, np.ndarray, np.ndarray]:
    """Выбор модели по WAPE на последних holdout днях. Возвращает (алгоритм, факт и прогноз на отложенном
    периоде) — по ошибкам этого периода оцениваются квантили."""
    if len(y) < holdout + 2 * SEASON:
        algo = candidates[0]
        return algo, np.array([]), np.array([])
    train, test = y[:-holdout], y[-holdout:]
    best = None
    for algo in candidates:
        f = ALGOS[algo](train, holdout, params)
        w = wape(test, f)
        score = w if w is not None else float(np.sum(f))
        if best is None or score < best[0] - 1e-12:
            best = (score, algo, f)
    return best[1], test, best[2]


def candidates_for(y: np.ndarray, algorithm: str) -> list[str]:
    if algorithm != "auto":
        return [algorithm]
    c = ["seasonal_naive", "holt_winters"]
    if is_intermittent(y[-90:] if len(y) > 90 else y):
        c.append("croston")
    return c


def error_profile(actual: np.ndarray, fc: np.ndarray) -> dict:
    """Распределение относительных ошибок (факт − прогноз) / прогноз на отложенном периоде."""
    if len(actual) == 0 or np.sum(fc) <= 0:
        return {"sigma": 0.5, "k80": None, "k95": None}
    denom = np.maximum(fc, 1.0)
    rel = (actual - fc) / denom
    return {"sigma": float(np.std(rel)), "k80": float(np.quantile(rel, 0.8)), "k95": float(np.quantile(rel, 0.95))}


def quantiles(p50: np.ndarray, prof: dict) -> tuple[np.ndarray, np.ndarray]:
    """P80 и P95: эмпирические квантили относительной ошибки, но не уже пуассоновского разброса √P50."""
    s = np.sqrt(np.maximum(p50, 0))
    k80 = prof["k80"] if prof["k80"] is not None else Z[0.8] * prof["sigma"]
    k95 = prof["k95"] if prof["k95"] is not None else Z[0.95] * prof["sigma"]
    p80 = np.maximum(p50 * (1 + max(k80, 0)), p50 + Z[0.8] * s)
    p95 = np.maximum(p50 * (1 + max(k95, 0)), p50 + Z[0.95] * s)
    p95 = np.maximum(p95, p80)
    return p80, p95


def period_quantile(p50: list[float], sigma_rel: float, q: float) -> float:
    """Квантиль спроса за период из дневных P50 (ошибки дней считаются независимыми)."""
    from statistics import NormalDist
    mean = float(sum(p50))
    var = sum(max(sigma_rel * x, 0.5 * math.sqrt(max(x, 0))) ** 2 for x in p50)
    z = NormalDist().inv_cdf(min(max(q, 0.5), 0.995))
    return max(0.0, mean + z * math.sqrt(var))
