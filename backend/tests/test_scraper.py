import pytest

from app.services.scraper import (
    ScrapeError, extract_page_info, normalize_ml_id, parse_ml_listing_html, parse_price,
)


@pytest.mark.parametrize("text,expected", [
    ("$1,299.00", 1299.0),
    ("1.299,90", 1299.9),
    ("MX$ 12 500", 12500.0),
    ("$ 1,234,567.89", 1234567.89),
    ("12.5", 12.5),
    ("3 meses sin intereses de $899", 899.0),
    ("Precio: 45", 45.0),
    (199, 199.0),
    ("sin precio", None),
    ("", None),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


def test_jsonld_product():
    html = """<html><head><title>X</title>
    <script type="application/ld+json">{"@context":"https://schema.org","@graph":[
      {"@type":"BreadcrumbList"},
      {"@type":"Product","name":"Audífonos","image":["https://img/1.jpg"],
       "offers":{"@type":"Offer","price":"1499.00","priceCurrency":"MXN"}}]}</script></head></html>"""
    info = extract_page_info(html)
    assert info.price == 1499.0 and info.currency == "MXN" and info.method == "json-ld"
    assert info.image == "https://img/1.jpg"


def test_jsonld_aggregate_offer_uses_lowest():
    html = """<script type="application/ld+json">{"@type":"Product","name":"A",
      "offers":[{"@type":"Offer","price":"300"},{"@type":"Offer","price":"250"}]}</script>"""
    assert extract_page_info(html).price == 250.0


def test_meta_and_microdata():
    html = '<meta property="product:price:amount" content="899.5"><meta property="og:title" content="Bocina">'
    info = extract_page_info(html)
    assert info.price == 899.5 and info.title == "Bocina"
    html2 = '<div><meta itemprop="price" content="1234"></div>'
    assert extract_page_info(html2).price == 1234.0


def test_css_selector_and_errors():
    html = '<div class="caja"><span class="precio-final">$2,350</span></div>'
    assert extract_page_info(html, ".precio-final").price == 2350.0
    with pytest.raises(ScrapeError):
        extract_page_info(html, ".no-existe")
    with pytest.raises(ScrapeError):
        extract_page_info("<p>nada</p>")


def test_heuristic_price_class():
    html = '<div class="product-price">MX$ 3,499.00</div>'
    info = extract_page_info(html)
    assert info.price == 3499.0 and info.method == "heurística"


def test_normalize_ml_id():
    assert normalize_ml_id("https://articulo.mercadolibre.com.mx/MLM-1234567890-audifonos-_JM") == "MLM1234567890"
    assert normalize_ml_id("https://www.mercadolibre.com.mx/x/p/MLM2233?pdp_filters=1#wid=MLM998877665") == "MLM998877665"
    assert normalize_ml_id("https://ejemplo.com") == ""


def test_parse_ml_listing_html():
    html = """<ol>
    <li class="ui-search-layout__item"><div class="poly-card">
      <img data-src="https://http2.mlstatic.com/a.webp" src="data:image/gif;base64,xx">
      <a class="poly-component__title" href="https://articulo.mercadolibre.com.mx/MLM-111222333-audifonos-_JM">Audífonos X</a>
      <span class="poly-component__seller">Por TiendaUno</span>
      <div class="poly-price__current"><span class="andes-money-amount__fraction">1,299</span><span class="andes-money-amount__cents">50</span></div>
      <div class="poly-component__shipping">Envío gratis</div></div></li>
    <li class="ui-search-layout__item"><div class="poly-card">
      <a class="poly-component__title" href="https://www.mercadolibre.com.mx/audifonos-y/p/MLM555#wid=MLM444555666">Audífonos Y</a>
      <div class="poly-price__current"><span class="andes-money-amount__fraction">899</span></div></div></li>
    </ol>"""
    items = parse_ml_listing_html(html)
    assert [i.external_id for i in items] == ["MLM111222333", "MLM444555666"]
    a, b = items
    assert a.price == 1299.5 and a.seller == "TiendaUno" and a.free_shipping
    assert a.thumbnail == "https://http2.mlstatic.com/a.webp"
    assert b.price == 899.0 and not b.free_shipping
