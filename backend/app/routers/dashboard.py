from collections import defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import CHANNELS, Expense, MarketResult, MarketSearch, Product, Sale, WatchItem
from ..services import settings as cfg

router = APIRouter(prefix="/api", tags=["dashboard"])


def _period_stats(sales: list[Sale], expenses: list[Expense]) -> dict:
    valid = [s for s in sales if s.status != "cancelado"]
    revenue = sum(s.total for s in valid)
    gross = sum(s.profit for s in valid)
    exp = sum(e.amount for e in expenses)
    return {
        "revenue": round(revenue, 2),
        "gross_profit": round(gross, 2),
        "expenses": round(exp, 2),
        "net_profit": round(gross - exp, 2),
        "orders": len(valid),
        "units": sum(i.quantity for s in valid for i in s.items),
        "avg_ticket": round(revenue / len(valid), 2) if valid else 0,
        "commissions": round(sum(s.commission + s.shipping_cost for s in valid), 2),
        "cancelled": len(sales) - len(valid),
    }


def _load(db: Session, start: date, end: date):
    sales = (db.query(Sale).options(selectinload(Sale.items), selectinload(Sale.customer))
             .filter(Sale.date >= start, Sale.date <= end).all())
    expenses = db.query(Expense).filter(Expense.date >= start, Expense.date <= end).all()
    return sales, expenses


@router.get("/dashboard")
def dashboard(days: int = 30, db: Session = Depends(get_db)):
    days = max(1, min(days, 730))
    today = date.today()
    start = today - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)

    sales, expenses = _load(db, start, today)
    prev_sales, prev_expenses = _load(db, prev_start, prev_end)
    current = _period_stats(sales, expenses)
    previous = _period_stats(prev_sales, prev_expenses)

    # Serie diaria (o semanal si el periodo es largo) por canal.
    bucket_days = 1 if days <= 62 else 7
    buckets: list[date] = []
    d = start
    while d <= today:
        buckets.append(d)
        d += timedelta(days=bucket_days)

    def bucket_of(x: date) -> date:
        return start + timedelta(days=((x - start).days // bucket_days) * bucket_days)

    by_day: dict[date, dict] = {b: {"revenue": 0.0, "profit": 0.0, **{c: 0.0 for c in CHANNELS}}
                                for b in buckets}
    by_channel: dict[str, dict] = {c: {"revenue": 0.0, "orders": 0, "profit": 0.0} for c in CHANNELS}
    by_product: dict[str, dict] = defaultdict(lambda: {"revenue": 0.0, "units": 0, "profit": 0.0})
    by_category: dict[str, float] = defaultdict(float)

    for s in sales:
        if s.status == "cancelado":
            continue
        row = by_day[bucket_of(s.date)]
        row["revenue"] += s.total
        row["profit"] += s.profit
        row[s.channel] += s.total
        ch = by_channel[s.channel]
        ch["revenue"] += s.total
        ch["orders"] += 1
        ch["profit"] += s.profit
        share = (s.commission + s.shipping_cost) / s.total if s.total else 0
        for i in s.items:
            name = i.product.name if i.product else (i.description or "Sin producto")
            line = i.quantity * i.unit_price
            p = by_product[name]
            p["revenue"] += line
            p["units"] += i.quantity
            p["profit"] += line - i.quantity * i.unit_cost - line * share
            by_category[(i.product.category if i.product else "") or "Sin categoría"] += line

    def rnd(d: dict) -> dict:
        return {k: round(v, 2) if isinstance(v, float) else v for k, v in d.items()}

    products = db.query(Product).all()
    low_stock = sorted(
        [{"id": p.id, "name": p.name, "sku": p.sku, "stock": p.stock, "min_stock": p.min_stock}
         for p in products if p.status != "borrador" and p.stock <= p.min_stock],
        key=lambda x: x["stock"],
    )

    # Alertas de competencia: competidor más barato que mi precio, o precio que cambió.
    alert_pct = cfg.get_float(db, "alert_cheaper_pct")
    alerts = []
    for w in db.query(WatchItem).options(selectinload(WatchItem.product)).filter(WatchItem.active.is_(True)):
        if w.last_price is None:
            continue
        if w.product and w.product.price and w.last_price < w.product.price * (1 - alert_pct / 100):
            alerts.append({"type": "cheaper", "watch_id": w.id, "name": w.name or w.last_title,
                           "competitor_price": w.last_price, "my_price": w.product.price,
                           "product": w.product.name, "url": w.url})
        elif w.prev_price is not None and w.prev_price != w.last_price:
            alerts.append({"type": "changed", "watch_id": w.id, "name": w.name or w.last_title,
                           "competitor_price": w.last_price, "prev_price": w.prev_price, "url": w.url})

    since = datetime.now() - timedelta(hours=48)
    new_market = [r for r in db.query(MarketResult).join(MarketSearch)
                  .filter(MarketResult.first_seen >= since).all()
                  if r.first_seen > r.search.created_at + timedelta(minutes=5)]

    recent = sorted(sales, key=lambda s: (s.date, s.id), reverse=True)[:8]

    return {
        "period": {"from": start.isoformat(), "to": today.isoformat(), "days": days,
                   "bucket_days": bucket_days},
        "kpis": current,
        "previous": previous,
        "series": [{"date": b.isoformat(), **rnd(by_day[b])} for b in buckets],
        "by_channel": [{"channel": c, **rnd(v)} for c, v in by_channel.items() if v["orders"]],
        "top_products": sorted(({"name": k, **rnd(v)} for k, v in by_product.items()),
                               key=lambda x: x["revenue"], reverse=True)[:8],
        "by_category": sorted(({"category": k, "revenue": round(v, 2)} for k, v in by_category.items()),
                              key=lambda x: x["revenue"], reverse=True)[:8],
        "inventory": {
            "products": len(products),
            "active": sum(1 for p in products if p.status == "activo"),
            "units": sum(max(p.stock, 0) for p in products),
            "cost_value": round(sum(p.cost * max(p.stock, 0) for p in products), 2),
            "retail_value": round(sum(p.price * max(p.stock, 0) for p in products), 2),
        },
        "low_stock": low_stock[:10],
        "alerts": alerts[:10],
        "new_market_count": len(new_market),
        "pending_orders": sum(1 for s in sales if s.status in ("pendiente", "pagado")),
        "recent_sales": [{"id": s.id, "date": s.date.isoformat(), "channel": s.channel,
                          "status": s.status, "total": s.total, "profit": s.profit,
                          "customer": s.customer.name if s.customer else "",
                          "items": ", ".join(f"{i.quantity}× {i.description}" for i in s.items)}
                         for s in recent],
    }
