"""Scraping de precios de la competencia y búsquedas en Mercado Libre.

Estrategia para extraer el precio de una página de producto (en orden):
1. Selector CSS que el usuario configuró (si hay).
2. Datos estructurados JSON-LD (schema.org Product / Offer) — lo usan la
   mayoría de tiendas (Shopify, WooCommerce, VTEX, Mercado Libre, Amazon...).
3. Meta tags (product:price:amount, og:price:amount, itemprop=price).
4. Heurística: primer elemento cuyo class/id contiene "price"/"precio".
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.7",
}
TIMEOUT = httpx.Timeout(25.0, connect=10.0)

ML_DOMAINS = {
    "MLM": "mercadolibre.com.mx",
    "MLA": "mercadolibre.com.ar",
    "MCO": "mercadolibre.com.co",
    "MLC": "mercadolibre.cl",
    "MLU": "mercadolibre.com.uy",
    "MPE": "mercadolibre.com.pe",
    "MEC": "mercadolibre.com.ec",
    "MLV": "mercadolibre.com.ve",
    "MLB": "mercadolivre.com.br",
}

_NUM_RE = re.compile(r"\d(?:[\d.,]|\s(?=\d{3}\b))*")
_ML_ID_RE = re.compile(r"\b(M[LCPE][A-Z])-?(\d{6,})")
_WID_RE = re.compile(r"[?&#]wid=(M[LCPE][A-Z]\d+)")


class ScrapeError(Exception):
    pass


@dataclass
class PageInfo:
    price: float | None = None
    title: str = ""
    image: str = ""
    currency: str = ""
    method: str = ""


@dataclass
class SearchItem:
    external_id: str
    title: str
    price: float | None
    url: str
    thumbnail: str = ""
    seller: str = ""
    sold_quantity: int | None = None
    free_shipping: bool = False


@dataclass
class SearchResponse:
    items: list[SearchItem] = field(default_factory=list)
    source: str = ""


# ------------------------------------------------------------------ precios

def parse_price(text: str | float | int | None) -> float | None:
    """Convierte textos como '$1,299.00', '1.299,90', 'MX$ 12 500' a float."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    text = str(text).replace("\xa0", " ").strip()
    if not text:
        return None
    # Si hay símbolo de moneda, prioriza el número que lo sigue.
    m = re.search(r"[$€£]\s*(\d[\d.,\s]*)", text)
    raw = m.group(1) if m else None
    if raw is None:
        m2 = _NUM_RE.search(text)
        if not m2:
            return None
        raw = m2.group(0)
    raw = re.sub(r"\s+", "", raw).strip(".,")
    if not raw:
        return None

    has_dot, has_comma = "." in raw, "," in raw
    if has_dot and has_comma:
        dec = "." if raw.rfind(".") > raw.rfind(",") else ","
        thou = "," if dec == "." else "."
        raw = raw.replace(thou, "").replace(dec, ".")
    elif has_dot or has_comma:
        sep = "." if has_dot else ","
        parts = raw.split(sep)
        if len(parts) > 2 or len(parts[-1]) == 3:
            raw = raw.replace(sep, "")  # separador de miles
        else:
            raw = raw.replace(sep, ".")  # separador decimal
    try:
        return float(raw)
    except ValueError:
        return None


def _iter_jsonld(obj):
    if isinstance(obj, list):
        for x in obj:
            yield from _iter_jsonld(x)
    elif isinstance(obj, dict):
        yield obj
        for key in ("@graph", "mainEntity", "itemListElement", "item"):
            if key in obj:
                yield from _iter_jsonld(obj[key])


def _offer_price(offers) -> tuple[float | None, str]:
    if isinstance(offers, list):
        prices = [p for p in (_offer_price(o) for o in offers) if p[0] is not None]
        return min(prices, key=lambda p: p[0]) if prices else (None, "")
    if not isinstance(offers, dict):
        return None, ""
    currency = str(offers.get("priceCurrency", ""))
    for key in ("price", "lowPrice"):
        if offers.get(key) not in (None, ""):
            return parse_price(offers[key]), currency
    spec = offers.get("priceSpecification")
    if spec:
        specs = spec if isinstance(spec, list) else [spec]
        for s in specs:
            if isinstance(s, dict) and s.get("price") not in (None, ""):
                return parse_price(s["price"]), str(s.get("priceCurrency", currency))
    return None, currency


