from datetime import timedelta

from app import clock
from app.database import SessionLocal
from app.models import Product


def mk(client, **kw):
    data = {"name": "Consola usada", "cost": 600, "price": 1500, "stock": 1, "min_stock": 0, **kw}
    r = client.post("/api/products", json=data)
    assert r.status_code == 201, r.text
    return r.json()


def age(product_id, days):
    db = SessionLocal()
    p = db.get(Product, product_id)
    p.listed_at = clock.now() - timedelta(days=days)
    db.commit()
    db.close()


# ------------------------------------------------------------------ rotación y venta rápida

def test_rotation_flags(client):
    a, b, c = mk(client, name="A"), mk(client, name="B"), mk(client, name="C")
    assert a["days_listed"] == 0 and a["aging"] == "" and a["listed_at"]
    age(b["id"], 15)
    age(c["id"], 31)
    by = {p["name"]: p for p in client.get("/api/products").json()}
    assert by["B"]["aging"] == "bajar" and by["B"]["suggested_price"] == 1350
    assert by["C"]["aging"] == "liquidar" and by["C"]["suggested_price"] == 1200
    assert [p["name"] for p in client.get("/api/products?aging=any").json()] == ["C", "B"] or \
        {p["name"] for p in client.get("/api/products?aging=any").json()} == {"B", "C"}
    assert [p["name"] for p in client.get("/api/products?aging=liquidar").json()] == ["C"]
    d = client.get("/api/dashboard").json()["aging"]
    assert d["bajar"] == 1 and d["liquidar"] == 1 and d["stuck_value"] == 1200
    # renovar reinicia los días
    r = client.post(f"/api/products/{c['id']}/relist").json()
    assert r["days_listed"] == 0 and r["aging"] == ""


def test_suggested_price_never_below_cost(client):
    p = mk(client, cost=1400, price=1500)
    age(p["id"], 40)
    assert client.get(f"/api/products/{p['id']}").json()["suggested_price"] == 1400


def test_status_change_restarts_listing(client):
    p = mk(client, status="borrador")
    assert p["listed_at"] is None and p["days_listed"] is None
    r = client.put(f"/api/products/{p['id']}", json={**p, "status": "activo"}).json()
    assert r["listed_at"] and r["days_listed"] == 0


def test_quick_sale(client):
    client.put("/api/settings", json={"fee_marketplace_pct": "0"})
    p = mk(client)
    s = client.post(f"/api/products/{p['id']}/quick-sale", json={"price": 1400, "customer_name": "Luis"})
    assert s.status_code == 201, s.text
    s = s.json()
    assert s["total"] == 1400 and s["profit"] == 800 and s["channel"] == "marketplace"
    assert s["status"] == "entregado" and s["customer_name"] == "Luis"
    after = client.get(f"/api/products/{p['id']}").json()
    assert after["stock"] == 0 and after["status"] == "agotado"
    again = client.post(f"/api/products/{p['id']}/quick-sale", json={"price": 1400})
    assert again.status_code == 409


# ------------------------------------------------------------------ oportunidades

def test_opportunity_calc_and_buy(client):
    client.put("/api/settings", json={"target_margin_pct": "30", "fee_mercadolibre_pct": "15"})
    o = client.post("/api/opportunities", json={
        "title": "Taladro DeWalt", "url": "https://fb.com/x", "asking_price": 600,
        "resale_price": 1500, "other_costs": 80}).json()
    c = o["calc"]
    assert c["buy_price"] == 600 and c["profit"] == 820 and c["margin_pct"] == 54.7
    assert c["max_pay"] == 970 and c["verdict"] == "comprar"

    # oferta y canal con comisión
    o2 = client.put(f"/api/opportunities/{o['id']}", json={
        **{k: o[k] for k in ("title", "url", "asking_price", "resale_price", "other_costs")},
        "offer_price": 900, "channel": "mercadolibre", "status": "negociando"}).json()
    c2 = o2["calc"]
    assert c2["fee"] == 225 and c2["profit"] == 1500 - 900 - 225 - 80 and c2["verdict"] == "rapido"

    bad = client.post("/api/opportunities/calc", json={"title": "x", "asking_price": 900, "resale_price": 1000})
    assert bad.json()["verdict"] == "no"

    r = client.post(f"/api/opportunities/{o['id']}/buy", json={"paid_price": 550})
    assert r.status_code == 200, r.text
    pid = r.json()["product_id"]
    prod = client.get(f"/api/products/{pid}").json()
    assert prod["cost"] == 630 and prod["price"] == 1500 and prod["stock"] == 1
    assert prod["condition"] == "usado" and prod["status"] == "activo" and "fb.com/x" in prod["notes"]
    assert r.json()["opportunity"]["status"] == "comprado"
    assert client.post(f"/api/opportunities/{o['id']}/buy", json={"paid_price": 1}).status_code == 409
    assert len(client.get("/api/opportunities?status=comprado").json()) == 1


