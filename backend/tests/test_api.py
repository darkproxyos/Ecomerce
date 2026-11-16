from datetime import date, timedelta

from app.services import scraper
from app.services.scraper import PageInfo, SearchItem, SearchResponse


def make_product(client, **kw):
    data = {"name": "Audífonos", "sku": "A1", "cost": 100, "price": 300, "stock": 10, "min_stock": 2, **kw}
    r = client.post("/api/products", json=data)
    assert r.status_code == 201, r.text
    return r.json()


def test_product_crud_and_duplicate_sku(client):
    p = make_product(client)
    assert p["margin"] == 200 and p["margin_pct"] == 66.7
    assert client.post("/api/products", json={"name": "Otro", "sku": "A1"}).status_code == 409
    r = client.put(f"/api/products/{p['id']}", json={**p, "price": 350, "category": "Audio"})
    assert r.json()["price"] == 350
    assert client.get("/api/categories").json() == ["Audio"]
    assert len(client.get("/api/products?q=audí").json()) == 1
    dup = client.post(f"/api/products/{p['id']}/duplicate").json()
    assert dup["sku"] is None and dup["status"] == "borrador"
    assert client.delete(f"/api/products/{p['id']}").status_code == 204


def test_image_upload(client):
    p = make_product(client)
    files = [("files", ("a.png", b"\x89PNG fake", "image/png")), ("files", ("b.jpg", b"jpg", "image/jpeg"))]
    imgs = client.post(f"/api/products/{p['id']}/images", files=files).json()
    assert len(imgs) == 2 and imgs[0]["url"].startswith("/api/images/")
    r = client.get(imgs[0]["url"])
    assert r.status_code == 200 and r.content == b"\x89PNG fake" and r.headers["content-type"] == "image/png"
    assert "immutable" in r.headers["cache-control"]
    # el listado no debe incluir los bytes de las fotos
    assert "data" not in client.get("/api/products").json()[0]["images"][0]
    client.post(f"/api/images/{imgs[1]['id']}/cover")
    again = client.get(f"/api/products/{p['id']}").json()["images"]
    assert again[0]["id"] == imgs[1]["id"]
    bad = client.post(f"/api/products/{p['id']}/images", files=[("files", ("x.exe", b"MZ", "application/x"))])
    assert bad.status_code == 400


def test_sale_updates_stock_and_profit(client):
    client.put("/api/settings", json={"fee_mercadolibre_pct": "10"})
    p = make_product(client)
    r = client.post("/api/sales", json={
        "channel": "mercadolibre", "customer_name": "Ana", "shipping_cost": 20,
        "items": [{"product_id": p["id"], "quantity": 2, "unit_price": 300}],
    })
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["total"] == 600 and s["commission"] == 60 and s["profit"] == 600 - 200 - 60 - 20
    assert s["customer_name"] == "Ana"
    assert client.get(f"/api/products/{p['id']}").json()["stock"] == 8

    client.patch(f"/api/sales/{s['id']}/status", json={"status": "cancelado"})
    assert client.get(f"/api/products/{p['id']}").json()["stock"] == 10
    client.patch(f"/api/sales/{s['id']}/status", json={"status": "entregado"})
    assert client.get(f"/api/products/{p['id']}").json()["stock"] == 8

    # editar: cambia cantidad 2 -> 3
    r = client.put(f"/api/sales/{s['id']}", json={
        "channel": "mercadolibre", "status": "entregado", "customer_id": s["customer_id"], "commission": 0,
        "items": [{"product_id": p["id"], "quantity": 3, "unit_price": 300}]})
    assert r.json()["total"] == 900
    assert client.get(f"/api/products/{p['id']}").json()["stock"] == 7

    client.delete(f"/api/sales/{s['id']}")
    assert client.get(f"/api/products/{p['id']}").json()["stock"] == 10
    customers = client.get("/api/customers").json()
    assert customers[0]["name"] == "Ana"


def test_dashboard(client):
    p = make_product(client, stock=3, min_stock=2)
    client.post("/api/sales", json={"channel": "marketplace", "items": [{"product_id": p["id"], "quantity": 1, "unit_price": 300}]})
    client.post("/api/sales", json={"channel": "directo", "date": (date.today() - timedelta(days=40)).isoformat(),
                                    "items": [{"description": "Servicio", "quantity": 1, "unit_price": 100}]})
    client.post("/api/expenses", json={"amount": 50, "category": "publicidad"})
    d = client.get("/api/dashboard?days=30").json()
    assert d["kpis"]["revenue"] == 300 and d["kpis"]["orders"] == 1
    assert d["kpis"]["net_profit"] == 300 - 100 - 50
    assert d["previous"]["revenue"] == 100
    assert d["low_stock"][0]["stock"] == 2
    assert d["by_channel"][0]["channel"] == "marketplace"
    assert len(d["series"]) == 30 and d["series"][-1]["marketplace"] == 300
    assert d["top_products"][0]["name"] == "Audífonos"


