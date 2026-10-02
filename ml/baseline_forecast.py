"""Базовый прототип прогнозирования спроса на цветочную продукцию и расчёта заказа.

Данные синтетические — дневные продажи нескольких товаров в нескольких салонах
с недельной сезонностью, праздничными пиками (14.02, 08.03, 01.09, 31.12) и влиянием
температуры. В дипломной работе генератор заменяется выгрузкой продаж из «1С:Розница».

Сравниваются:
  * сезонная наивная модель (продажи того же дня недели неделю назад);
  * градиентный бустинг с лаговыми, календарными и погодными признаками.
Метрика: WAPE = Σ|факт − прогноз| / Σ факт.

Дополнительно показан расчёт заказа по модели «продавца газет» (newsvendor):
целевой уровень обслуживания α = Cu / (Cu + Co).

Запуск:  python ml/baseline_forecast.py
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

RNG = np.random.default_rng(7)
HOLIDAYS = {(2, 14): 4.0, (3, 8): 9.0, (9, 1): 3.0, (12, 31): 2.5}   # множители спроса в день праздника


def make_sales() -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", "2026-08-31", freq="D")
    items = {"Роза 60 см": 40, "Хризантема кустовая": 25, "Тюльпан": 15, "Эустома": 10, "Гвоздика": 12}
    stores = ["Салон 1", "Салон 2", "Салон 3", "Интернет-магазин"]
    temp = 8 + 14 * np.sin(2 * np.pi * (dates.dayofyear - 110) / 365) + RNG.normal(0, 3, len(dates))
    rows = []
    for item, base in items.items():
        for k, store in enumerate(stores):
            level = base * (1.3 - 0.2 * k)
            for i, d in enumerate(dates):
                m = 1 + 0.35 * (d.dayofweek >= 4)                                    # пятница–воскресенье
                if item == "Тюльпан":
                    m *= 2.5 if d.month in (3, 4) else 0.4                            # сезонный товар
                for (mm, dd), mult in HOLIDAYS.items():
                    delta = (pd.Timestamp(d.year, mm, dd) - d).days
                    if 0 <= delta <= 2:
                        m *= 1 + (mult - 1) / (delta + 1)                             # рост за 2 дня до праздника
                m *= 1 + 0.01 * (temp[i] - 10)
                rows.append((d, item, store, RNG.poisson(max(level * m, 0.1)), temp[i]))
    return pd.DataFrame(rows, columns=["date", "item", "store", "qty", "temp"])


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["item", "store", "date"]).copy()
    g = df.groupby(["item", "store"])["qty"]
    for lag in (7, 14, 364):
        df[f"lag_{lag}"] = g.shift(lag)
    df["roll_7"] = g.transform(lambda s: s.shift(7).rolling(7).mean())
    df["dow"] = df["date"].dt.dayofweek
    df["month"] = df["date"].dt.month
    days_to = []
    for d in df["date"]:
        nxt = min(((pd.Timestamp(d.year + (pd.Timestamp(d.year, m, dd) < d), m, dd) - d).days)
                  for (m, dd) in HOLIDAYS)
        days_to.append(min(nxt, 30))
    df["days_to_holiday"] = days_to
    df["item_id"] = df["item"].astype("category").cat.codes
    df["store_id"] = df["store"].astype("category").cat.codes
    return df.dropna()


def wape(y, p) -> float:
    return float(np.abs(y - p).sum() / y.sum())


def main() -> None:
    df = add_features(make_sales())
    feats = ["lag_7", "lag_14", "lag_364", "roll_7", "dow", "month", "days_to_holiday", "temp", "item_id", "store_id"]
    split = pd.Timestamp("2026-03-01")
    tr, te = df[df["date"] < split], df[df["date"] >= split]

    print(f"Строк обучения: {len(tr)}, теста: {len(te)} (период {split.date()} — {te['date'].max().date()})")
    print(f"Сезонная наивная модель:   WAPE = {wape(te['qty'], te['lag_7']):.1%}")

    p50 = HistGradientBoostingRegressor(loss="poisson", max_iter=400, learning_rate=0.05, random_state=0)
    p50.fit(tr[feats], tr["qty"])
    pred = p50.predict(te[feats])
    print(f"Градиентный бустинг (P50): WAPE = {wape(te['qty'].values, pred):.1%}")
    hol = te["days_to_holiday"] <= 2
    print(f"  в т. ч. в предпраздничные дни: WAPE = {wape(te.loc[hol, 'qty'].values, pred[hol.values]):.1%}")

    # квантильная модель для расчёта заказа скоропортящегося товара
    cu, co = 120.0, 65.0                       # упущенная маржа и потери от списания одного стебля, руб.
    alpha = cu / (cu + co)
    q = HistGradientBoostingRegressor(loss="quantile", quantile=alpha, max_iter=300, learning_rate=0.05, random_state=0)
    q.fit(tr[feats], tr["qty"])
    day = te[(te["date"] == pd.Timestamp("2026-03-06")) & (te["item"] == "Роза 60 см")]
    need = q.predict(day[feats]).sum()
    stock, pack = 60, 25
    order = max(0.0, need - stock)
    order = int(np.ceil(order / pack) * pack)
    print(f"\nNewsvendor: α = {alpha:.2f}; потребность в розах на 06.03.2026 по всем точкам = {need:.0f} шт.,"
          f" остаток = {stock}, заказ с кратностью {pack} = {order} шт.")


if __name__ == "__main__":
    main()
