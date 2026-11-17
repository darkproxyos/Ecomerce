"""Mi ruta: fases del negocio, tareas y detección de la fase actual con datos reales."""
from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy.orm import Session, selectinload

from .. import clock
from ..models import Expense, Product, Sale
from . import settings as cfg

# app: (texto, ruta del panel)
PHASES = [
    {
        "id": "f0", "tag": "Fase 0", "title": "Prepara el terreno", "time": "1 semana",
        "goal": "20 artículos listos para publicar",
        "tasks": [
            "Completa tu perfil de Facebook con foto real y activa Marketplace.",
            "Abre una cuenta o tarjeta digital solo para el negocio.",
            "En Configuración pon tu moneda y la comisión de cada canal.",
            "Recorre tu casa y anota 20 cosas que ya no usas y se pueden vender.",
            "Arma un rincón para fotos: luz natural, fondo liso y un trapo para limpiar.",
            "Instala WhatsApp Business y escribe 3 respuestas rápidas.",
        ],
        "app": [("Configura moneda y comisiones", "configuracion"),
                ("Da de alta tus artículos con costo $0 si ya eran tuyos", "productos")],
        "tools": ["Facebook Marketplace", "WhatsApp Business", "Cuenta bancaria del negocio"],
        "next": "Tienes 20 artículos dados de alta en el panel.",
    },
    {
        "id": "f1", "tag": "Fase 1", "title": "Vende lo que ya tienes", "time": "Semanas 1 a 4",
        "goal": "$3,000 a $10,000 de capital semilla",
        "tasks": [
            "Publica de 3 a 5 artículos por día hasta tener todo publicado.",
            "Pon precio buscando el mismo artículo en Marketplace y Mercado Libre; súbele 10% para negociar.",
            "Toma de 4 a 6 fotos por artículo: frente, detalles, defectos y medidas.",
            "Responde todos los mensajes en menos de 15 minutos.",
            "Registra cada venta con el botón Vendido el mismo día.",
            "Baja el precio o renueva lo que lleve más de 14 días sin venderse.",
            "Guarda todo lo que ganes en la cuenta del negocio: es tu capital semilla.",
        ],
        "app": [("Copia el anuncio desde 'Texto para publicar'", "productos"),
                ("Registra cada venta con el botón Vendido", "productos"),
                ("Revisa los artículos para bajar precio", "productos")],
        "tools": ["Google Lens", "Snapseed o Photoroom", "Mercado Pago"],
        "next": "Tienes $3,000 de capital y vendes 3 o más artículos por semana.",
    },
    {
        "id": "f2", "tag": "Fase 2", "title": "Compra barato y revende", "time": "Meses 2 y 3",
        "goal": "$5,000 a $8,000 de utilidad al mes",
        "tasks": [
            "Busca gangas en Marketplace (mudanzas, \"urge\", \"remato\"), bazares, tianguis y ventas de garaje.",
            "Anota cada posible compra en Oportunidades y paga máximo lo que te indica.",
            "Empieza con artículos que conoces y que puedes probar en el momento.",
            "Limpia, repara y fotografía bien: eso sube el precio de venta.",
            "Anota en Gastos la gasolina, limpieza y refacciones.",
            "Reinvierte 70% de la ganancia, guarda 20% de colchón y toma 10%.",
            "Al final de cada mes revisa qué categoría dejó más ganancia.",
        ],
        "app": [("Evalúa compras en Oportunidades", "compras"),
                ("Registra gastos", "gastos"),
                ("Vigila precios de anuncios parecidos", "competencia")],
        "tools": ["Marketplace (para comprar)", "Canva", "Calculadora de Oportunidades"],
        "next": "Ganas $5,000 o más al mes durante dos meses seguidos.",
    },
    {
        "id": "f3", "tag": "Fase 3", "title": "Elige un nicho y producto nuevo", "time": "Meses 3 a 6",
        "goal": "30 ventas al mes con 25% de margen",
        "tasks": [
            "Elige un nicho: una categoría que conoces y que se vende rápido.",
            "Crea búsquedas de ese nicho y anota precio promedio, vendedores y novedades.",
            "Consigue 2 o 3 proveedores mayoristas y compara precio, mínimo de compra y garantía.",
            "Prueba con lotes chicos: de 5 a 10 piezas de 2 o 3 productos distintos.",
            "Quédate con el producto que se venda en menos de 15 días.",
            "Pon stock mínimo a cada producto para que el panel te avise.",
            "Empieza a enviar a otras ciudades con guías de paquetería.",
        ],
        "app": [("Estudia el mercado en Búsquedas", "mercado"),
                ("Configura stock mínimo en Productos", "productos"),
                ("Revisa quién te recompra en Clientes", "clientes")],
        "tools": ["Envia.com o Skydropx", "Proveedores mayoristas", "WhatsApp Business (catálogo)"],
        "next": "30 o más ventas al mes con 25% o más de margen.",
    },
    {
        "id": "f4", "tag": "Fase 4", "title": "Da el salto a Mercado Libre", "time": "Meses 6 a 12",
        "goal": "50 a 100 ventas al mes en Mercado Libre",
        "tasks": [
            "Date de alta en el SAT (RFC) con ayuda de un contador.",
            "Crea tu cuenta de vendedor y configura Mercado Envíos.",
            "Calcula tu precio contando la comisión y el envío.",
            "Publica primero tus productos ganadores con títulos de hasta 60 caracteres.",
            "Contesta preguntas rápido y envía a tiempo para cuidar tu reputación.",
            "Conecta tu cuenta en el panel e importa pedidos cada semana.",
            "Cuando vendas seguido, evalúa Mercado Libre Full.",
        ],
        "app": [("Conecta Mercado Libre", "configuracion"),
                ("Sincroniza precio y stock desde cada producto", "productos")],
        "tools": ["App de vendedor de Mercado Libre", "SAT y contador"],
        "next": "50 o más ventas al mes en Mercado Libre.",
    },
    {
        "id": "f5", "tag": "Fase 5", "title": "Tu propia tienda y tu marca", "time": "Año 2",
        "goal": "20% a 30% de ventas fuera de marketplaces",
        "tasks": [
            "Ponle nombre a tu negocio, crea un logotipo y usa empaque con tu marca.",
            "Abre tu tienda en línea en Tiendanube o Shopify.",
            "Publica contenido en Instagram y TikTok mostrando tus productos en uso.",
            "Escribe a tus mejores clientes cuando lleguen productos nuevos.",
            "Prueba anuncios pequeños solo con productos que ya se venden.",
            "Busca proveedores directos o importación para mejorar tu margen.",
            "Cuando no te alcance el tiempo, contrata ayuda para empacar y enviar.",
        ],
        "app": [("Tus compradores frecuentes en Clientes", "clientes"),
                ("Exporta el catálogo para Meta", "configuracion")],
        "tools": ["Tiendanube o Shopify", "Meta Business Suite", "Canva y CapCut"],
        "next": "Al menos 20% de tus ventas son directas (tienda, WhatsApp, redes).",
    },
]

