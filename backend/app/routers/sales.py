from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import Customer, Expense, Product, Sale, SaleItem
from ..schemas import (
    CustomerIn, CustomerOut, ExpenseIn, ExpenseOut, SaleIn, SaleOut, SaleStatusIn,
)
from ..services import settings as cfg
from ..services.inventory import apply_stock

router = APIRouter(prefix="/api", tags=["ventas"])


def sale_out(s: Sale) -> SaleOut:
    out = SaleOut.model_validate(s)
    out.customer_name = s.customer.name if s.customer else ""
    return out


def _get_sale(db: Session, sale_id: int) -> Sale:
    s = db.get(Sale, sale_id)
    if s is None:
        raise HTTPException(404, "Venta no encontrada")
    return s


def _fill_sale(db: Session, sale: Sale, data: SaleIn) -> None:
    if data.customer_id is not None:
        if db.get(Customer, data.customer_id) is None:
            raise HTTPException(404, "Cliente no encontrado")
        sale.customer_id = data.customer_id
    elif data.customer_name.strip():
        name = data.customer_name.strip()
        customer = db.query(Customer).filter(func.lower(Customer.name) == name.lower()).first()
        if customer is None:
            customer = Customer(name=name, channel=data.channel)
            db.add(customer)
            db.flush()
        sale.customer_id = customer.id
    else:
        sale.customer_id = None

    sale.date = data.date or date.today()
    sale.channel = data.channel
    sale.status = data.status
    sale.external_id = (data.external_id or "").strip() or None
    sale.shipping_cost = data.shipping_cost
    sale.notes = data.notes
    sale.items = []
    for it in data.items:
        product = db.get(Product, it.product_id) if it.product_id else None
        if it.product_id and product is None:
            raise HTTPException(404, f"Producto {it.product_id} no encontrado")
        if product is None and not it.description.strip():
            raise HTTPException(400, "Cada artículo necesita un producto o una descripción")
        sale.items.append(SaleItem(
            product=product,
            description=it.description.strip() or (product.name if product else ""),
            quantity=it.quantity,
            unit_price=it.unit_price,
            unit_cost=it.unit_cost if it.unit_cost is not None else (product.cost if product else 0),
        ))
    if data.commission is None:
        pct = cfg.get_float(db, f"fee_{data.channel}_pct")
        sale.commission = round(sale.total * pct / 100, 2)
    else:
        sale.commission = data.commission


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Ya existe una venta con ese ID externo en ese canal") from exc


@router.get("/sales", response_model=list[SaleOut])
def list_sales(date_from: date | None = None, date_to: date | None = None, channel: str = "",
               status: str = "", q: str = "", limit: int = 500, db: Session = Depends(get_db)):
    query = db.query(Sale).options(selectinload(Sale.items), selectinload(Sale.customer))
    if date_from:
        query = query.filter(Sale.date >= date_from)
    if date_to:
        query = query.filter(Sale.date <= date_to)
    if channel:
        query = query.filter(Sale.channel == channel)
    if status:
        query = query.filter(Sale.status == status)
    if q:
        like = f"%{q}%"
        query = (query.outerjoin(Customer).filter(or_(
            Customer.name.ilike(like), Sale.notes.ilike(like), Sale.external_id.ilike(like),
            Sale.items.any(SaleItem.description.ilike(like)),
        )))
    rows = query.order_by(Sale.date.desc(), Sale.id.desc()).limit(limit).all()
    return [sale_out(s) for s in rows]


@router.get("/sales/{sale_id}", response_model=SaleOut)
def get_sale(sale_id: int, db: Session = Depends(get_db)):
    return sale_out(_get_sale(db, sale_id))


@router.post("/sales", response_model=SaleOut, status_code=201)
def create_sale(data: SaleIn, db: Session = Depends(get_db)):
    sale = Sale()
    db.add(sale)
    _fill_sale(db, sale, data)
    if sale.status != "cancelado":
        apply_stock(sale)
    _commit(db)
    db.refresh(sale)
    return sale_out(sale)


@router.put("/sales/{sale_id}", response_model=SaleOut)
def update_sale(sale_id: int, data: SaleIn, db: Session = Depends(get_db)):
    sale = _get_sale(db, sale_id)
    if sale.status != "cancelado":
        apply_stock(sale, restore=True)
    _fill_sale(db, sale, data)
    if sale.status != "cancelado":
        apply_stock(sale)
    _commit(db)
    db.refresh(sale)
    return sale_out(sale)