def test_watch_flow(client, monkeypatch):
    prices = iter([500.0, 450.0])
    monkeypatch.setattr(scraper, "fetch_page_info",
                        lambda url, sel="", tok="": PageInfo(next(prices), "Competidor", "https://i/x.jpg"))
    p = make_product(client)
    w = client.post("/api/watches", json={"url": "https://tienda.com/p/1", "product_id": p["id"]}).json()
    assert w["last_price"] == 500 and w["name"] == "Competidor" and w["product_price"] == 300
    w = client.post(f"/api/watches/{w['id']}/check").json()
    assert w["last_price"] == 450 and w["prev_price"] == 500
    assert [h["price"] for h in client.get(f"/api/watches/{w['id']}/history").json()] == [500, 450]
    alerts = client.get("/api/dashboard").json()["alerts"]
    assert alerts and alerts[0]["type"] == "changed"


def test_watch_error_is_stored(client, monkeypatch):
    def boom(*a, **k):
        raise scraper.ScrapeError("bloqueado")
    monkeypatch.setattr(scraper, "fetch_page_info", boom)
    w = client.post("/api/watches", json={"url": "https://tienda.com/p/1"}).json()
    assert w["last_error"] == "bloqueado" and w["last_price"] is None


def test_market_search_detects_new(client, monkeypatch):
    runs = iter([
        [SearchItem("MLM1", "A", 100, "u1"), SearchItem("MLM2", "B", 200, "u2")],
        [SearchItem("MLM1", "A", 90, "u1"), SearchItem("MLM3", "C", 150, "u3")],
    ])
    monkeypatch.setattr(scraper, "search_mercadolibre", lambda q, site, tok="": SearchResponse(next(runs), "api"))
    s = client.post("/api/searches", json={"query": "audifonos"}).json()
    assert s["result_count"] == 2 and s["new_count"] == 0 and s["avg_price"] == 150

    # Simula que la búsqueda se creó hace un día, para que la 2a corrida cuente como "nuevos".
    from app.database import SessionLocal
    from app.models import MarketResult, MarketSearch
    from datetime import datetime
    db = SessionLocal()
    ms = db.get(MarketSearch, s["id"])
    ms.created_at -= timedelta(days=1)
    for r in db.query(MarketResult):
        r.first_seen -= timedelta(days=1)
        r.last_seen -= timedelta(days=1)
    ms.last_run = datetime.now() - timedelta(days=1)
    db.commit()
    db.close()

    s = client.post(f"/api/searches/{s['id']}/run").json()
    assert s["result_count"] == 2 and s["new_count"] == 1
    res = client.get(f"/api/searches/{s['id']}/results").json()
    by_id = {r["external_id"]: r for r in res}
    assert by_id["MLM3"]["is_new"] and not by_id["MLM1"]["is_new"]
    assert by_id["MLM1"]["price"] == 90 and by_id["MLM1"]["prev_price"] == 100
    news = client.get("/api/market/new-products").json()
    assert [n["external_id"] for n in news] == ["MLM3"]


def test_exports_and_settings(client):
    p = make_product(client)
    client.post(f"/api/products/{p['id']}/images", files=[("files", ("a.png", b"x", "image/png"))])
    r = client.get("/api/export/meta-catalog.csv")
    assert r.status_code == 200 and "A1" in r.text and "/api/images/" in r.text and "in stock" in r.text
    assert "Audífonos" in client.get("/api/export/products.csv").text
    client.put("/api/settings", json={"ml_client_secret": "secreto", "business_name": "Tienda"})
    s = client.get("/api/settings").json()
    assert s["ml_client_secret"] != "secreto" and s["business_name"] == "Tienda"
    # enviar la máscara no sobreescribe el secreto
    client.put("/api/settings", json={"ml_client_secret": s["ml_client_secret"]})
    from app.database import SessionLocal
    from app.services import settings as cfg
    db = SessionLocal()
    assert cfg.get(db, "ml_client_secret") == "secreto"
    db.close()