TASK_IDS = {f"{p['id']}-{i}" for p in PHASES for i in range(len(p["tasks"]))}


def get_done(db: Session) -> dict[str, bool]:
    try:
        data = json.loads(cfg.get(db, "roadmap_done") or "{}")
        return {k: True for k, v in data.items() if v and k in TASK_IDS}
    except (ValueError, AttributeError):
        return {}


def set_task(db: Session, task_id: str, done: bool) -> None:
    current = get_done(db)
    if done:
        current[task_id] = True
    else:
        current.pop(task_id, None)
    cfg.set_many(db, {"roadmap_done": json.dumps(current)})


def metrics(db: Session) -> dict:
    today = clock.today()
    sales = (db.query(Sale).options(selectinload(Sale.items))
             .filter(Sale.status != "cancelado").all())
    expenses = db.query(Expense).all()

    def window(start_days: int, end_days: int = 0):
        start = today - timedelta(days=start_days - 1)
        end = today - timedelta(days=end_days)
        return [s for s in sales if start <= s.date <= end]

    def exp_window(start_days: int, end_days: int = 0) -> float:
        start = today - timedelta(days=start_days - 1)
        end = today - timedelta(days=end_days)
        return sum(e.amount for e in expenses if start <= e.date <= end)

    last30, prev30 = window(30), window(60, 30)
    last60, last90, last28 = window(60), window(90), window(28)
    rev60 = sum(s.total for s in last60)
    rev90 = sum(s.total for s in last90)
    direct90 = sum(s.total for s in last90 if s.channel == "directo")
    net_all = sum(s.profit for s in sales) - sum(e.amount for e in expenses)
    return {
        "capital": round(cfg.get_float(db, "initial_capital") + net_all, 2),
        "products": db.query(Product).count(),
        "sales_per_week": round(len(last28) / 4, 1),
        "profit_30": round(sum(s.profit for s in last30) - exp_window(30), 2),
        "profit_prev_30": round(sum(s.profit for s in prev30) - exp_window(60, 30), 2),
        "orders_30": len(last30),
        "margin_60": round(sum(s.profit for s in last60) / rev60 * 100, 1) if rev60 else 0.0,
        "ml_orders_30": sum(1 for s in last30 if s.channel == "mercadolibre"),
        "direct_share_90": round(direct90 / rev90 * 100, 1) if rev90 else 0.0,
    }