# ------------------------------------------------------------------ mi ruta

def test_roadmap_detects_phase(client):
    r = client.get("/api/roadmap").json()
    assert r["current"] == 0 and r["tasks_total"] == 41 and r["tasks_done"] == 0
    # marcar todas las tareas de la fase 0 la da por cumplida
    for t in r["phases"][0]["tasks"]:
        assert client.put(f"/api/roadmap/tasks/{t['id']}", json={"done": True}).status_code == 200
    r = client.get("/api/roadmap").json()
    assert r["current"] == 1 and r["phases"][0]["passed_by_tasks"]
    assert client.put("/api/roadmap/tasks/zz-9", json={"done": True}).status_code == 404

    # fase 1 se cumple con capital >= 3000 y 3 ventas por semana
    client.put("/api/settings", json={"initial_capital": "500"})
    p = mk(client, cost=0, price=300, stock=20)
    for _ in range(12):
        client.post(f"/api/products/{p['id']}/quick-sale", json={"price": 300})
    r = client.get("/api/roadmap").json()
    m = r["metrics"]
    assert m["capital"] == 500 + 3600 and m["sales_per_week"] == 3.0
    assert r["phases"][1]["passed"] and r["current"] == 2
    crit = {c["key"]: c for c in r["phases"][2]["criteria"]}
    assert crit["profit_30"]["value"] == 3600 and not crit["profit_30"]["met"]
    assert client.get("/api/dashboard").json()["roadmap"]["tag"] == "Fase 2"


# ------------------------------------------------------------------ respaldo

def test_backup_and_restore_roundtrip(client):
    client.put("/api/settings", json={"business_name": "Tienda X", "ml_client_secret": "nosale"})
    p = mk(client)
    client.post(f"/api/products/{p['id']}/images", files=[("files", ("a.png", b"PNGDATA", "image/png"))])
    client.post(f"/api/products/{p['id']}/quick-sale", json={"price": 1400, "customer_name": "Ana"})
    client.post("/api/opportunities", json={"title": "Bici", "asking_price": 500, "resale_price": 1200})
    client.put("/api/roadmap/tasks/f0-0", json={"done": True})

    b = client.get("/api/backup").json()
    assert b["format"] == "panel-ventas-respaldo"
    t = b["tables"]
    assert len(t["products"]) == 1 and len(t["sales"]) == 1 and len(t["opportunities"]) == 1
    assert "data" not in t["product_images"][0] and t["product_images"][0]["product_id"] == p["id"]
    assert not any(s["key"] == "ml_client_secret" for s in t["settings"])

    # se borra todo y se restaura
    mk(client, name="Basura")
    r = client.post("/api/restore", json=b)
    assert r.status_code == 200, r.text
    assert r.json()["products"] == 1 and r.json()["fotos_pendientes"] == 1
    prods = client.get("/api/products").json()
    assert [x["name"] for x in prods] == ["Consola usada"] and prods[0]["images"] == []
    img = t["product_images"][0]
    up = client.post("/api/restore/image", data={"product_id": img["product_id"], "position": 0},
                     files={"file": ("a.png", b"PNGDATA", "image/png")})
    assert up.status_code == 200
    again = client.get(f"/api/products/{p['id']}").json()
    assert client.get(again["images"][0]["url"]).content == b"PNGDATA"
    assert client.get("/api/settings").json()["business_name"] == "Tienda X"
    assert client.get("/api/sales").json()[0]["customer_name"] == "Ana"
    assert client.get("/api/roadmap").json()["tasks_done"] == 1
    # los ids siguen funcionando para registros nuevos (secuencias)
    assert mk(client, name="Nuevo")["id"] > p["id"]
    assert client.post("/api/restore", json={"format": "otro"}).status_code == 400


def test_migration_adds_missing_column(client):
    from sqlalchemy import inspect, text

    from app.database import add_missing_columns, engine
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE products DROP COLUMN listed_at"))
    assert "listed_at" not in {c["name"] for c in inspect(engine).get_columns("products")}
    add_missing_columns()
    assert "listed_at" in {c["name"] for c in inspect(engine).get_columns("products")}


def test_roadmap_skips_phases_already_surpassed(client):
    # muchas ventas con buen margen pero pocos productos: no debe quedarse en la fase 0
    p = mk(client, cost=100, price=600, stock=100)
    for _ in range(32):
        client.post(f"/api/products/{p['id']}/quick-sale", json={"price": 600})
    r = client.get("/api/roadmap").json()
    assert r["metrics"]["products"] == 1
    assert r["phases"][0]["passed"] and r["phases"][3]["passed"] and r["current"] == 4
