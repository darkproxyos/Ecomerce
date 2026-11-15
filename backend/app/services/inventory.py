from ..models import Sale


def apply_stock(sale: Sale, restore: bool = False) -> None:
    """Descuenta (o devuelve) del inventario las unidades de una venta."""
    sign = 1 if restore else -1
    for item in sale.items:
        if item.product is not None:
            item.product.stock += sign * item.quantity