def _criteria(m: dict) -> list[list[dict]]:
    def c(label, key, target, unit):
        return {"label": label, "key": key, "value": m[key], "target": target, "unit": unit,
                "met": m[key] >= target}
    return [
        [c("Productos dados de alta", "products", 20, "count")],
        [c("Capital del negocio", "capital", 3000, "money"),
         c("Ventas por semana (últimas 4)", "sales_per_week", 3, "count")],
        [c("Utilidad últimos 30 días", "profit_30", 5000, "money"),
         c("Utilidad de los 30 días anteriores", "profit_prev_30", 5000, "money")],
        [c("Ventas últimos 30 días", "orders_30", 30, "count"),
         c("Margen neto (60 días)", "margin_60", 25, "pct")],
        [c("Ventas en Mercado Libre (30 días)", "ml_orders_30", 50, "count")],
        [c("Ventas directas (90 días)", "direct_share_90", 20, "pct")],
    ]


def roadmap(db: Session) -> dict:
    done = get_done(db)
    m = metrics(db)
    crit = _criteria(m)
    phases, current = [], None
    met_by_phase = [all(c["met"] for c in cs) for cs in crit]
    # Si tus números ya cumplen una fase más avanzada, las anteriores cuentan como superadas.
    last_met = max((i for i, ok in enumerate(met_by_phase) if ok), default=-1)
    for i, p in enumerate(PHASES):
        tasks = [{"id": f"{p['id']}-{j}", "text": t, "done": bool(done.get(f"{p['id']}-{j}"))}
                 for j, t in enumerate(p["tasks"])]
        all_tasks = all(t["done"] for t in tasks)
        met = met_by_phase[i] or i < last_met
        passed = met or all_tasks
        progress = round(sum(min(c["value"] / c["target"], 1) if c["target"] else 1 for c in crit[i])
                         / len(crit[i]) * 100)
        if not passed and current is None:
            current = i
        phases.append({
            **{k: p[k] for k in ("id", "tag", "title", "time", "goal", "tools", "next")},
            "app": [{"text": t, "route": r} for t, r in p["app"]],
            "tasks": tasks, "criteria": crit[i], "passed": passed,
            "passed_by_tasks": all_tasks and not met, "progress_pct": progress,
        })
    if current is None:
        current = len(PHASES) - 1
    return {
        "current": current,
        "phases": phases,
        "metrics": m,
        "tasks_done": sum(1 for p in phases for t in p["tasks"] if t["done"]),
        "tasks_total": sum(len(p["tasks"]) for p in phases),
    }
