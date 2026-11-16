from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from .. import clock
from ..database import get_db
from ..models import MarketResult, MarketSearch, PriceSnapshot, WatchItem
from ..schemas import ResultOut, SearchIn, SearchOut, SnapshotOut, WatchIn, WatchOut
from ..services import market, scraper
from ..services.scraper import ML_DOMAINS

router = APIRouter(prefix="/api", tags=["mercado"])

NEW_WINDOW = timedelta(hours=48)


# ------------------------------------------------------------------ vigilancia de precios

def watch_out(db: Session, w: WatchItem) -> WatchOut:
    out = WatchOut.model_validate(w)
    if w.product:
        out.product_name = w.product.name
        out.product_price = w.product.price
    prices = [s.price for s in w.snapshots]
    if prices:
        out.min_price, out.max_price = min(prices), max(prices)
    return out


def _get_watch(db: Session, watch_id: int) -> WatchItem:
    w = db.get(WatchItem, watch_id)
    if w is None:
        raise HTTPException(404, "Vigilancia no encontrada")
    return w


@router.get("/watches", response_model=list[WatchOut])
def list_watches(db: Session = Depends(get_db)):
    rows = (db.query(WatchItem).options(selectinload(WatchItem.snapshots), selectinload(WatchItem.product))
            .order_by(WatchItem.created_at.desc()).all())
    return [watch_out(db, w) for w in rows]


@router.post("/watches", response_model=WatchOut, status_code=201)
def create_watch(data: WatchIn, check_now: bool = True, db: Session = Depends(get_db)):
    w = WatchItem(**data.model_dump())
    db.add(w)
    db.commit()
    if check_now:
        market.run_watch(db, w)
    db.refresh(w)
    return watch_out(db, w)


@router.put("/watches/{watch_id}", response_model=WatchOut)
def update_watch(watch_id: int, data: WatchIn, db: Session = Depends(get_db)):
    w = _get_watch(db, watch_id)
    for k, v in data.model_dump().items():
        setattr(w, k, v)
    db.commit()
    return watch_out(db, w)


@router.delete("/watches/{watch_id}", status_code=204)
def delete_watch(watch_id: int, db: Session = Depends(get_db)):
    db.delete(_get_watch(db, watch_id))
    db.commit()


@router.post("/watches/{watch_id}/check", response_model=WatchOut)
def check_watch(watch_id: int, db: Session = Depends(get_db)):
    w = market.run_watch(db, _get_watch(db, watch_id))
    db.refresh(w)
    return watch_out(db, w)


@router.get("/watches/{watch_id}/history", response_model=list[SnapshotOut])
def watch_history(watch_id: int, db: Session = Depends(get_db)):
    _get_watch(db, watch_id)
    return (db.query(PriceSnapshot).filter_by(watch_id=watch_id)
            .order_by(PriceSnapshot.checked_at).all())


@router.post("/scrape/test")
def test_scrape(data: WatchIn):
    """Prueba una URL/selector sin guardar nada."""
    try:
        info = scraper.fetch_page_info(data.url, data.css_selector)
    except scraper.ScrapeError as exc:
        raise HTTPException(422, str(exc)) from exc
    return info.__dict__


# ------------------------------------------------------------------ búsquedas de mercado

def search_out(s: MarketSearch) -> SearchOut:
    out = SearchOut.model_validate(s)
    results = s.results
    # Solo los resultados vistos en la última corrida representan el mercado actual.
    current = [r for r in results if s.last_run is None or r.last_seen >= s.last_run - timedelta(minutes=5)]
    prices = sorted(r.price for r in current if r.price)
    out.result_count = len(current)
    if s.last_run:
        out.new_count = sum(1 for r in results if r.first_seen >= s.last_run - NEW_WINDOW
                            and r.first_seen > s.created_at + timedelta(minutes=5))
    if prices:
        out.min_price, out.max_price = prices[0], prices[-1]
        out.avg_price = round(sum(prices) / len(prices), 2)
    return out


def _get_search(db: Session, search_id: int) -> MarketSearch:
    s = db.get(MarketSearch, search_id)
    if s is None:
        raise HTTPException(404, "Búsqueda no encontrada")
    return s


@router.get("/ml-sites")
def ml_sites():
    return ML_DOMAINS


@router.get("/searches", response_model=list[SearchOut])
def list_searches(db: Session = Depends(get_db)):
    rows = (db.query(MarketSearch).options(selectinload(MarketSearch.results))
            .order_by(MarketSearch.created_at.desc()).all())
    return [search_out(s) for s in rows]


@router.post("/searches", response_model=SearchOut, status_code=201)
def create_search(data: SearchIn, run_now: bool = True, db: Session = Depends(get_db)):
    if data.site not in ML_DOMAINS:
        raise HTTPException(400, f"Sitio inválido, usa uno de {list(ML_DOMAINS)}")
    s = MarketSearch(**data.model_dump())
    db.add(s)
    db.commit()
    if run_now:
        market.run_search(db, s)
    db.refresh(s)
    return search_out(s)


@router.put("/searches/{search_id}", response_model=SearchOut)
def update_search(search_id: int, data: SearchIn, db: Session = Depends(get_db)):
    s = _get_search(db, search_id)
    for k, v in data.model_dump().items():
        setattr(s, k, v)
    db.commit()
    return search_out(s)


@router.delete("/searches/{search_id}", status_code=204)
def delete_search(search_id: int, db: Session = Depends(get_db)):
    db.delete(_get_search(db, search_id))
    db.commit()


@router.post("/searches/{search_id}/run", response_model=SearchOut)
def run_search(search_id: int, db: Session = Depends(get_db)):
    s = market.run_search(db, _get_search(db, search_id))
    db.refresh(s)
    return search_out(s)


@router.get("/searches/{search_id}/results", response_model=list[ResultOut])
def search_results(search_id: int, only_new: bool = False, sort: str = "price",
                   db: Session = Depends(get_db)):
    s = _get_search(db, search_id)
    out = []
    for r in s.results:
        o = ResultOut.model_validate(r)
        o.is_new = (s.last_run is not None and r.first_seen >= s.last_run - NEW_WINDOW
                    and r.first_seen > s.created_at + timedelta(minutes=5))
        if only_new and not o.is_new:
            continue
        out.append(o)
    keys = {
        "price": lambda r: (r.price is None, r.price or 0),
        "sold": lambda r: -(r.sold_quantity or 0),
        "recent": lambda r: -r.first_seen.timestamp(),
    }
    out.sort(key=keys.get(sort, keys["price"]))
    return out


@router.post("/market/run-due")
def run_due(db: Session = Depends(get_db)):
    """Ejecuta ahora todo lo pendiente (lo mismo que hace el planificador)."""
    return market.run_due(db)


@router.get("/market/new-products")
def new_products(hours: int = 48, db: Session = Depends(get_db)):
    since = clock.now() - timedelta(hours=hours)
    rows = (db.query(MarketResult).join(MarketSearch)
            .filter(MarketResult.first_seen >= since)
            .order_by(MarketResult.first_seen.desc()).limit(300).all())
    # Lo encontrado en la primera corrida de una búsqueda no es "nuevo", es la línea base.
    rows = [r for r in rows if r.first_seen > r.search.created_at + timedelta(minutes=5)][:100]
    return [{**ResultOut.model_validate(r).model_dump(), "is_new": True, "query": r.search.query}
            for r in rows]