@router.patch("/sales/{sale_id}/status", response_model=SaleOut)
def change_status(sale_id: int, data: SaleStatusIn, db: Session = Depends(get_db)):
    sale = _get_sale(db, sale_id)
    was_cancelled, now_cancelled = sale.status == "cancelado", data.status == "cancelado"
    if now_cancelled and not was_cancelled:
        apply_stock(sale, restore=True)
    elif was_cancelled and not now_cancelled:
        apply_stock(sale)
    sale.status = data.status
    db.commit()
    return sale_out(sale)


@router.delete("/sales/{sale_id}", status_code=204)
def delete_sale(sale_id: int, db: Session = Depends(get_db)):
    sale = _get_sale(db, sale_id)
    if sale.status != "cancelado":
        apply_stock(sale, restore=True)
    db.delete(sale)
    db.commit()


# ------------------------------------------------------------------ clientes

def _customer_stats(db: Session) -> dict[int, tuple[int, float]]:
    stats: dict[int, tuple[int, float]] = {}
    sales = (db.query(Sale).options(selectinload(Sale.items))
             .filter(Sale.customer_id.isnot(None), Sale.status != "cancelado").all())
    for s in sales:
        n, total = stats.get(s.customer_id, (0, 0.0))
        stats[s.customer_id] = (n + 1, total + s.total)
    return stats


@router.get("/customers", response_model=list[CustomerOut])
def list_customers(q: str = "", db: Session = Depends(get_db)):
    query = db.query(Customer)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Customer.name.ilike(like), Customer.phone.ilike(like),
                                 Customer.email.ilike(like), Customer.city.ilike(like)))
    stats = _customer_stats(db)
    out = []
    for c in query.order_by(Customer.name).all():
        o = CustomerOut.model_validate(c)
        o.orders, o.total_spent = stats.get(c.id, (0, 0.0))
        o.total_spent = round(o.total_spent, 2)
        out.append(o)
    return out


@router.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(data: CustomerIn, db: Session = Depends(get_db)):
    c = Customer(**data.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return CustomerOut.model_validate(c)


@router.put("/customers/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: int, data: CustomerIn, db: Session = Depends(get_db)):
    c = db.get(Customer, customer_id)
    if c is None:
        raise HTTPException(404, "Cliente no encontrado")
    for k, v in data.model_dump().items():
        setattr(c, k, v)
    db.commit()
    return CustomerOut.model_validate(c)


@router.delete("/customers/{customer_id}", status_code=204)
def delete_customer(customer_id: int, db: Session = Depends(get_db)):
    c = db.get(Customer, customer_id)
    if c is None:
        raise HTTPException(404, "Cliente no encontrado")
    db.delete(c)
    db.commit()


# ------------------------------------------------------------------ gastos

@router.get("/expenses", response_model=list[ExpenseOut])
def list_expenses(date_from: date | None = None, date_to: date | None = None,
                  db: Session = Depends(get_db)):
    q = db.query(Expense)
    if date_from:
        q = q.filter(Expense.date >= date_from)
    if date_to:
        q = q.filter(Expense.date <= date_to)
    return q.order_by(Expense.date.desc(), Expense.id.desc()).all()


@router.post("/expenses", response_model=ExpenseOut, status_code=201)
def create_expense(data: ExpenseIn, db: Session = Depends(get_db)):
    values = data.model_dump()
    values["date"] = values["date"] or date.today()
    e = Expense(**values)
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


@router.put("/expenses/{expense_id}", response_model=ExpenseOut)
def update_expense(expense_id: int, data: ExpenseIn, db: Session = Depends(get_db)):
    e = db.get(Expense, expense_id)
    if e is None:
        raise HTTPException(404, "Gasto no encontrado")
    values = data.model_dump()
    values["date"] = values["date"] or e.date
    for k, v in values.items():
        setattr(e, k, v)
    db.commit()
    return e


@router.delete("/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: int, db: Session = Depends(get_db)):
    e = db.get(Expense, expense_id)
    if e is None:
        raise HTTPException(404, "Gasto no encontrado")
    db.delete(e)
    db.commit()
