from __future__ import annotations

from datetime import date as Date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import CHANNELS, PRODUCT_STATUSES, SALE_STATUSES


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ Productos

class ImageOut(ORM):
    id: int
    filename: str
    position: int
    url: str = ""


class ListingIn(BaseModel):
    product_id: int | None = None
    channel: str
    external_id: str = ""
    title: str = ""
    url: str = ""
    price: float = 0
    status: str = "activa"
    views: int = 0

    @field_validator("channel")
    @classmethod
    def _channel(cls, v: str) -> str:
        if v not in CHANNELS:
            raise ValueError(f"canal inválido, usa uno de {CHANNELS}")
        return v


class ListingOut(ListingIn, ORM):
    id: int
    created_at: datetime


class ProductIn(BaseModel):
    sku: str | None = None
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    category: str = ""
    brand: str = ""
    condition: str = "nuevo"
    cost: float = Field(0, ge=0)
    price: float = Field(0, ge=0)
    stock: int = 0
    min_stock: int = 1
    status: str = "activo"
    supplier: str = ""
    notes: str = ""

    @field_validator("sku")
    @classmethod
    def _sku(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in PRODUCT_STATUSES:
            raise ValueError(f"estado inválido, usa uno de {PRODUCT_STATUSES}")
        return v


class ProductOut(ProductIn, ORM):
    id: int
    created_at: datetime
    updated_at: datetime
    images: list[ImageOut] = []
    listings: list[ListingOut] = []
    margin: float = 0
    margin_pct: float = 0
    low_stock: bool = False
    units_sold: int = 0


# ------------------------------------------------------------------ Clientes

class CustomerIn(BaseModel):
    name: str = Field(min_length=1)
    phone: str = ""
    email: str = ""
    city: str = ""
    channel: str = ""
    notes: str = ""


class CustomerOut(CustomerIn, ORM):
    id: int
    created_at: datetime
    orders: int = 0
    total_spent: float = 0


# ------------------------------------------------------------------ Ventas

class SaleItemIn(BaseModel):
    product_id: int | None = None
    description: str = ""
    quantity: int = Field(1, ge=1)
    unit_price: float = Field(ge=0)
    unit_cost: float | None = None  # si es None se toma el costo del producto


class SaleItemOut(ORM):
    id: int
    product_id: int | None
    description: str
    quantity: int
    unit_price: float
    unit_cost: float


class SaleIn(BaseModel):
    date: Date | None = None
    channel: str = "marketplace"
    status: str = "pagado"
    customer_id: int | None = None
    customer_name: str = ""  # crea cliente al vuelo si no se pasa customer_id
    external_id: str | None = None
    commission: float | None = None  # None => se calcula con el % configurado del canal
    shipping_cost: float = 0
    notes: str = ""
    items: list[SaleItemIn] = Field(min_length=1)

    @field_validator("channel")
    @classmethod
    def _channel(cls, v: str) -> str:
        if v not in CHANNELS:
            raise ValueError(f"canal inválido, usa uno de {CHANNELS}")
        return v

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in SALE_STATUSES:
            raise ValueError(f"estado inválido, usa uno de {SALE_STATUSES}")
        return v


class SaleStatusIn(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in SALE_STATUSES:
            raise ValueError(f"estado inválido, usa uno de {SALE_STATUSES}")
        return v


class SaleOut(ORM):
    id: int
    date: Date
    channel: str
    status: str
    customer_id: int | None
    customer_name: str = ""
    external_id: str | None
    commission: float
    shipping_cost: float
    notes: str
    items: list[SaleItemOut]
    total: float
    cost_total: float
    profit: float
    created_at: datetime


# ------------------------------------------------------------------ Gastos

class ExpenseIn(BaseModel):
    date: Date | None = None
    category: str = "general"
    description: str = ""
    amount: float = Field(ge=0)


class ExpenseOut(ExpenseIn, ORM):
    id: int
    date: Date


# ------------------------------------------------------------------ Competencia

class WatchIn(BaseModel):
    name: str = ""
    url: str = Field(min_length=8)
    css_selector: str = ""
    product_id: int | None = None
    active: bool = True
    interval_hours: float = Field(12, ge=0.25)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("la URL debe empezar con http:// o https://")
        return v


class SnapshotOut(ORM):
    price: float
    checked_at: datetime


class WatchOut(WatchIn, ORM):
    id: int
    last_price: float | None
    prev_price: float | None
    last_title: str
    last_image: str
    last_checked: datetime | None
    last_error: str
    created_at: datetime
    product_name: str = ""
    product_price: float | None = None
    min_price: float | None = None
    max_price: float | None = None


class SearchIn(BaseModel):
    query: str = Field(min_length=2)
    site: str = "MLM"
    active: bool = True
    interval_hours: float = Field(24, ge=1)


class SearchOut(SearchIn, ORM):
    id: int
    last_run: datetime | None
    last_error: str
    last_source: str
    created_at: datetime
    result_count: int = 0
    new_count: int = 0
    avg_price: float | None = None
    min_price: float | None = None
    max_price: float | None = None


class ResultOut(ORM):
    id: int
    external_id: str
    title: str
    price: float | None
    prev_price: float | None
    url: str
    thumbnail: str
    seller: str
    sold_quantity: int | None
    free_shipping: bool
    first_seen: datetime
    last_seen: datetime
    is_new: bool = False