def _from_jsonld(soup: BeautifulSoup) -> PageInfo | None:
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _iter_jsonld(data):
            types = node.get("@type", "")
            types = types if isinstance(types, list) else [types]
            if "offers" in node and any(t in ("Product", "ProductGroup", "Offer", "IndividualProduct") or not t for t in types):
                price, currency = _offer_price(node["offers"])
                if price is not None:
                    img = node.get("image", "")
                    if isinstance(img, list):
                        img = img[0] if img else ""
                    if isinstance(img, dict):
                        img = img.get("url", "")
                    return PageInfo(price, str(node.get("name", "")), str(img), currency, "json-ld")
    return None


def extract_page_info(html: str, css_selector: str = "") -> PageInfo:
    soup = BeautifulSoup(html, "html.parser")

    def meta(*names: str) -> str:
        for n in names:
            tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return ""

    title = meta("og:title", "twitter:title")
    if not title and soup.title:
        title = soup.title.get_text(strip=True)
    image = meta("og:image", "twitter:image")
    info = PageInfo(title=title, image=image)

    if css_selector:
        el = soup.select_one(css_selector)
        if el is None:
            raise ScrapeError(f"El selector CSS '{css_selector}' no encontró nada en la página")
        price = parse_price(el.get("content") or el.get_text(" ", strip=True))
        if price is None:
            raise ScrapeError(f"El selector encontró '{el.get_text(strip=True)[:60]}' pero no es un precio")
        info.price, info.method = price, "selector"
        return info

    ld = _from_jsonld(soup)
    if ld:
        ld.title = info.title or ld.title
        ld.image = info.image or ld.image
        return ld

    amount = meta("product:price:amount", "og:price:amount")
    if amount:
        info.price, info.method = parse_price(amount), "meta"
        info.currency = meta("product:price:currency", "og:price:currency")
        if info.price is not None:
            return info

    el = soup.find(attrs={"itemprop": "price"})
    if el is not None:
        price = parse_price(el.get("content") or el.get_text(" ", strip=True))
        if price is not None:
            info.price, info.method = price, "microdata"
            return info

    for el in soup.select('[class*="price" i], [id*="price" i], [class*="precio" i]'):
        if el.name in ("script", "style", "meta", "link"):
            continue
        text = el.get_text(" ", strip=True)
        if text and len(text) < 60:
            price = parse_price(text)
            if price:
                info.price, info.method = price, "heurística"
                return info

    raise ScrapeError(
        "No se encontró el precio. Abre la página, haz clic derecho en el precio → "
        "Inspeccionar, y agrega un selector CSS (ej. .price, #precio)."
    )


def _client() -> httpx.Client:
    return httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)


def fetch_page_info(url: str, css_selector: str = "", ml_token: str = "") -> PageInfo:
    # Publicaciones de Mercado Libre: la API es más estable que el HTML.
    m = _ML_ID_RE.search(url)
    if m and ml_token and "/p/" not in url:
        try:
            return ml_item_info(m.group(1) + m.group(2), ml_token)
        except ScrapeError:
            pass  # se intenta con el HTML
    try:
        with _client() as client:
            resp = client.get(url)
    except httpx.HTTPError as exc:
        raise ScrapeError(f"No se pudo descargar la página: {exc}") from exc
    if resp.status_code >= 400:
        raise ScrapeError(f"La página respondió HTTP {resp.status_code} (puede estar bloqueando bots)")
    return extract_page_info(resp.text, css_selector)


# ------------------------------------------------------------------ Mercado Libre

