from __future__ import annotations

import datetime as dt
from datetime import datetime

from . import clock

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

CHANNELS = ("mercadolibre", "marketplace", "directo", "otro")
SALE_STATUSES = ("pendiente", "pagado", "enviado", "entregado", "cancelado")
PRODUCT_STATUSES = ("activo", "borrador", "pausado", "agotado")


now = clock.now


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str | None] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="")
    brand: Mapped[str] = mapped_column(String(100), default="")
    condition: Mapped[str] = mapped_column(String(20), default="nuevo")
    cost: Mapped[float] = mapped_column(Float, default=0)
    price: Mapped[float] = mapped_column(Float, default=0)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    min_stock: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="activo")
    supplier: Mapped[str] = mapped_column(String(150), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    images: Mapped[list[ProductImage]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="ProductImage.position"
    )
    listings: Mapped[list[Listing]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class ProductImage(Base):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255), default="")
    content_type: Mapped[str] = mapped_column(String(40), default="image/jpeg")
    size: Mapped[int] = mapped_column(Integer, default=0)
    # La foto se guarda en la base (Vercel no tiene disco persistente). Se carga solo al pedirla.
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    product: Mapped[Product] = relationship(back_populates="images")


class Listing(Base):
    """Publicación de un producto en un canal (Mercado Libre, Marketplace, ...)."""

    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(30))
    external_id: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(255), default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    price: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="activa")
    views: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    product: Mapped[Product | None] = relationship(back_populates="listings")


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(50), default="")
    email: Mapped[str] = mapped_column(String(150), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    channel: Mapped[str] = mapped_column(String(30), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    sales: Mapped[list[Sale]] = relationship(back_populates="customer")


class Sale(Base):
    __tablename__ = "sales"
    __table_args__ = (UniqueConstraint("channel", "external_id", name="uq_sale_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, default=clock.today)
    channel: Mapped[str] = mapped_column(String(30), default="marketplace")
    status: Mapped[str] = mapped_column(String(20), default="pagado")
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    commission: Mapped[float] = mapped_column(Float, default=0)
    shipping_cost: Mapped[float] = mapped_column(Float, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    customer: Mapped[Customer | None] = relationship(back_populates="sales")
    items: Mapped[list[SaleItem]] = relationship(
        back_populates="sale", cascade="all, delete-orphan"
    )

    @property
    def total(self) -> float:
        return round(sum(i.quantity * i.unit_price for i in self.items), 2)

    @property
    def cost_total(self) -> float:
        return round(sum(i.quantity * i.unit_cost for i in self.items), 2)

    @property
    def profit(self) -> float:
        if self.status == "cancelado":
            return 0.0
        return round(self.total - self.cost_total - self.commission - self.shipping_cost, 2)


class SaleItem(Base):
    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"))
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[str] = mapped_column(String(255), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    unit_cost: Mapped[float] = mapped_column(Float, default=0)

    sale: Mapped[Sale] = relationship(back_populates="items")
    product: Mapped[Product | None] = relationship()


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, default=clock.today)
    category: Mapped[str] = mapped_column(String(80), default="general")
    description: Mapped[str] = mapped_column(String(255), default="")
    amount: Mapped[float] = mapped_column(Float, default=0)


# ---------------------------------------------------------------- Inteligencia de mercado

class WatchItem(Base):
    """Una URL de la competencia cuyo precio se vigila."""

    __tablename__ = "watch_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(String(1000))
    css_selector: Mapped[str] = mapped_column(String(300), default="")
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_hours: Mapped[float] = mapped_column(Float, default=12)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    prev_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_title: Mapped[str] = mapped_column(String(500), default="")
    last_image: Mapped[str] = mapped_column(String(1000), default="")
    last_checked: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    product: Mapped[Product | None] = relationship()
    snapshots: Mapped[list[PriceSnapshot]] = relationship(
        back_populates="watch", cascade="all, delete-orphan", order_by="PriceSnapshot.checked_at"
    )


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("watch_items.id", ondelete="CASCADE"))
    price: Mapped[float] = mapped_column(Float)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    watch: Mapped[WatchItem] = relationship(back_populates="snapshots")


class MarketSearch(Base):
    """Búsqueda recurrente en Mercado Libre para descubrir productos y precios."""

    __tablename__ = "market_searches"

    id: Mapped[int] = mapped_column(primary_key=True)
    query: Mapped[str] = mapped_column(String(200))
    site: Mapped[str] = mapped_column(String(10), default="MLM")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_hours: Mapped[float] = mapped_column(Float, default=24)
    last_run: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_source: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    results: Mapped[list[MarketResult]] = relationship(
        back_populates="search", cascade="all, delete-orphan"
    )


class MarketResult(Base):
    __tablename__ = "market_results"
    __table_args__ = (UniqueConstraint("search_id", "external_id", name="uq_result"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    search_id: Mapped[int] = mapped_column(ForeignKey("market_searches.id", ondelete="CASCADE"))
    external_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(500), default="")
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    prev_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    url: Mapped[str] = mapped_column(String(1000), default="")
    thumbnail: Mapped[str] = mapped_column(String(1000), default="")
    seller: Mapped[str] = mapped_column(String(200), default="")
    sold_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    free_shipping: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=now)

    search: Mapped[MarketSearch] = relationship(back_populates="results")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
