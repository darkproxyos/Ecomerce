"""Oportunidades de compra: cosas que podrías comprar para revender."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import clock
from ..database import get_db
from ..models import Opportunity, Product
from ..schemas import BuyIn, OpportunityCalc, OpportunityIn, OpportunityOut
from ..services import settings as cfg

router = APIRouter(prefix="/api", tags=["oportunidades"])


def calculate(o: Opportunity | OpportunityIn, default_fee_pct: float, target_margin: float) -> OpportunityCalc:
    buy = o.offer_price if o.offer_price is not None else o.asking_price
    fee_pct = o.fee_pct if o.fee_pct is not None else default_fee_pct
    resale = o.resale_price
    fee = resale * fee_pct / 100
    profit = resale - buy - fee - o.shipping - o.other_costs
    margin = profit / resale * 100 if resale else 0.0
    roi = profit / buy * 100 if buy else None
    max_pay = resale - fee - o.shipping - o.other_costs - resale * target_margin / 100
    if margin >= target_margin:
        verdict = "comprar"
    elif margin >= target_margin / 2:
        verdict = "rapido"
    else:
        verdict = "no"
    return OpportunityCalc(
        buy_price=round(buy, 2), fee_pct=fee_pct, fee=round(fee, 2), profit=round(profit, 2),
        margin_pct=round(margin, 1), roi_pct=round(roi, 1) if roi is not None else None,
        max_pay=round(max(max_pay, 0), 2), verdict=verdict,
    )


def _out(db: Session, o: Opportunity) -> OpportunityOut:
    out = OpportunityOut.model_validate(o)
    out.calc = calculate(o, cfg.get_float(db, f"fee_{o.channel}_pct"), cfg.get_float(db, "target_margin_pct", 30))
    return out


def _get(db: Session, opp_id: int) -> Opportunity:
    o = db.get(Opportunity, opp_id)
    if o is None:
        raise HTTPException(404, "Oportunidad no encontrada")
    return o


@router.get("/opportunities", response_model=list[OpportunityOut])
def list_opportunities(status: str = "", db: Session = Depends(get_db)):
    q = db.query(Opportunity)
    if status:
        q = q.filter(Opportunity.status == status)
    return [_out(db, o) for o in q.order_by(Opportunity.created_at.desc()).all()]


@router.post("/opportunities/calc", response_model=OpportunityCalc)
def calc_only(data: OpportunityIn, db: Session = Depends(get_db)):
    """Calcula sin guardar (para la calculadora en vivo)."""
    return calculate(data, cfg.get_float(db, f"fee_{data.channel}_pct"), cfg.get_float(db, "target_margin_pct", 30))


@router.post("/opportunities", response_model=OpportunityOut, status_code=201)
def create_opportunity(data: OpportunityIn, db: Session = Depends(get_db)):
    o = Opportunity(**data.model_dump())
    db.add(o)
    db.commit()
    db.refresh(o)
    return _out(db, o)


@router.put("/opportunities/{opp_id}", response_model=OpportunityOut)
def update_opportunity(opp_id: int, data: OpportunityIn, db: Session = Depends(get_db)):
    o = _get(db, opp_id)
    for k, v in data.model_dump().items():
        setattr(o, k, v)
    db.commit()
    return _out(db, o)


@router.delete("/opportunities/{opp_id}", status_code=204)
def delete_opportunity(opp_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, opp_id))
    db.commit()


@router.post("/opportunities/{opp_id}/buy")
def buy_opportunity(opp_id: int, data: BuyIn, db: Session = Depends(get_db)):
    """'La compré': crea el producto con su costo real y lo deja listo para publicar."""
    o = _get(db, opp_id)
    if o.product_id and db.get(Product, o.product_id):
        raise HTTPException(409, "Esta oportunidad ya se convirtió en producto")
    extra = data.other_costs if data.other_costs is not None else o.other_costs
    notes = "Comprado para revender"
    if o.url:
        notes += f". Anuncio original: {o.url}"
    if o.notes:
        notes += f"\n{o.notes}"
    p = Product(
        name=o.title[:200], cost=round(data.paid_price + extra, 2), price=o.resale_price, stock=1,
        min_stock=0, status="activo", condition="usado", supplier=o.source, notes=notes,
        listed_at=clock.now(),
    )
    db.add(p)
    db.flush()
    o.status = "comprado"
    o.offer_price = data.paid_price
    o.other_costs = extra
    o.product_id = p.id
    db.commit()
    return {"product_id": p.id, "opportunity": _out(db, o)}