def ml_item_info(item_id: str, token: str) -> PageInfo:
    with _client() as client:
        resp = client.get(
            f"https://api.mercadolibre.com/items/{item_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        raise ScrapeError(f"API Mercado Libre HTTP {resp.status_code}")
    data = resp.json()
    pics = data.get("pictures") or []
    return PageInfo(
        price=parse_price(data.get("price")),
        title=data.get("title", ""),
        image=(pics[0].get("secure_url") if pics else data.get("thumbnail", "")) or "",
        currency=data.get("currency_id", ""),
        method="api-ml",
    )


def normalize_ml_id(url: str) -> str:
    m = _WID_RE.search(url)
    if m:
        return m.group(1)
    m = _ML_ID_RE.search(url)
    if m:
        return m.group(1) + m.group(2)
    return ""


def search_ml_api(query: str, site: str, token: str = "", limit: int = 50) -> list[SearchItem]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with _client() as client:
        resp = client.get(
            f"https://api.mercadolibre.com/sites/{site}/search",
            params={"q": query, "limit": limit},
            headers=headers,
        )
    if resp.status_code != 200:
        raise ScrapeError(f"API Mercado Libre HTTP {resp.status_code}")
    items = []
    for r in resp.json().get("results", []):
        seller = r.get("seller") or {}
        items.append(SearchItem(
            external_id=r.get("id", ""),
            title=r.get("title", ""),
            price=parse_price(r.get("price")),
            url=r.get("permalink", ""),
            thumbnail=(r.get("thumbnail") or "").replace("http://", "https://"),
            seller=seller.get("nickname", "") or str(seller.get("id", "")),
            sold_quantity=r.get("sold_quantity"),
            free_shipping=bool((r.get("shipping") or {}).get("free_shipping")),
        ))
    return items


def parse_ml_listing_html(html: str) -> list[SearchItem]:
    """Parsea la página de resultados (listado.mercadolibre...)."""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("li.ui-search-layout__item") or soup.select("div.poly-card, div.ui-search-result")
    items: list[SearchItem] = []
    seen: set[str] = set()
    for card in cards:
        link = (
            card.select_one("a.poly-component__title")
            or card.select_one("h2 a, h3 a")
            or card.select_one("a.ui-search-link, a.ui-search-item__group__element")
            or card.select_one("a[href]")
        )
        if not link or not link.get("href"):
            continue
        url = link["href"].split("#")[0] if "wid=" not in link["href"] else link["href"]
        ext_id = normalize_ml_id(link["href"]) or normalize_ml_id(card.decode())
        if not ext_id or ext_id in seen:
            continue
        seen.add(ext_id)
        title_el = card.select_one(".poly-component__title, .ui-search-item__title, h2, h3") or link

        price = None
        price_box = card.select_one(".poly-price__current, .ui-search-price__second-line") or card
        frac = price_box.select_one(".andes-money-amount__fraction")
        if frac:
            price = parse_price(frac.get_text(strip=True).replace(",", "").replace(".", ""))
            cents = price_box.select_one(".andes-money-amount__cents")
            if price is not None and cents and cents.get_text(strip=True).isdigit():
                price += int(cents.get_text(strip=True)) / 100

        img = card.select_one("img")
        thumb = ""
        if img:
            thumb = img.get("data-src") or img.get("src") or ""
            if thumb.startswith("data:"):
                thumb = ""
        seller_el = card.select_one(".poly-component__seller, .ui-search-official-store-label")
        shipping = card.select_one(".poly-component__shipping, .ui-search-item__shipping")
        items.append(SearchItem(
            external_id=ext_id,
            title=title_el.get_text(" ", strip=True),
            price=price,
            url=url,
            thumbnail=thumb,
            seller=seller_el.get_text(" ", strip=True).replace("Por ", "") if seller_el else "",
            free_shipping=bool(shipping and "gratis" in shipping.get_text().lower()),
        ))
    return items


def search_ml_html(query: str, site: str) -> list[SearchItem]:
    domain = ML_DOMAINS.get(site, ML_DOMAINS["MLM"])
    slug = quote(re.sub(r"\s+", "-", query.strip().lower()))
    try:
        with _client() as client:
            resp = client.get(f"https://listado.{domain}/{slug}")
    except httpx.HTTPError as exc:
        raise ScrapeError(f"No se pudo descargar el listado: {exc}") from exc
    if resp.status_code >= 400:
        raise ScrapeError(f"El listado respondió HTTP {resp.status_code}")
    items = parse_ml_listing_html(resp.text)
    if not items:
        raise ScrapeError(
            "Mercado Libre no devolvió resultados legibles (posible verificación anti-bot). "
            "Configura el token de Mercado Libre en Configuración para usar la API."
        )
    return items


def search_mercadolibre(query: str, site: str, token: str = "") -> SearchResponse:
    errors = []
    try:
        return SearchResponse(search_ml_api(query, site, token), "api")
    except (ScrapeError, httpx.HTTPError) as exc:
        errors.append(f"API: {exc}")
    try:
        return SearchResponse(search_ml_html(query, site), "html")
    except (ScrapeError, httpx.HTTPError) as exc:
        errors.append(f"HTML: {exc}")
    raise ScrapeError(" | ".join(errors))