def test_ml_order_import(client):
    from app.database import SessionLocal
    from app.services.mercadolibre import import_order
    p = make_product(client, sku="SKU-9")
    order = {"id": 2000001, "status": "paid", "date_created": "2026-11-01T10:00:00.000-04:00",
             "buyer": {"nickname": "COMPRADOR1"},
             "order_items": [{"item": {"id": "MLM1", "title": "Audífonos", "seller_sku": "SKU-9"},
                              "quantity": 2, "unit_price": 350, "sale_fee": 40}]}
    db = SessionLocal()
    assert import_order(db, order) == "nueva"
    db.commit()
    assert import_order(db, {**order, "status": "cancelled"}) == "actualizada"
    db.commit()
    db.close()
    sales = client.get("/api/sales?channel=mercadolibre").json()
    assert len(sales) == 1 and sales[0]["commission"] == 80 and sales[0]["status"] == "cancelado"
    assert client.get(f"/api/products/{p['id']}").json()["stock"] == 10


def test_login_required(monkeypatch, client):
    import app.main as main
    monkeypatch.setattr(main, "ADMIN_PASSWORD", "clave")
    monkeypatch.setattr(main, "AUTH_REQUIRED", True)
    assert client.get("/api/products").status_code == 401
    assert client.get("/api/status").json()["logged_in"] is False
    assert client.post("/api/login", json={"password": "mala"}).status_code == 401
    assert client.post("/api/login", json={"password": "clave"}).status_code == 200
    assert client.get("/api/products").status_code == 200
    assert client.get("/api/status").json()["logged_in"] is True
    client.post("/api/logout")
    assert client.get("/api/products").status_code == 401
    # token alterado
    client.cookies.set(main.COOKIE, "9999999999.firmafalsa")
    assert client.get("/api/products").status_code == 401
    assert client.get("/api/health").status_code == 200


def test_vercel_without_password_blocks_data(monkeypatch, client):
    import app.main as main
    monkeypatch.setattr(main, "ADMIN_PASSWORD", "")
    monkeypatch.setattr(main, "AUTH_REQUIRED", True)
    r = client.get("/api/products")
    assert r.status_code == 503 and r.json()["setup"] is True
    st = client.get("/api/status").json()
    assert st["password_configured"] is False and st["database_ok"] is True


def test_images_public_when_logged_out(monkeypatch, client):
    p = make_product(client)
    img = client.post(f"/api/products/{p['id']}/images",
                      files=[("files", ("a.png", b"x", "image/png"))]).json()[0]
    import app.main as main
    monkeypatch.setattr(main, "ADMIN_PASSWORD", "clave")
    monkeypatch.setattr(main, "AUTH_REQUIRED", True)
    assert client.get(img["url"]).status_code == 200
    assert client.delete(f"/api/images/{img['id']}").status_code == 401


def test_cron(monkeypatch, client):
    import app.main as main
    monkeypatch.setattr(main, "CRON_SECRET", "s3cret")
    calls = []
    monkeypatch.setattr(main.market_service, "run_due", lambda db: calls.append(1) or {"watches": 0})
    assert client.get("/api/cron").status_code == 401
    assert client.get("/api/cron", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert calls == [1]


def test_run_due_respects_time_budget(client, monkeypatch):
    from app.database import SessionLocal
    from app.services import market
    for i in range(3):
        client.post("/api/watches?check_now=false", json={"url": f"https://t.com/{i}"})
    seen = []
    monkeypatch.setattr(market, "run_watch", lambda db, w: seen.append(w.id))
    db = SessionLocal()
    assert market.run_due(db, budget_seconds=-1) == {"watches": 0, "searches": 0, "pending": 3}
    assert market.run_due(db, budget_seconds=60)["watches"] == 3
    db.close()


def test_frontend_and_game_served_locally(client):
    assert "app.js" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    r = client.get("/juegos/digiz/")
    assert r.status_code == 200 and "phaser.js" in r.text and "cordova" not in r.text


def test_database_url_normalization(monkeypatch):
    from app import config
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db?sslmode=require")
    assert config._database_url() == ("postgresql+psycopg://u:p@h/db?sslmode=require", True)
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.setenv("POSTGRES_URL", "postgresql://u:p@h/db")
    assert config._database_url()[0] == "postgresql+psycopg://u:p@h/db"
    monkeypatch.delenv("POSTGRES_URL")
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setattr(config, "ON_VERCEL", True)
    assert config._database_url() == ("sqlite:////tmp/negocio.db", False)


def test_vercel_rewritten_path(client):
    make_product(client)
    r = client.get("/api/index?path=products&q=Aud")
    assert r.status_code == 200 and len(r.json()) == 1
    assert client.get("/api/index?path=products&q=zzz").json() == []
