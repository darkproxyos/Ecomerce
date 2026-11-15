"""Ejecuta vigilancias de precio y búsquedas de mercado, y las programa."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import MarketResult, MarketSearch, PriceSnapshot, WatchItem
from . import mercadolibre as ml
from . import scraper

log = logging.getLogger("market")


def _ml_token(db: Session) -> str:
    try:
        return ml.access_token(db)
    except Exception:  # noqa: BLE001 - token caducado o sin red: se sigue sin token
        return ""


def run_watch(db: Session, watch: WatchItem) -> WatchItem:
    watch.last_checked = datetime.now()
    try:
        info = scraper.fetch_page_info(watch.url, watch.css_selector, _ml_token(db))
    except scraper.ScrapeError as exc:
        watch.last_error = str(exc)
        db.commit()
        return watch
    watch.last_error = ""
    if info.title:
        watch.last_title = info.title[:500]
        if not watch.name:
            watch.name = info.title[:200]
    if info.image:
        watch.last_image = info.image[:1000]
    if info.price is not None:
        if watch.last_price is not None and info.price != watch.last_price:
            watch.prev_price = watch.last_price
        watch.last_price = info.price
        db.add(PriceSnapshot(watch_id=watch.id, price=info.price))
    db.commit()
    return watch


def run_search(db: Session, search: MarketSearch) -> MarketSearch:
    now = datetime.now()
    search.last_run = now
    try:
        resp = scraper.search_mercadolibre(search.query, search.site, _ml_token(db))
    except scraper.ScrapeError as exc:
        search.last_error = str(exc)
        db.commit()
        return search
    search.last_error = ""
    search.last_source = resp.source
    existing = {r.external_id: r for r in search.results}
    for item in resp.items:
        row = existing.get(item.external_id)
        if row is None:
            row = MarketResult(search_id=search.id, external_id=item.external_id, first_seen=now)
            db.add(row)
            existing[item.external_id] = row
        elif item.price is not None and row.price is not None and item.price != row.price:
            row.prev_price = row.price
        row.title = item.title[:500]
        if item.price is not None:
            row.price = item.price
        row.url = item.url[:1000]
        row.thumbnail = item.thumbnail[:1000]
        row.seller = item.seller[:200]
        row.sold_quantity = item.sold_quantity
        row.free_shipping = item.free_shipping
        row.last_seen = now
    db.commit()
    return search


def run_due(db: Session) -> dict:
    now = datetime.now()
    done = {"watches": 0, "searches": 0}
    for w in db.query(WatchItem).filter(WatchItem.active.is_(True)).all():
        if w.last_checked is None or w.last_checked + timedelta(hours=w.interval_hours) <= now:
            run_watch(db, w)
            done["watches"] += 1
    for s in db.query(MarketSearch).filter(MarketSearch.active.is_(True)).all():
        if s.last_run is None or s.last_run + timedelta(hours=s.interval_hours) <= now:
            run_search(db, s)
            done["searches"] += 1
    return done


def _run_due_job() -> dict:
    db = SessionLocal()
    try:
        return run_due(db)
    finally:
        db.close()


async def scheduler_loop(tick_seconds: int) -> None:
    while True:
        try:
            done = await asyncio.to_thread(_run_due_job)
            if any(done.values()):
                log.info("Scraping programado: %s", done)
        except Exception:  # noqa: BLE001
            log.exception("Error en el planificador de scraping")
        await asyncio.sleep(tick_seconds)
