"""Carga datos de ejemplo para probar el dashboard:  python -m app.seed"""
import random
from datetime import date, timedelta

from .database import Base, SessionLocal, engine
from .models import Customer, Expense, Listing, Product, Sale, SaleItem
from .services.inventory import apply_stock

PRODUCTS = [
    ("AUD-001", "Audífonos Bluetooth Pro", "Audio", "SoundMax", 180, 449, 25),
    ("BOC-002", "Bocina portátil resistente al agua", "Audio", "SoundMax", 220, 599, 12),
    ("CAR-003", "Cargador rápido USB-C 30W", "Accesorios", "VoltX", 60, 199, 40),
    ("CAB-004", "Cable USB-C a Lightning 1m", "Accesorios", "VoltX", 25, 99, 3),
    ("SMW-005", "Smartwatch deportivo", "Wearables", "FitOne", 350, 899, 8),
    ("LAM-006", "Lámpara LED de escritorio", "Hogar", "Lumi", 140, 379, 15),
    ("SOP-007", "Soporte para celular de auto", "Accesorios", "VoltX", 35, 149, 2),
    ("TEC-008", "Teclado mecánico RGB", "Computación", "KeyPro", 420, 1099, 6),
]
NAMES = ["Ana López", "Carlos Ruiz", "María Pérez", "Jorge Díaz", "Lucía Torres", "Pedro Gómez",
         "Sofía Herrera", "Diego Castro", "Valeria Ríos", "Andrés Mora"]


def run() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    if db.query(Product).count():
        print("La base ya tiene productos; no se cargó nada.")
        return
    random.seed(7)
    products = []
    for sku, name, cat, brand, cost, price, stock in PRODUCTS:
        p = Product(sku=sku, name=name, category=cat, brand=brand, cost=cost, price=price,
                    stock=stock + 30, min_stock=3,
                    description=f"{name}. Nuevo, con garantía. Envío a todo el país.")
        db.add(p)
        products.append(p)
    db.flush()
    for p in products[:5]:
        db.add(Listing(product_id=p.id, channel="mercadolibre", title=p.name, price=round(p.price * 1.12),
                       external_id=f"MLM{random.randint(10**9, 10**10)}"))
        db.add(Listing(product_id=p.id, channel="marketplace", title=p.name, price=p.price))
    customers = [Customer(name=n, phone=f"55{random.randint(10**7, 10**8)}",
                          city=random.choice(["CDMX", "Guadalajara", "Monterrey", "Puebla"]))
                 for n in NAMES]
    db.add_all(customers)
    db.flush()
    today = date.today()
    for d in range(90):
        day = today - timedelta(days=d)
        for _ in range(random.choice([0, 1, 1, 2, 3])):
            channel = random.choices(["mercadolibre", "marketplace", "directo"], [5, 4, 1])[0]
            p = random.choice(products)
            qty = random.choice([1, 1, 1, 2])
            price = round(p.price * (1.12 if channel == "mercadolibre" else 1))
            sale = Sale(date=day, channel=channel, customer_id=random.choice(customers).id,
                        status=random.choices(["entregado", "enviado", "pagado", "cancelado"], [8, 2, 1, 1])[0]
                        if d > 3 else random.choice(["pagado", "pendiente", "enviado"]),
                        shipping_cost=random.choice([0, 0, 89]) if channel == "mercadolibre" else 0)
            sale.items.append(SaleItem(product=p, description=p.name, quantity=qty,
                                       unit_price=price, unit_cost=p.cost))
            sale.commission = round(sale.total * 0.13, 2) if channel == "mercadolibre" else 0
            db.add(sale)
            if sale.status != "cancelado":
                apply_stock(sale)
    for m in range(3):
        base = today.replace(day=1) - timedelta(days=30 * m)
        db.add(Expense(date=base, category="publicidad", description="Anuncios Facebook", amount=800))
        db.add(Expense(date=base + timedelta(days=5), category="empaque", description="Cajas y bolsas",
                       amount=350))
    db.commit()
    print(f"Listo: {len(products)} productos, {db.query(Sale).count()} ventas de ejemplo.")


if __name__ == "__main__":
    run()
