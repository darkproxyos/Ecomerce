# Panel de Ventas — Mercado Libre + Facebook Marketplace

Dashboard para administrar un negocio de ventas en línea: productos con fotos, inventario,
ventas por canal, clientes, gastos y utilidad real, más **inteligencia de mercado**
(scraping de precios de la competencia y detección de productos nuevos en Mercado Libre).

- **Backend:** Python · FastAPI · SQLAlchemy · SQLite (un archivo, sin servidor de BD)
- **Frontend:** HTML/CSS/JS sin compilación (Chart.js incluido localmente)
- Interfaz en español, modo claro/oscuro automático y adaptada a celular.

## Arranque rápido

```bash
./run.sh                      # crea el entorno, instala dependencias y arranca
# abre http://localhost:8000
```

Para cargar datos de ejemplo (8 productos y ~3 meses de ventas) y ver el panel lleno:

```bash
cd backend && .venv/bin/python -m app.seed
```

Los datos quedan en `data/` (`negocio.db` y `uploads/` con las fotos). **Respalda esa carpeta.**

## Qué incluye

| Sección | Qué hace |
|---|---|
| **Inicio** | Ingresos, utilidad neta, pedidos, ticket promedio, comisiones y gastos vs. periodo anterior; ventas por día y canal; top productos; stock bajo; alertas de competencia. |
| **Productos** | Catálogo con SKU, costo, precio, margen (y margen neto en ML), stock y mínimo. Fotos con arrastrar y soltar (portada, descarga). Registro de publicaciones por canal. **Texto listo para publicar** en Marketplace y Mercado Libre. |
| **Ventas** | Ventas con varios artículos, canal, estado (pendiente → entregado / cancelado), cliente, envío y comisión automática por canal. El inventario se descuenta y se devuelve solo al cancelar/eliminar. |
| **Clientes** | Se crean al registrar ventas; historial de pedidos y total comprado; enlace a WhatsApp. |
| **Gastos** | Publicidad, empaque, envíos… para calcular la utilidad neta. |
| **Precios competencia** | Pega la URL de un producto de cualquier tienda: detecta el precio (JSON‑LD, meta tags, microdatos o un selector CSS), lo revisa cada X horas, guarda historial, lo compara con tu precio y genera alertas. |
| **Búsquedas y novedades** | Palabras clave en Mercado Libre: rango y promedio de precios, vendedores, cambios de precio y **productos nuevos** que aparecen entre revisiones. |
| **Configuración** | Moneda, país, % de comisión por canal, conexión con Mercado Libre, exportaciones CSV y catálogo para Meta. |

El planificador interno ejecuta automáticamente las revisiones pendientes cada minuto mientras el servidor esté encendido.

## Mercado Libre (API oficial)

1. Crea una aplicación en <https://developers.mercadolibre.com.mx/devcenter>.
2. Redirect URI: `https://TU-DOMINIO/api/ml/callback` (ML exige HTTPS; en local puedes usar un túnel como ngrok o Cloudflare Tunnel).
3. En **Configuración** pega App ID y Secret Key → **Conectar con Mercado Libre**.

Con la cuenta conectada puedes:
- **Importar pedidos** (crea ventas con la comisión real de ML y descuenta inventario; si se cancelan, lo devuelve).
- **Importar publicaciones** (se vinculan a tus productos por SKU).
- **Sincronizar** precio y stock de una publicación desde la ficha del producto.
- Las búsquedas de mercado y la vigilancia de URLs de ML usan la API (más estable que leer el HTML).

Sin conexión, las búsquedas intentan leer la página pública de resultados; Mercado Libre puede bloquearlo con verificaciones anti‑bot, por eso se recomienda conectar la cuenta.

## Facebook Marketplace

Meta **no ofrece una API pública** para publicar en Marketplace como particular. El panel te ayuda así:
- Pestaña **Texto para publicar** en cada producto (copiar con un clic) + descarga de fotos.
- **Catálogo Meta (CSV)** en Configuración, en el formato de Commerce Manager, para tiendas en Facebook/Instagram.
- Las ventas de Marketplace se registran manualmente en *Ventas* (canal “Marketplace”).

## Seguridad / publicarlo en internet

Si el panel va a estar accesible fuera de tu computadora, define una contraseña:

```bash
ADMIN_PASSWORD='una-clave-larga' ADMIN_USER=admin HOST=0.0.0.0 ./run.sh
```

y ponlo detrás de HTTPS (Caddy, Nginx, Cloudflare Tunnel…).

Variables disponibles: `ADMIN_PASSWORD`, `ADMIN_USER`, `DATA_DIR`, `DATABASE_URL`,
`SCHEDULER_ENABLED` (1/0), `SCHEDULER_TICK_SECONDS`, `HOST`, `PORT`.

## Scraping responsable

Revisa los términos de uso de cada sitio, usa intervalos razonables (el mínimo es 15 min; se recomiendan 6–24 h)
y no vigiles cientos de URLs del mismo sitio. Algunas tiendas bloquean bots: en ese caso la vigilancia muestra el error.

## Pruebas

```bash
cd backend && .venv/bin/pip install pytest && .venv/bin/python -m pytest -q
```

## API

Documentación interactiva en `http://localhost:8000/docs`.
