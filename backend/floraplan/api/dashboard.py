"""Главная страница: ключевые показатели для роли пользователя."""
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import appsettings
from ..db import get_db
from ..models import (Batch, OnlineOrder, PurchaseOrder, Sale, SaleLine, StockoutDay, User, WriteOff)
from ..security import current_user
from ..services import analytics as an
from ..services import expiry, forecasting as fs

router = APIRouter(prefix="/api/dashboard", tags=["Главная"])


@router.get("")
def dashboard(me: User = Depends(current_user), db: Session = Depends(get_db)):
    today = date.today()
    week_ago = today - timedelta(days=6)
    month_ago = today - timedelta(days=29)
    loc = me.location_id if me.role == "florist" else None

    def sales_sum(a, b):
        q = (db.query(func.coalesce(func.sum(SaleLine.qty * SaleLine.price - SaleLine.discount), 0.0))
             .join(Sale).filter(Sale.day >= a, Sale.day <= b))
        if loc:
            q = q.filter(Sale.location_id == loc)
        return round(float(q.scalar()), 2)

    wo = float(db.query(func.coalesce(func.sum(WriteOff.qty * WriteOff.cost), 0.0)).filter(
        WriteOff.ts >= datetime.combine(month_ago, time.min)).scalar())
    purchased = an.received_cost(db, month_ago, today)
    recs = expiry.recommendations(db, loc)
    cur = fs.current_run(db)
    acc = an.accuracy(db, today - timedelta(days=28), today - timedelta(days=1))
    daily = []
    for i in range(29, -1, -1):
        d = today - timedelta(days=i)
        daily.append({"day": d, "revenue": 0.0})
    idx = {x["day"]: x for x in daily}
    q = (db.query(Sale.day, func.sum(SaleLine.qty * SaleLine.price - SaleLine.discount)).join(SaleLine)
         .filter(Sale.day >= month_ago))
    if loc:
        q = q.filter(Sale.location_id == loc)
    for d, v in q.group_by(Sale.day):
        if d in idx:
            idx[d]["revenue"] = round(v or 0, 2)
    return {
        "today": today,
        "sales_today": sales_sum(today, today),
        "sales_week": sales_sum(week_ago, today),
        "sales_daily": daily,
        "writeoff_share_pct": round(wo / purchased * 100, 1) if purchased else None,
        "writeoff_cost_month": round(wo, 2),
        "expiring_batches": len(recs),
        "markdown_needed": sum(1 for r in recs if r["recommendation"] == "уценить"),
        "expired_batches": db.query(Batch).filter(Batch.qty - Batch.reserved > 1e-9, Batch.expiry_date < today).count(),
        "orders_awaiting_approval": db.query(PurchaseOrder).filter(PurchaseOrder.status == "approval").count(),
        "orders_in_transit": db.query(PurchaseOrder).filter(PurchaseOrder.status == "in_transit").count(),
        "orders_drafts": db.query(PurchaseOrder).filter(PurchaseOrder.status == "draft").count(),
        "online_to_process": db.query(OnlineOrder).filter(OnlineOrder.status.in_(("new", "preorder", "reserved"))).count(),
        "stockouts_week": db.query(StockoutDay).filter(StockoutDay.day >= week_ago).count(),
        "forecast_date": cur.base_date if cur else None,
        "forecast_stale": cur is None or cur.base_date < today,
        "forecast_wape_pct": acc.get("totals", {}).get("wape_pct"),
        "weekly_budget": appsettings.get(db, "weekly_budget"),
    }
