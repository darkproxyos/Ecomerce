# Panel de Ventas — Mercado Libre + Facebook Marketplace

Dashboard para administrar un negocio de ventas en línea: productos con fotos, inventario,
ventas por canal, clientes, gastos y utilidad real, más **inteligencia de mercado**
(scraping de precios de la competencia y detección de productos nuevos en Mercado Libre).

- **Backend:** Python · FastAPI · SQLAlchemy · SQLite (un archivo, sin servidor de BD)
- **Frontend:** HTML/CSS/JS sin compilación (Chart.js incluido localmente)
- Interfaz en español, modo claro/oscuro automático y adaptada a celular.

## Desplegar en Vercel (recomendado)

1. En Vercel: **Add New → Project → Import** este repositorio → **Deploy** (no cambies nada; `vercel.json` ya trae la configuración).
2. Abre la URL: verás una pantalla que te guía con lo que falta. Una sola vez:
   - **Settings → Environment Variables**:
     - `ADMIN_PASSWORD` → la contraseña para entrar al panel (**obligatoria**).
     - `CRON_SECRET` → cualquier texto largo (activa la revisión automática de precios, 1 vez al día).
     - `APP_TIMEZONE` → opcional, por defecto `America/Mexico_City`.
   - **Storage → Create Database → Neon (Postgres) → Connect** al proyecto. Crea `DATABASE_URL` sola.
     (También sirve Supabase o cualquier PostgreSQL: pon su URL en `DATABASE_URL`.)
3. **Deployments → ⋯ → Redeploy**. Listo: entra con tu contraseña.

Cómo funciona en Vercel:
- `public/` (panel y juego) lo sirve la CDN de Vercel; la API es una función Python (`api/index.py` → `backend/app`).
- Todo se guarda en PostgreSQL, **también las fotos** (Vercel no tiene disco permanente). El navegador las reduce a 1600 px antes de subirlas.
- Sin base de datos el panel funciona en *modo de prueba* y avisa que los datos se borrarán.
- Las revisiones automáticas corren con **Vercel Cron** (`/api/cron`). En el plan gratuito, 1 vez al día; también puedes pulsar “Revisar pendientes” cuando quieras. Cada ejecución dura máx. ~50 s; lo que falte se revisa en la siguiente.
- Para Mercado Libre usa como Redirect URI: `https://TU-PROYECTO.vercel.app/api/ml/callback`.

## Correrlo en tu computadora (opcional)

```bash
./run.sh                      # abre http://localhost:8000 (usa SQLite en data/)
cd backend && .venv/bin/python -m app.seed   # datos de ejemplo
```

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

**Para crecer:**

| Sección | Qué hace |
|---|---|
| **Venta rápida** | Botón **Vendido** en cada producto: registra la venta en 2 toques, descuenta stock y marca *agotado* si ya no queda. |
| **Rotación** | Cuenta los días que lleva publicado cada artículo. A los 14 días sugiere bajar 10%; a los 30, liquidar (−20%, nunca por debajo del costo). Muestra el dinero detenido en Inicio. Los días se configuran. |
| **Oportunidades de compra** | Evalúa algo antes de comprarlo para revender: ganancia, margen, rendimiento y lo máximo que debes pagar. Con **La compré** se crea el producto con su costo real. |
| **Mi ruta** | Las 6 fases del plan (de vender lo de casa a tu propia tienda) con tareas y tu fase detectada con tus números reales: capital, ventas por semana, utilidad y margen. |
| **App en el celular** | Se instala en la pantalla de inicio (Android e iPhone) y abre aunque la señal sea mala. |
| **Respaldo completo** | Descarga un archivo con todo (incluidas las fotos) y restáuralo en otro panel: así pasas tus datos de tu computadora o Termux a Vercel. |

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

## Seguridad

- En Vercel el panel **exige** `ADMIN_PASSWORD`; sin ella la API no muestra datos.
- La sesión dura 30 días (cookie segura). “Cerrar sesión” está en el menú.
- Son públicos sin contraseña: el juego (`/juegos/...`) y las fotos de productos (las necesita el catálogo de Meta).
- Variables: `ADMIN_PASSWORD`, `SESSION_SECRET` (opcional), `DATABASE_URL`, `CRON_SECRET`, `APP_TIMEZONE`.

## Scraping responsable

Revisa los términos de uso de cada sitio, usa intervalos razonables (el mínimo es 15 min; se recomiendan 6–24 h)
y no vigiles cientos de URLs del mismo sitio. Algunas tiendas bloquean bots: en ese caso la vigilancia muestra el error.

## Pruebas

```bash
cd backend && pip install -r requirements-dev.txt && python -m pytest -q
# contra PostgreSQL: TEST_DATABASE_URL=postgresql://usuario@host/db python -m pytest -q
```

## API

Documentación interactiva en `/docs` (solo en tu computadora; en Vercel las rutas fuera de `/api` son del sitio estático).

## Juego DIGIZ

El juego DIGIZ está en **`/juegos/digiz/`** (por ejemplo `https://TU-PROYECTO.vercel.app/juegos/digiz/`).
Es público: no pide la contraseña del panel. Hay un acceso directo en el menú lateral.
Para agregar otro juego, copia su carpeta dentro de `public/juegos/` y quedará en `/juegos/<carpeta>/`.
