/* Panel de ventas — SPA sin dependencias de compilación. */
'use strict';

// ======================================================================= utilidades
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const view = $('#view');
const state = { settings: {}, charts: [] };

const CH = {
  mercadolibre: { label: 'Mercado Libre', color: '--s1' },
  marketplace: { label: 'Marketplace', color: '--s2' },
  directo: { label: 'Directo', color: '--s3' },
  otro: { label: 'Otro', color: '--s4' },
};
const SALE_STATUS = {
  pendiente: 'warn', pagado: 'info', enviado: 'info', entregado: 'good', cancelado: 'bad',
};
const PRODUCT_STATUS = { activo: 'good', borrador: '', pausado: 'warn', agotado: 'bad' };

function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function money(n, opts = {}) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  try {
    return new Intl.NumberFormat('es-MX', {
      style: 'currency', currency: state.settings.currency || 'MXN',
      maximumFractionDigits: opts.decimals ?? (Math.abs(n) >= 1000 ? 0 : 2),
      minimumFractionDigits: 0,
    }).format(n);
  } catch { return '$' + Number(n).toFixed(2); }
}
const num = n => new Intl.NumberFormat('es-MX').format(n ?? 0);
const today = () => new Date().toISOString().slice(0, 10);
function fmtDate(s) {
  if (!s) return '—';
  const d = new Date(s.length <= 10 ? s + 'T12:00:00' : s);
  return d.toLocaleDateString('es-MX', { day: '2-digit', month: 'short', year: '2-digit' });
}
function fmtDateTime(s) {
  if (!s) return 'nunca';
  return new Date(s).toLocaleString('es-MX', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}
function ago(s) {
  if (!s) return 'nunca';
  const m = Math.round((Date.now() - new Date(s)) / 60000);
  if (m < 1) return 'hace un momento';
  if (m < 60) return `hace ${m} min`;
  if (m < 1440) return `hace ${Math.round(m / 60)} h`;
  return `hace ${Math.round(m / 1440)} d`;
}
function pctDelta(cur, prev) {
  if (!prev) return cur ? null : 0;
  return ((cur - prev) / Math.abs(prev)) * 100;
}
const chan = c => `<span class="chan"><span class="dot" style="background:var(${(CH[c] || CH.otro).color})"></span>${esc((CH[c] || { label: c }).label)}</span>`;
const badge = (txt, kind = '') => `<span class="badge ${kind}">${esc(txt)}</span>`;
const thumb = url => url ? `<img class="thumb" src="${esc(url)}" alt="" loading="lazy">` : '<div class="thumb ph">▦</div>';

async function api(path, { method = 'GET', body, form } = {}) {
  const opts = { method, headers: {} };
  if (form) opts.body = form;
  else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers['Content-Type'] = 'application/json'; }
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && data.login) { showLogin(); throw new Error('Inicia sesión para continuar'); }
  if (res.status === 503 && data.setup) { showSetup(state.status || {}); throw new Error(data.detail); }
  if (!res.ok) {
    let msg = data.detail || res.statusText;
    if (Array.isArray(msg)) msg = msg.map(e => `${(e.loc || []).slice(1).join('.')}: ${e.msg}`).join(' · ');
    throw new Error(msg);
  }
  return data;
}

function toast(msg, kind = '') {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), kind === 'error' ? 7000 : 3500);
}

async function busy(btn, fn) {
  const old = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="spin"></span> ${old}`;
  try { return await fn(); }
  catch (e) { toast(e.message, 'error'); }
  finally { btn.disabled = false; btn.innerHTML = old; }
}

function formData(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === 'checkbox') out[el.name] = el.checked;
    else if (el.type === 'number') out[el.name] = el.value === '' ? null : Number(el.value);
    else out[el.name] = el.value;
  }
  return out;
}

function setActions(html) { $('#page-actions').innerHTML = html; }

function destroyCharts() { state.charts.forEach(c => c.destroy()); state.charts = []; }

// ======================================================================= modal
function openModal({ title, body, foot = '', wide = false, onClose }) {
  const root = $('#modal-root');
  const wrap = document.createElement('div');
  wrap.className = 'modal-backdrop';
  wrap.innerHTML = `<div class="modal ${wide ? 'wide' : ''}" role="dialog" aria-modal="true">
    <div class="modal-head"><h2>${esc(title)}</h2><button class="icon-btn" data-close aria-label="Cerrar">✕</button></div>
    <div class="modal-body">${body}</div>
    ${foot ? `<div class="modal-foot">${foot}</div>` : ''}</div>`;
  const close = () => { wrap.remove(); document.removeEventListener('keydown', onKey); onClose && onClose(); };
  const onKey = e => { if (e.key === 'Escape') close(); };
  wrap.addEventListener('mousedown', e => { if (e.target === wrap) close(); });
  wrap.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', close));
  document.addEventListener('keydown', onKey);
  root.appendChild(wrap);
  const first = wrap.querySelector('input, select, textarea');
  if (first) setTimeout(() => first.focus(), 30);
  return { el: wrap, close };
}

function confirmDialog(message, okLabel = 'Eliminar') {
  return new Promise(resolve => {
    const m = openModal({
      title: 'Confirmar', body: `<p>${esc(message)}</p>`,
      foot: `<button class="btn" data-close>Cancelar</button><button class="btn primary" id="cf-ok">${esc(okLabel)}</button>`,
      onClose: () => resolve(false),
    });
    $('#cf-ok', m.el).addEventListener('click', () => { resolve(true); m.el.remove(); });
  });
}

// ======================================================================= gráficas
function baseChartOptions(extra = {}) {
  const muted = cssVar('--muted'), grid = cssVar('--grid');
  return {
    responsive: true, maintainAspectRatio: false, animation: { duration: 250 },
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: cssVar('--surface'), titleColor: cssVar('--text'), bodyColor: cssVar('--text-2'),
        borderColor: cssVar('--border'), borderWidth: 1, padding: 10, boxPadding: 4, usePointStyle: true,
        callbacks: { label: c => ` ${c.dataset.label}: ${money(c.parsed.y ?? c.parsed.x)}` },
      },
    },
    scales: {
      x: { grid: { display: false }, ticks: { color: muted, maxRotation: 0, autoSkipPadding: 14 }, border: { color: cssVar('--axis') } },
      y: { grid: { color: grid }, border: { display: false }, ticks: { color: muted, callback: v => money(v, { decimals: 0 }) }, beginAtZero: true },
    },
    ...extra,
  };
}
function makeChart(canvas, config) {
  const c = new Chart(canvas, config);
  state.charts.push(c);
  return c;
}

// ======================================================================= router
const routes = {};
function route(name, title, fn) { routes[name] = { title, fn }; }

async function render() {
  const hash = location.hash.replace(/^#\/?/, '') || 'inicio';
  const [path, query = ''] = hash.split('?');
  const [name, ...rest] = path.split('/');
  const r = routes[name] || routes.inicio;
  $$('.sidebar nav a').forEach(a => a.classList.toggle('active', a.dataset.route === name));
  $('#sidebar').classList.remove('open');
  $('#page-title').textContent = r.title;
  setActions('');
  destroyCharts();
  $('#modal-root').innerHTML = '';
  view.innerHTML = '<div class="empty"><span class="spin"></span></div>';
  try {
    await r.fn(rest, new URLSearchParams(query));
  } catch (e) {
    view.innerHTML = `<div class="notice bad">Error: ${esc(e.message)}</div>`;
  }
}
window.addEventListener('hashchange', render);
$('#menu-btn').addEventListener('click', () => $('#sidebar').classList.toggle('open'));

// ======================================================================= INICIO
let dashDays = Number(localStorageGet('dashDays') || 30);
function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* sin almacenamiento */ } }

route('inicio', 'Inicio', async () => {
  setActions(`<div class="seg" id="period">${[7, 30, 90, 365].map(d =>
    `<button data-d="${d}" class="${d === dashDays ? 'on' : ''}">${d === 365 ? '12 meses' : d + ' días'}</button>`).join('')}</div>
    <a class="btn primary" href="#/ventas?nueva=1">+ Venta</a>`);
  $$('#period button').forEach(b => b.addEventListener('click', () => {
    dashDays = Number(b.dataset.d); localStorageSet('dashDays', dashDays); render();
  }));

  const d = await api(`/api/dashboard?days=${dashDays}`);
  const k = d.kpis, p = d.previous;
  const kpi = (label, val, cur, prev, fmt = money, invert = false) => {
    const pct = pctDelta(cur, prev);
    let delta = '<div class="delta">sin periodo previo</div>';
    if (pct !== null) {
      const good = invert ? pct <= 0 : pct >= 0;
      const arrow = pct > 0 ? '▲' : pct < 0 ? '▼' : '■';
      delta = `<div class="delta ${pct === 0 ? '' : good ? 'up' : 'down'}">${arrow} ${Math.abs(pct).toFixed(1)}% vs. periodo anterior</div>`;
    }
    return `<div class="card kpi"><div class="label">${label}</div><div class="value">${fmt(val)}</div>${delta}</div>`;
  };

  const channels = Object.keys(CH).filter(c => d.series.some(r => r[c] > 0));
  const maxTop = Math.max(...d.top_products.map(t => t.revenue), 1);
  const totalCh = d.by_channel.reduce((a, c) => a + c.revenue, 0) || 1;

  view.innerHTML = `
  <div class="stack">
    ${(d.alerts.length || d.low_stock.length || d.new_market_count) ? `<div class="row">
      ${d.pending_orders ? `<a class="badge warn" href="#/ventas?status=pagado">● ${d.pending_orders} pedidos por enviar</a>` : ''}
      ${d.low_stock.length ? `<a class="badge bad" href="#/productos?low=1">▼ ${d.low_stock.length} con stock bajo</a>` : ''}
      ${d.alerts.length ? `<a class="badge warn" href="#/competencia">◎ ${d.alerts.length} alertas de precio</a>` : ''}
      ${d.new_market_count ? `<a class="badge info" href="#/mercado">✦ ${d.new_market_count} productos nuevos en el mercado</a>` : ''}
    </div>` : ''}
    <div class="grid kpis">
      ${kpi('Ventas (ingresos)', k.revenue, k.revenue, p.revenue)}
      ${kpi('Utilidad neta', k.net_profit, k.net_profit, p.net_profit)}
      ${kpi('Pedidos', k.orders, k.orders, p.orders, num)}
      ${kpi('Ticket promedio', k.avg_ticket, k.avg_ticket, p.avg_ticket)}
      ${kpi('Comisiones y envíos', k.commissions, k.commissions, p.commissions, money, true)}
      ${kpi('Gastos', k.expenses, k.expenses, p.expenses, money, true)}
    </div>
    <div class="grid cols-2">
      <div class="card">
        <div class="card-head"><h2>Ventas por ${d.period.bucket_days === 1 ? 'día' : 'semana'} y canal</h2>
          <div class="legend">${channels.map(c => `<span><i class="dot" style="background:var(${CH[c].color})"></i>${CH[c].label}</span>`).join('')}</div></div>
        ${channels.length ? '<div class="chart-box"><canvas id="ch-sales"></canvas></div>'
          : '<div class="empty"><div class="big">📈</div>Aún no hay ventas en este periodo.<br><a href="#/ventas?nueva=1">Registra tu primera venta</a></div>'}
      </div>
      <div class="card">
        <div class="card-head"><h2>Por canal</h2></div>
        ${d.by_channel.length ? `<div class="bar-list">${d.by_channel.map(c => `
          <div class="bar-item"><div class="top"><span>${chan(c.channel)}</span><span class="num">${money(c.revenue)}</span></div>
          <div class="bar-track"><div class="bar-fill" style="width:${(c.revenue / totalCh * 100).toFixed(1)}%;background:var(${(CH[c.channel] || CH.otro).color})"></div></div>
          <div class="small muted">${c.orders} pedidos · utilidad ${money(c.profit)} · ${(c.revenue / totalCh * 100).toFixed(0)}%</div></div>`).join('')}</div>`
          : '<div class="empty">Sin datos</div>'}
        <hr style="border:0;border-top:1px solid var(--border);margin:16px 0">
        <h2 style="margin-bottom:10px">Inventario</h2>
        <div class="list">
          <div class="list-item"><span class="grow">Productos activos</span><b>${d.inventory.active} / ${d.inventory.products}</b></div>
          <div class="list-item"><span class="grow">Unidades en stock</span><b>${num(d.inventory.units)}</b></div>
          <div class="list-item"><span class="grow">Valor a costo</span><b>${money(d.inventory.cost_value)}</b></div>
          <div class="list-item"><span class="grow">Valor a precio de venta</span><b>${money(d.inventory.retail_value)}</b></div>
        </div>
      </div>
    </div>
    <div class="grid cols-2e">
      <div class="card">
        <div class="card-head"><h2>Productos más vendidos</h2><span class="small muted">por ingresos</span></div>
        ${d.top_products.length ? `<div class="bar-list">${d.top_products.map(t => `
          <div class="bar-item"><div class="top"><span title="${esc(t.name)}">${esc(t.name)}</span><span class="num">${money(t.revenue)}</span></div>
          <div class="bar-track"><div class="bar-fill" style="width:${(t.revenue / maxTop * 100).toFixed(1)}%"></div></div>
          <div class="small muted">${t.units} uds · utilidad ${money(t.profit)}</div></div>`).join('')}</div>`
          : '<div class="empty">Sin ventas todavía</div>'}
      </div>
      <div class="card">
        <div class="card-head"><h2>Últimas ventas</h2><a href="#/ventas" class="small">Ver todas →</a></div>
        ${d.recent_sales.length ? `<div class="list">${d.recent_sales.map(s => `
          <div class="list-item"><div class="grow"><div class="ellipsis">${esc(s.items)}</div>
            <div class="small muted">${fmtDate(s.date)} · ${esc(s.customer || 'Sin cliente')} · ${chan(s.channel)}</div></div>
            <div class="right"><div class="num"><b>${money(s.total)}</b></div>${badge(s.status, SALE_STATUS[s.status])}</div></div>`).join('')}</div>`
          : '<div class="empty">Sin ventas</div>'}
      </div>
    </div>
    <div class="grid cols-2e">
      <div class="card">
        <div class="card-head"><h2>Stock bajo</h2><a class="small" href="#/productos?low=1">Ver →</a></div>
        ${d.low_stock.length ? `<div class="list">${d.low_stock.map(p => `
          <a class="list-item" href="#/productos/${p.id}" style="color:inherit"><span class="grow ellipsis">${esc(p.name)} <span class="muted small">${esc(p.sku || '')}</span></span>
          ${badge(`${p.stock} uds (mín. ${p.min_stock})`, p.stock <= 0 ? 'bad' : 'warn')}</a>`).join('')}</div>`
          : '<div class="empty">✓ Todo el inventario está por encima del mínimo</div>'}
      </div>
      <div class="card">
        <div class="card-head"><h2>Alertas de competencia</h2><a class="small" href="#/competencia">Ver →</a></div>
        ${d.alerts.length ? `<div class="list">${d.alerts.map(a => `
          <div class="list-item"><div class="grow"><div class="ellipsis">${esc(a.name)}</div>
          <div class="small muted">${a.type === 'cheaper'
            ? `Competidor ${money(a.competitor_price)} · tu precio ${money(a.my_price)} (${esc(a.product)})`
            : `Cambió de ${money(a.prev_price)} a ${money(a.competitor_price)}`}</div></div>
          ${a.type === 'cheaper' ? badge('▼ más barato', 'bad') : badge(a.competitor_price < a.prev_price ? '▼ bajó' : '▲ subió', 'warn')}</div>`).join('')}</div>`
          : '<div class="empty">Sin alertas. Agrega URLs en <a href="#/competencia">Precios competencia</a>.</div>'}
      </div>
    </div>
  </div>`;

  if (channels.length) {
    const labels = d.series.map(r => fmtDate(r.date));
    makeChart($('#ch-sales'), {
      type: 'bar',
      data: {
        labels,
        datasets: channels.map(c => ({
          label: CH[c].label, data: d.series.map(r => r[c]), backgroundColor: cssVar(CH[c].color),
          borderColor: cssVar('--surface'), borderWidth: { top: 2, left: 0, right: 0, bottom: 0 },
          borderRadius: 3, borderSkipped: 'bottom', maxBarThickness: 28, stack: 's',
        })),
      },
      options: baseChartOptions({
        scales: {
          ...baseChartOptions().scales,
          x: { ...baseChartOptions().scales.x, stacked: true },
          y: { ...baseChartOptions().scales.y, stacked: true },
        },
        plugins: {
          ...baseChartOptions().plugins,
          tooltip: {
            ...baseChartOptions().plugins.tooltip,
            filter: i => i.parsed.y > 0,
            callbacks: {
              label: c => ` ${c.dataset.label}: ${money(c.parsed.y)}`,
              footer: items => `Total: ${money(items.reduce((a, i) => a + i.parsed.y, 0))}`,
            },
          },
        },
      }),
    });
  }
});

// ======================================================================= PRODUCTOS
route('productos', 'Productos', async (rest, qs) => {
  setActions(`<a class="btn" href="/api/export/products.csv">⇩ CSV</a><button class="btn primary" id="new-product">+ Producto</button>`);
  $('#new-product').addEventListener('click', () => productEditor(null));

  const cats = await api('/api/categories');
  let mode = localStorageGet('productView') || 'grid';
  view.innerHTML = `
    <div class="filters">
      <input type="search" id="pf-q" placeholder="Buscar por nombre, SKU, marca…">
      <select id="pf-cat"><option value="">Todas las categorías</option>${cats.map(c => `<option>${esc(c)}</option>`).join('')}</select>
      <select id="pf-status"><option value="">Todos los estados</option>${Object.keys(PRODUCT_STATUS).map(s => `<option>${s}</option>`).join('')}</select>
      <label class="row small"><input type="checkbox" id="pf-low" style="width:auto" ${qs.get('low') ? 'checked' : ''}> Stock bajo</label>
      <span class="spacer"></span>
      <div class="seg" id="pf-mode"><button data-m="grid">▦ Tarjetas</button><button data-m="table">☰ Tabla</button></div>
    </div>
    <div id="plist"></div>`;

  const load = async () => {
    const params = new URLSearchParams({ q: $('#pf-q').value, category: $('#pf-cat').value, status: $('#pf-status').value });
    if ($('#pf-low').checked) params.set('low_stock', 'true');
    const items = await api('/api/products?' + params);
    $$('#pf-mode button').forEach(b => b.classList.toggle('on', b.dataset.m === mode));
    const box = $('#plist');
    if (!items.length) {
      box.innerHTML = `<div class="card empty"><div class="big">▦</div>No hay productos${params.get('q') ? ' que coincidan' : ''}.<br><br>
        <button class="btn primary" onclick="productEditor(null)">+ Agregar producto</button></div>`;
      return;
    }
    if (mode === 'grid') {
      box.innerHTML = `<div class="product-grid">${items.map(p => `
        <div class="pcard" data-id="${p.id}">
          <div class="img">${p.images[0] ? `<img src="${esc(p.images[0].url)}" alt="" loading="lazy">` : '▦'}</div>
          <div class="body">
            <div class="name">${esc(p.name)}</div>
            <div class="row"><span class="price">${money(p.price)}</span><span class="spacer"></span>${badge(p.status, PRODUCT_STATUS[p.status])}</div>
            <div class="small muted">${esc(p.sku || 'sin SKU')} · margen ${p.margin_pct}%</div>
            <div class="row small">${p.low_stock ? badge(`stock ${p.stock}`, p.stock <= 0 ? 'bad' : 'warn') : `<span class="muted">stock ${p.stock}</span>`}
              <span class="spacer"></span>${[...new Set(p.listings.map(l => l.channel))].map(c => `<span class="dot" title="${CH[c]?.label}" style="background:var(${CH[c]?.color})"></span>`).join('')}</div>
          </div>
        </div>`).join('')}</div>`;
    } else {
      box.innerHTML = `<div class="card table-wrap"><table><thead><tr><th></th><th>Producto</th><th>SKU</th><th>Categoría</th>
        <th class="num">Costo</th><th class="num">Precio</th><th class="num">Margen</th><th class="num">Stock</th><th class="num">Vendidos</th><th>Estado</th></tr></thead>
        <tbody>${items.map(p => `<tr class="clickable" data-id="${p.id}"><td>${thumb(p.images[0]?.url)}</td>
          <td><b>${esc(p.name)}</b><div class="small muted">${esc(p.brand)}</div></td><td>${esc(p.sku || '')}</td><td>${esc(p.category)}</td>
          <td class="num">${money(p.cost)}</td><td class="num">${money(p.price)}</td>
          <td class="num">${money(p.margin)} <span class="muted small">${p.margin_pct}%</span></td>
          <td class="num">${p.low_stock ? badge(p.stock, p.stock <= 0 ? 'bad' : 'warn') : p.stock}</td>
          <td class="num">${p.units_sold}</td><td>${badge(p.status, PRODUCT_STATUS[p.status])}</td></tr>`).join('')}</tbody></table></div>`;
    }
    $$('[data-id]', box).forEach(el => el.addEventListener('click', () => { location.hash = `#/productos/${el.dataset.id}`; }));
  };

  let t;
  $('#pf-q').addEventListener('input', () => { clearTimeout(t); t = setTimeout(load, 250); });
  ['#pf-cat', '#pf-status', '#pf-low'].forEach(s => $(s).addEventListener('change', load));
  $$('#pf-mode button').forEach(b => b.addEventListener('click', () => { mode = b.dataset.m; localStorageSet('productView', mode); load(); }));
  window.reloadProducts = load;
  await load();
  if (rest[0]) productEditor(Number(rest[0]));
});

function listingTexts(p) {
  const s = state.settings;
  const title = p.name.slice(0, 60);
  const bullets = (p.description || '').split(/\n+/).filter(Boolean);
  const ml = `${title}\n\nPrecio: ${money(p.price)}\n\n${p.description || ''}\n\n` +
    `• Condición: ${p.condition}\n${p.brand ? `• Marca: ${p.brand}\n` : ''}${p.sku ? `• SKU: ${p.sku}\n` : ''}` +
    `\nEnvío a todo el país. Si tienes dudas, pregúntanos antes de comprar. ¡Gracias por tu compra!`;
  const fb = `${p.name}\n${money(p.price)}\n\n${bullets.length ? bullets.join('\n') : p.name}\n\n` +
    `✅ ${p.condition === 'nuevo' ? 'Nuevo' : 'Usado en buen estado'}${p.brand ? ` · ${p.brand}` : ''}\n` +
    `📦 ${p.stock > 0 ? 'Disponible' : 'Bajo pedido'}\n🚚 Entregas y envíos\n💬 Escríbeme por mensaje\n\n` +
    `#${(p.category || 'venta').replace(/\s+/g, '')} #${(s.business_name || '').replace(/\s+/g, '')}`;
  return { ml, fb };
}

async function productEditor(id) {
  const p = id ? await api(`/api/products/${id}`) : {
    name: '', sku: '', description: '', category: '', brand: '', condition: 'nuevo', cost: 0, price: 0,
    stock: 0, min_stock: 1, status: 'activo', supplier: '', notes: '', images: [], listings: [],
  };
  const cats = await api('/api/categories');
  const m = openModal({
    title: id ? p.name : 'Nuevo producto', wide: true,
    onClose: () => { if (location.hash.match(/#\/productos\/\d+/)) history.replaceState(null, '', '#/productos'); },
    body: `
      <div class="tabs">
        <button data-tab="datos" class="on">Datos</button>
        <button data-tab="fotos" ${id ? '' : 'disabled title="Guarda primero el producto"'}>Fotos (${p.images.length})</button>
        <button data-tab="canales" ${id ? '' : 'disabled'}>Publicaciones (${p.listings.length})</button>
        <button data-tab="texto" ${id ? '' : 'disabled'}>Texto para publicar</button>
      </div>
      <div data-pane="datos">
        <form id="pform" class="form-grid">
          <label class="field full">Nombre *<input name="name" required maxlength="200" value="${esc(p.name)}"></label>
          <label class="field">SKU<input name="sku" value="${esc(p.sku || '')}"></label>
          <label class="field">Categoría<input name="category" list="cat-list" value="${esc(p.category)}">
            <datalist id="cat-list">${cats.map(c => `<option>${esc(c)}</option>`).join('')}</datalist></label>
          <label class="field">Marca<input name="brand" value="${esc(p.brand)}"></label>
          <label class="field">Condición<select name="condition">${['nuevo', 'usado', 'reacondicionado'].map(c => `<option ${c === p.condition ? 'selected' : ''}>${c}</option>`).join('')}</select></label>
          <label class="field">Costo<input name="cost" type="number" step="0.01" min="0" value="${p.cost}"></label>
          <label class="field">Precio de venta<input name="price" type="number" step="0.01" min="0" value="${p.price}"></label>
          <label class="field">Stock<input name="stock" type="number" step="1" value="${p.stock}"></label>
          <label class="field">Stock mínimo (alerta)<input name="min_stock" type="number" step="1" value="${p.min_stock}"></label>
          <label class="field">Estado<select name="status">${Object.keys(PRODUCT_STATUS).map(s => `<option ${s === p.status ? 'selected' : ''}>${s}</option>`).join('')}</select></label>
          <label class="field">Proveedor<input name="supplier" value="${esc(p.supplier)}"></label>
          <div class="field full" id="margin-info"></div>
          <label class="field full">Descripción<textarea name="description" rows="5">${esc(p.description)}</textarea></label>
          <label class="field full">Notas internas<textarea name="notes" rows="2">${esc(p.notes)}</textarea></label>
        </form>
      </div>
      <div data-pane="fotos" class="hidden">
        <div class="dropzone" id="dz">Arrastra fotos aquí o <b>toca para elegir o tomar una foto</b><div class="small muted">Se optimizan automáticamente (máx. 1600 px) · la primera es la portada</div>
          <input type="file" id="file-in" accept="image/*" multiple hidden></div>
        <div class="gallery" id="gallery"></div>
      </div>
      <div data-pane="canales" class="hidden"><div id="listings"></div></div>
      <div data-pane="texto" class="hidden"><div id="texts"></div></div>`,
    foot: `${id ? '<button class="btn danger" id="p-del">Eliminar</button><button class="btn" id="p-dup">Duplicar</button><span class="spacer"></span>' : ''}
      <button class="btn" data-close>Cerrar</button><button class="btn primary" id="p-save">Guardar</button>`,
  });
  const el = m.el;
  $$('.tabs button', el).forEach(b => b.addEventListener('click', () => {
    if (b.disabled) return;
    $$('.tabs button', el).forEach(x => x.classList.toggle('on', x === b));
    $$('[data-pane]', el).forEach(x => x.classList.toggle('hidden', x.dataset.pane !== b.dataset.tab));
    $('#p-save', el).classList.toggle('hidden', b.dataset.tab !== 'datos');
  }));

  const form = $('#pform', el);
  const updateMargin = () => {
    const f = formData(form);
    const margin = (f.price || 0) - (f.cost || 0);
    const pct = f.price ? (margin / f.price * 100).toFixed(1) : 0;
    const fee = Number(state.settings.fee_mercadolibre_pct || 0);
    const mlNet = (f.price || 0) * (1 - fee / 100) - (f.cost || 0);
    $('#margin-info', el).innerHTML = `<div class="notice" style="margin:0">Margen: <b>${money(margin)}</b> (${pct}%) ·
      En Mercado Libre (comisión ${fee}%): <b>${money(mlNet)}</b> por unidad</div>`;
  };
  form.addEventListener('input', updateMargin);
  updateMargin();

  $('#p-save', el).addEventListener('click', e => busy(e.currentTarget, async () => {
    if (!form.reportValidity()) return;
    const data = formData(form);
    const saved = await api(id ? `/api/products/${id}` : '/api/products', { method: id ? 'PUT' : 'POST', body: data });
    toast('Producto guardado', 'ok');
    m.close();
    window.reloadProducts && window.reloadProducts();
    if (!id) productEditor(saved.id);
  }));
  if (!id) return;

  $('#p-del', el).addEventListener('click', async () => {
    if (!await confirmDialog(`¿Eliminar "${p.name}" y sus fotos? Las ventas registradas se conservan.`)) return;
    await api(`/api/products/${id}`, { method: 'DELETE' });
    toast('Producto eliminado'); m.close(); window.reloadProducts && window.reloadProducts();
  });
  $('#p-dup', el).addEventListener('click', async () => {
    const copy = await api(`/api/products/${id}/duplicate`, { method: 'POST' });
    m.close(); window.reloadProducts && window.reloadProducts(); productEditor(copy.id);
  });

  // ---- fotos
  let images = p.images;
  const drawGallery = () => {
    $('.tabs [data-tab=fotos]', el).textContent = `Fotos (${images.length})`;
    $('#gallery', el).innerHTML = images.map((img, i) => `
      <div class="g"><img src="${esc(img.url)}" alt="">
        ${i === 0 ? '<span class="badge info cover-tag">Portada</span>' : ''}
        <div class="acts">${i ? `<button data-cover="${img.id}">Portada</button>` : '<span></span>'}
          <a href="${esc(img.url)}" download><button type="button">⇩</button></a>
          <button data-del="${img.id}">✕</button></div></div>`).join('');
    $$('[data-del]', el).forEach(b => b.addEventListener('click', async () => {
      await api(`/api/images/${b.dataset.del}`, { method: 'DELETE' });
      images = images.filter(x => x.id !== Number(b.dataset.del)); drawGallery(); window.reloadProducts?.();
    }));
    $$('[data-cover]', el).forEach(b => b.addEventListener('click', async () => {
      await api(`/api/images/${b.dataset.cover}/cover`, { method: 'POST' });
      const cid = Number(b.dataset.cover);
      images = [images.find(x => x.id === cid), ...images.filter(x => x.id !== cid)]; drawGallery(); window.reloadProducts?.();
    }));
  };
  const upload = async files => {
    if (!files.length) return;
    const dzEl = $('#dz', el), label = dzEl.firstChild.textContent;
    dzEl.classList.add('over');
    let n = 0;
    try {
      // Una foto por petición y comprimida: Vercel acepta como máximo 4.5 MB por petición.
      for (const f of files) {
        dzEl.firstChild.textContent = `Subiendo ${++n} de ${files.length}… `;
        const fd = new FormData();
        fd.append('files', await compressImage(f));
        images = await api(`/api/products/${id}/images`, { method: 'POST', form: fd });
        drawGallery();
      }
      toast(files.length > 1 ? `${files.length} fotos subidas` : 'Foto subida', 'ok');
      window.reloadProducts?.();
    } catch (e) { toast(e.message, 'error'); }
    finally { dzEl.classList.remove('over'); dzEl.firstChild.textContent = label; }
  };
  const dz = $('#dz', el), fin = $('#file-in', el);
  dz.addEventListener('click', () => fin.click());
  fin.addEventListener('change', () => { const list = [...fin.files]; fin.value = ''; upload(list); });
  dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('over'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('over'));
  dz.addEventListener('drop', e => { e.preventDefault(); dz.classList.remove('over'); upload([...e.dataTransfer.files]); });
  drawGallery();

  // ---- publicaciones por canal
  const drawListings = async () => {
    const prod = await api(`/api/products/${id}`);
    $('.tabs [data-tab=canales]', el).textContent = `Publicaciones (${prod.listings.length})`;
    $('#listings', el).innerHTML = `
      <p class="muted small" style="margin-top:0">Registra dónde está publicado este producto y a qué precio. En Mercado Libre, con la cuenta conectada,
      puedes enviar precio y stock con “Sincronizar”.</p>
      ${prod.listings.length ? `<div class="table-wrap"><table><thead><tr><th>Canal</th><th>ID / enlace</th><th class="num">Precio</th><th>Estado</th><th></th></tr></thead><tbody>
      ${prod.listings.map(l => `<tr><td>${chan(l.channel)}</td>
        <td>${l.url ? `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.external_id || 'Abrir')} ↗</a>` : esc(l.external_id || '—')}</td>
        <td class="num">${money(l.price)}</td><td>${badge(l.status, l.status === 'activa' ? 'good' : '')}</td>
        <td class="right nowrap">${l.channel === 'mercadolibre' && l.external_id ? `<button class="btn sm" data-push="${l.id}">⇪ Sincronizar</button>` : ''}
          <button class="btn sm" data-edit-l="${l.id}">Editar</button><button class="btn sm danger" data-del-l="${l.id}">✕</button></td></tr>`).join('')}
      </tbody></table></div>` : '<div class="empty">Aún no registras publicaciones de este producto.</div>'}
      <div style="margin-top:12px"><button class="btn primary" id="add-listing">+ Agregar publicación</button></div>`;
    $('#add-listing', el).addEventListener('click', () => listingEditor({ product_id: id, channel: 'mercadolibre', price: prod.price, title: prod.name, status: 'activa' }, drawListings));
    $$('[data-edit-l]', el).forEach(b => b.addEventListener('click', () => listingEditor(prod.listings.find(l => l.id === Number(b.dataset.editL)), drawListings)));
    $$('[data-del-l]', el).forEach(b => b.addEventListener('click', async () => {
      await api(`/api/listings/${b.dataset.delL}`, { method: 'DELETE' }); drawListings();
    }));
    $$('[data-push]', el).forEach(b => b.addEventListener('click', () => busy(b, async () => {
      await api(`/api/listings/${b.dataset.push}/push`, { method: 'POST' }); toast('Precio y stock enviados a Mercado Libre', 'ok');
    })));
  };
  drawListings();

  // ---- textos
  const t = listingTexts(p);
  $('#texts', el).innerHTML = `
    <p class="muted small" style="margin-top:0">Facebook Marketplace no tiene API pública para publicar: copia este texto y descarga las fotos desde la pestaña Fotos.
    Para catálogos de Meta Commerce usa la exportación en Configuración.</p>
    <div class="grid cols-2e">
      <div><div class="card-head"><h2>${chan('marketplace')}</h2><button class="btn sm" data-copy="fb">Copiar</button></div><div class="copybox" id="tx-fb">${esc(t.fb)}</div></div>
      <div><div class="card-head"><h2>${chan('mercadolibre')}</h2><button class="btn sm" data-copy="ml">Copiar</button></div><div class="copybox" id="tx-ml">${esc(t.ml)}</div>
        <div class="small muted" style="margin-top:6px">Título ML (máx. 60): ${p.name.length > 60 ? badge(`${p.name.length} caracteres — recórtalo`, 'warn') : badge(`${p.name.length} caracteres`, 'good')}</div></div>
    </div>`;
  $$('[data-copy]', el).forEach(b => b.addEventListener('click', async () => {
    const text = $(`#tx-${b.dataset.copy}`, el).textContent;
    try { await navigator.clipboard.writeText(text); toast('Copiado al portapapeles', 'ok'); }
    catch { toast('No se pudo copiar; selecciona el texto manualmente', 'error'); }
  }));
}

function listingEditor(l, onSaved) {
  const m = openModal({
    title: l.id ? 'Editar publicación' : 'Nueva publicación',
    body: `<form id="lform" class="form-grid">
      <label class="field">Canal<select name="channel">${Object.entries(CH).map(([k, v]) => `<option value="${k}" ${k === l.channel ? 'selected' : ''}>${v.label}</option>`).join('')}</select></label>
      <label class="field">ID externo<input name="external_id" placeholder="MLM123456789" value="${esc(l.external_id || '')}"></label>
      <label class="field full">Título<input name="title" value="${esc(l.title || '')}"></label>
      <label class="field full">URL<input name="url" type="url" placeholder="https://…" value="${esc(l.url || '')}"></label>
      <label class="field">Precio publicado<input name="price" type="number" step="0.01" value="${l.price ?? 0}"></label>
      <label class="field">Estado<select name="status">${['activa', 'pausada', 'cerrada'].map(s => `<option ${s === l.status ? 'selected' : ''}>${s}</option>`).join('')}</select></label>
      <label class="field">Visitas<input name="views" type="number" value="${l.views || 0}"></label>
    </form>`,
    foot: '<button class="btn" data-close>Cancelar</button><button class="btn primary" id="l-save">Guardar</button>',
  });
  $('#l-save', m.el).addEventListener('click', e => busy(e.currentTarget, async () => {
    const data = { ...formData($('#lform', m.el)), product_id: l.product_id };
    await api(l.id ? `/api/listings/${l.id}` : '/api/listings', { method: l.id ? 'PUT' : 'POST', body: data });
    m.close(); onSaved && onSaved();
  }));
}
window.productEditor = productEditor;

// ======================================================================= VENTAS
route('ventas', 'Ventas', async (rest, qs) => {
  setActions(`<a class="btn" id="sales-csv" href="/api/export/sales.csv">⇩ CSV</a><button class="btn primary" id="new-sale">+ Venta</button>`);
  $('#new-sale').addEventListener('click', () => saleEditor(null));
  const d30 = new Date(Date.now() - 29 * 864e5).toISOString().slice(0, 10);
  view.innerHTML = `
    <div class="filters">
      <input type="search" id="sf-q" placeholder="Buscar cliente, artículo, ID…">
      <input type="date" id="sf-from" value="${qs.get('from') || d30}"> <input type="date" id="sf-to" value="${qs.get('to') || today()}">
      <select id="sf-ch"><option value="">Todos los canales</option>${Object.entries(CH).map(([k, v]) => `<option value="${k}">${v.label}</option>`).join('')}</select>
      <select id="sf-st"><option value="">Todos los estados</option>${Object.keys(SALE_STATUS).map(s => `<option ${qs.get('status') === s ? 'selected' : ''}>${s}</option>`).join('')}</select>
    </div>
    <div class="grid kpis" id="sales-sum" style="margin-bottom:16px"></div>
    <div class="card table-wrap" id="slist"></div>`;

  const load = async () => {
    const params = new URLSearchParams({ q: $('#sf-q').value, channel: $('#sf-ch').value, status: $('#sf-st').value });
    if ($('#sf-from').value) params.set('date_from', $('#sf-from').value);
    if ($('#sf-to').value) params.set('date_to', $('#sf-to').value);
    $('#sales-csv').href = '/api/export/sales.csv?' + new URLSearchParams({ date_from: $('#sf-from').value, date_to: $('#sf-to').value });
    const sales = await api('/api/sales?' + params);
    const valid = sales.filter(s => s.status !== 'cancelado');
    const tot = valid.reduce((a, s) => a + s.total, 0), prof = valid.reduce((a, s) => a + s.profit, 0);
    $('#sales-sum').innerHTML = `
      <div class="card kpi"><div class="label">Ventas</div><div class="value">${money(tot)}</div></div>
      <div class="card kpi"><div class="label">Utilidad bruta</div><div class="value">${money(prof)}</div><div class="delta">${tot ? (prof / tot * 100).toFixed(1) : 0}% de margen</div></div>
      <div class="card kpi"><div class="label">Pedidos</div><div class="value">${valid.length}</div><div class="delta">${sales.length - valid.length} cancelados</div></div>`;
    $('#slist').innerHTML = sales.length ? `<table><thead><tr><th>#</th><th>Fecha</th><th>Canal</th><th>Cliente</th><th>Artículos</th>
      <th class="num">Total</th><th class="num">Comisión+envío</th><th class="num">Utilidad</th><th>Estado</th><th></th></tr></thead><tbody>
      ${sales.map(s => `<tr><td class="muted">${s.id}</td><td class="nowrap">${fmtDate(s.date)}</td><td>${chan(s.channel)}</td>
        <td>${esc(s.customer_name || '—')}</td>
        <td><div class="ellipsis" style="max-width:280px">${esc(s.items.map(i => `${i.quantity}× ${i.description}`).join(', '))}</div>${s.external_id ? `<div class="small muted">${esc(s.external_id)}</div>` : ''}</td>
        <td class="num"><b>${money(s.total)}</b></td><td class="num muted">${money(s.commission + s.shipping_cost)}</td>
        <td class="num" style="color:var(${s.profit < 0 ? '--bad' : '--text'})">${money(s.profit)}</td>
        <td><select class="st-sel" data-id="${s.id}" style="width:auto;padding:3px 6px">${Object.keys(SALE_STATUS).map(x => `<option ${x === s.status ? 'selected' : ''}>${x}</option>`).join('')}</select></td>
        <td class="right nowrap"><button class="btn sm" data-edit="${s.id}">Editar</button> <button class="btn sm danger" data-del="${s.id}">✕</button></td></tr>`).join('')}
      </tbody></table>` : '<div class="empty"><div class="big">$</div>No hay ventas con estos filtros.</div>';
    $$('.st-sel').forEach(sel => sel.addEventListener('change', async () => {
      try { await api(`/api/sales/${sel.dataset.id}/status`, { method: 'PATCH', body: { status: sel.value } }); toast('Estado actualizado', 'ok'); load(); }
      catch (e) { toast(e.message, 'error'); }
    }));
    $$('[data-edit]').forEach(b => b.addEventListener('click', () => saleEditor(sales.find(s => s.id === Number(b.dataset.edit)))));
    $$('[data-del]').forEach(b => b.addEventListener('click', async () => {
      if (!await confirmDialog('¿Eliminar esta venta? El stock se devolverá al inventario.')) return;
      await api(`/api/sales/${b.dataset.del}`, { method: 'DELETE' }); toast('Venta eliminada'); load();
    }));
  };
  window.reloadSales = load;
  let t;
  $('#sf-q').addEventListener('input', () => { clearTimeout(t); t = setTimeout(load, 250); });
  ['#sf-from', '#sf-to', '#sf-ch', '#sf-st'].forEach(s => $(s).addEventListener('change', load));
  await load();
  if (qs.get('nueva')) { history.replaceState(null, '', '#/ventas'); saleEditor(null); }
});

async function saleEditor(sale) {
  const [products, customers] = await Promise.all([api('/api/products'), api('/api/customers')]);
  const s = sale || { date: today(), channel: 'marketplace', status: 'pagado', items: [{ product_id: null, description: '', quantity: 1, unit_price: 0 }],
    shipping_cost: 0, commission: null, notes: '', customer_name: '', external_id: '' };
  const prodOpts = sel => `<option value="">— Artículo libre —</option>${products.map(p =>
    `<option value="${p.id}" ${p.id === sel ? 'selected' : ''}>${esc(p.name)} (${p.stock} uds · ${money(p.price)})</option>`).join('')}`;
  const m = openModal({
    title: sale ? `Editar venta #${sale.id}` : 'Registrar venta', wide: true,
    body: `<form id="sform"><div class="form-grid">
      <label class="field">Fecha<input type="date" name="date" value="${s.date}" required></label>
      <label class="field">Canal<select name="channel">${Object.entries(CH).map(([k, v]) => `<option value="${k}" ${k === s.channel ? 'selected' : ''}>${v.label}</option>`).join('')}</select></label>
      <label class="field">Estado<select name="status">${Object.keys(SALE_STATUS).map(x => `<option ${x === s.status ? 'selected' : ''}>${x}</option>`).join('')}</select></label>
      <label class="field">Cliente<input name="customer_name" list="cust-list" placeholder="Nombre (se crea si no existe)" value="${esc(s.customer_name || '')}">
        <datalist id="cust-list">${customers.map(c => `<option>${esc(c.name)}</option>`).join('')}</datalist></label>
      <label class="field">ID de pedido externo<input name="external_id" value="${esc(s.external_id || '')}"></label>
      </div>
      <h2 style="margin:18px 0 6px">Artículos</h2>
      <div class="table-wrap"><table class="items-table"><thead><tr><th style="min-width:220px">Producto</th><th>Descripción</th><th style="width:80px">Cant.</th><th style="width:120px">Precio unit.</th><th class="num">Subtotal</th><th></th></tr></thead>
      <tbody id="items"></tbody></table></div>
      <button type="button" class="btn sm" id="add-item" style="margin-top:8px">+ Artículo</button>
      <div class="form-grid" style="margin-top:16px">
        <label class="field">Costo de envío (lo pagas tú)<input type="number" step="0.01" min="0" name="shipping_cost" value="${s.shipping_cost}"></label>
        <label class="field">Comisión del canal<input type="number" step="0.01" min="0" name="commission" placeholder="Automática" value="${s.commission ?? ''}"></label>
        <label class="field full">Notas<textarea name="notes" rows="2">${esc(s.notes)}</textarea></label>
      </div>
      <div class="notice" id="sale-sum" style="margin-top:12px"></div></form>`,
    foot: '<button class="btn" data-close>Cancelar</button><button class="btn primary" id="s-save">Guardar venta</button>',
  });
  const el = m.el;
  const tbody = $('#items', el);
  const addRow = it => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><select class="it-p">${prodOpts(it.product_id)}</select></td>
      <td><input class="it-d" value="${esc(it.description || '')}" placeholder="Descripción"></td>
      <td><input class="it-q" type="number" min="1" step="1" value="${it.quantity}"></td>
      <td><input class="it-u" type="number" min="0" step="0.01" value="${it.unit_price}"></td>
      <td class="num it-sub"></td><td><button type="button" class="icon-btn it-x" aria-label="Quitar">✕</button></td>`;
    $('.it-p', tr).addEventListener('change', e => {
      const p = products.find(x => x.id === Number(e.target.value));
      if (p) { $('.it-u', tr).value = p.price; $('.it-d', tr).value = p.name; }
      recalc();
    });
    $('.it-x', tr).addEventListener('click', () => { if (tbody.children.length > 1) { tr.remove(); recalc(); } });
    tbody.appendChild(tr);
  };
  const rows = () => $$('tr', tbody).map(tr => ({
    product_id: $('.it-p', tr).value ? Number($('.it-p', tr).value) : null,
    description: $('.it-d', tr).value, quantity: Number($('.it-q', tr).value || 1), unit_price: Number($('.it-u', tr).value || 0),
  }));
  const recalc = () => {
    let total = 0, cost = 0;
    $$('tr', tbody).forEach((tr, i) => {
      const r = rows()[i];
      const sub = r.quantity * r.unit_price;
      total += sub;
      const p = products.find(x => x.id === r.product_id);
      cost += r.quantity * (p ? p.cost : 0);
      $('.it-sub', tr).textContent = money(sub);
    });
    const f = formData($('#sform', el));
    const pct = Number(state.settings[`fee_${f.channel}_pct`] || 0);
    const comm = f.commission ?? total * pct / 100;
    const profit = total - cost - comm - (f.shipping_cost || 0);
    $('#sale-sum', el).innerHTML = `Total <b>${money(total)}</b> · costo ${money(cost)} · comisión ${money(comm)}${f.commission === null ? ` <span class="muted">(auto ${pct}%)</span>` : ''}
      · envío ${money(f.shipping_cost || 0)} → utilidad <b style="color:var(${profit < 0 ? '--bad' : '--good'})">${money(profit)}</b>`;
  };
  s.items.forEach(addRow);
  $('#add-item', el).addEventListener('click', () => { addRow({ product_id: null, quantity: 1, unit_price: 0 }); recalc(); });
  $('#sform', el).addEventListener('input', recalc);
  $('#sform', el).addEventListener('change', recalc);
  recalc();

  $('#s-save', el).addEventListener('click', e => busy(e.currentTarget, async () => {
    const f = formData($('#sform', el));
    const body = { ...f, items: rows() };
    if (sale) {
      const keepCustomer = sale.customer_id && f.customer_name === sale.customer_name;
      if (keepCustomer) body.customer_id = sale.customer_id;
    }
    await api(sale ? `/api/sales/${sale.id}` : '/api/sales', { method: sale ? 'PUT' : 'POST', body });
    toast('Venta guardada — inventario actualizado', 'ok');
    m.close();
    window.reloadSales ? window.reloadSales() : render();
  }));
}

// ======================================================================= CLIENTES
route('clientes', 'Clientes', async () => {
  setActions('<a class="btn" href="/api/export/customers.csv">⇩ CSV</a><button class="btn primary" id="new-c">+ Cliente</button>');
  $('#new-c').addEventListener('click', () => customerEditor({}));
  view.innerHTML = `<div class="filters"><input type="search" id="cf-q" placeholder="Buscar nombre, teléfono, ciudad…"></div><div class="card table-wrap" id="clist"></div>`;
  const load = async () => {
    const list = await api('/api/customers?q=' + encodeURIComponent($('#cf-q').value));
    $('#clist').innerHTML = list.length ? `<table><thead><tr><th>Nombre</th><th>Teléfono</th><th>Email</th><th>Ciudad</th><th>Canal</th>
      <th class="num">Pedidos</th><th class="num">Total comprado</th><th></th></tr></thead><tbody>
      ${list.map(c => `<tr><td><b>${esc(c.name)}</b>${c.notes ? `<div class="small muted ellipsis" style="max-width:240px">${esc(c.notes)}</div>` : ''}</td>
        <td>${c.phone ? `<a href="https://wa.me/${esc(c.phone.replace(/\D/g, ''))}" target="_blank" rel="noopener">${esc(c.phone)}</a>` : '—'}</td>
        <td>${esc(c.email || '—')}</td><td>${esc(c.city || '—')}</td><td>${c.channel ? chan(c.channel) : '—'}</td>
        <td class="num">${c.orders}</td><td class="num">${money(c.total_spent)}</td>
        <td class="right nowrap"><button class="btn sm" data-e="${c.id}">Editar</button> <button class="btn sm danger" data-d="${c.id}">✕</button></td></tr>`).join('')}
      </tbody></table>` : '<div class="empty"><div class="big">☺</div>Sin clientes. Se crean automáticamente al registrar ventas.</div>';
    $$('[data-e]').forEach(b => b.addEventListener('click', () => customerEditor(list.find(c => c.id === Number(b.dataset.e)))));
    $$('[data-d]').forEach(b => b.addEventListener('click', async () => {
      if (!await confirmDialog('¿Eliminar cliente? Sus ventas se conservan sin cliente.')) return;
      await api(`/api/customers/${b.dataset.d}`, { method: 'DELETE' }); load();
    }));
  };
  window.reloadCustomers = load;
  let t; $('#cf-q').addEventListener('input', () => { clearTimeout(t); t = setTimeout(load, 250); });
  await load();
});

function customerEditor(c) {
  const m = openModal({
    title: c.id ? 'Editar cliente' : 'Nuevo cliente',
    body: `<form id="cform" class="form-grid">
      <label class="field full">Nombre *<input name="name" required value="${esc(c.name || '')}"></label>
      <label class="field">Teléfono / WhatsApp<input name="phone" value="${esc(c.phone || '')}"></label>
      <label class="field">Email<input name="email" type="email" value="${esc(c.email || '')}"></label>
      <label class="field">Ciudad<input name="city" value="${esc(c.city || '')}"></label>
      <label class="field">Canal<select name="channel"><option value="">—</option>${Object.entries(CH).map(([k, v]) => `<option value="${k}" ${k === c.channel ? 'selected' : ''}>${v.label}</option>`).join('')}</select></label>
      <label class="field full">Notas<textarea name="notes" rows="3">${esc(c.notes || '')}</textarea></label></form>`,
    foot: '<button class="btn" data-close>Cancelar</button><button class="btn primary" id="c-save">Guardar</button>',
  });
  $('#c-save', m.el).addEventListener('click', e => busy(e.currentTarget, async () => {
    const form = $('#cform', m.el); if (!form.reportValidity()) return;
    await api(c.id ? `/api/customers/${c.id}` : '/api/customers', { method: c.id ? 'PUT' : 'POST', body: formData(form) });
    m.close(); window.reloadCustomers?.();
  }));
}

// ======================================================================= GASTOS
route('gastos', 'Gastos', async () => {
  setActions('<a class="btn" href="/api/export/expenses.csv">⇩ CSV</a><button class="btn primary" id="new-e">+ Gasto</button>');
  $('#new-e').addEventListener('click', () => expenseEditor({}));
  const load = async () => {
    const list = await api('/api/expenses');
    const byCat = {};
    list.forEach(e => { byCat[e.category] = (byCat[e.category] || 0) + e.amount; });
    const month = today().slice(0, 7);
    const monthTotal = list.filter(e => e.date.startsWith(month)).reduce((a, e) => a + e.amount, 0);
    view.innerHTML = `<div class="grid cols-2">
      <div class="card table-wrap">${list.length ? `<table><thead><tr><th>Fecha</th><th>Categoría</th><th>Descripción</th><th class="num">Monto</th><th></th></tr></thead><tbody>
        ${list.map(e => `<tr><td class="nowrap">${fmtDate(e.date)}</td><td>${badge(e.category)}</td><td>${esc(e.description)}</td>
        <td class="num">${money(e.amount)}</td><td class="right nowrap"><button class="btn sm" data-e="${e.id}">Editar</button> <button class="btn sm danger" data-d="${e.id}">✕</button></td></tr>`).join('')}
        </tbody></table>` : '<div class="empty"><div class="big">−</div>Registra publicidad, empaques, envíos, renta… para ver tu utilidad real.</div>'}</div>
      <div class="stack"><div class="card kpi"><div class="label">Gastos de este mes</div><div class="value">${money(monthTotal)}</div></div>
        <div class="card"><h2 style="margin-bottom:12px">Por categoría (total)</h2><div class="bar-list">${Object.entries(byCat).sort((a, b) => b[1] - a[1]).map(([k, v]) => `
          <div class="bar-item"><div class="top"><span>${esc(k)}</span><span class="num">${money(v)}</span></div>
          <div class="bar-track"><div class="bar-fill" style="width:${(v / Math.max(...Object.values(byCat)) * 100).toFixed(1)}%"></div></div></div>`).join('') || '<div class="muted">—</div>'}</div></div></div>
    </div>`;
    $$('[data-e]').forEach(b => b.addEventListener('click', () => expenseEditor(list.find(x => x.id === Number(b.dataset.e)))));
    $$('[data-d]').forEach(b => b.addEventListener('click', async () => {
      if (!await confirmDialog('¿Eliminar gasto?')) return;
      await api(`/api/expenses/${b.dataset.d}`, { method: 'DELETE' }); load();
    }));
  };
  window.reloadExpenses = load;
  await load();
});

function expenseEditor(e) {
  const cats = ['publicidad', 'empaque', 'envíos', 'mercancía', 'renta', 'servicios', 'comisiones', 'general'];
  const m = openModal({
    title: e.id ? 'Editar gasto' : 'Nuevo gasto',
    body: `<form id="eform" class="form-grid">
      <label class="field">Fecha<input type="date" name="date" value="${e.date || today()}"></label>
      <label class="field">Categoría<input name="category" list="ecats" value="${esc(e.category || 'general')}"><datalist id="ecats">${cats.map(c => `<option>${c}</option>`).join('')}</datalist></label>
      <label class="field">Monto *<input type="number" name="amount" min="0" step="0.01" required value="${e.amount ?? ''}"></label>
      <label class="field full">Descripción<input name="description" value="${esc(e.description || '')}"></label></form>`,
    foot: '<button class="btn" data-close>Cancelar</button><button class="btn primary" id="e-save">Guardar</button>',
  });
  $('#e-save', m.el).addEventListener('click', ev => busy(ev.currentTarget, async () => {
    const form = $('#eform', m.el); if (!form.reportValidity()) return;
    await api(e.id ? `/api/expenses/${e.id}` : '/api/expenses', { method: e.id ? 'PUT' : 'POST', body: formData(form) });
    m.close(); window.reloadExpenses?.();
  }));
}

// ======================================================================= COMPETENCIA
route('competencia', 'Precios de la competencia', async () => {
  setActions('<button class="btn" id="run-all">↻ Revisar pendientes</button><button class="btn primary" id="new-w">+ Vigilar URL</button>');
  $('#new-w').addEventListener('click', () => watchEditor({ interval_hours: 12, active: true }));
  $('#run-all').addEventListener('click', e => busy(e.currentTarget, async () => {
    const r = await api('/api/market/run-due', { method: 'POST' });
    toast(`Revisadas ${r.watches} URLs y ${r.searches} búsquedas`, 'ok'); window.reloadWatches();
  }));
  const load = async () => {
    const list = await api('/api/watches');
    view.innerHTML = `
      <div class="notice">Pega la URL de un producto de cualquier tienda (Mercado Libre, Amazon, Liverpool, Shopify, etc.). El sistema detecta el precio
      automáticamente (datos estructurados / meta tags) y lo revisa cada X horas, guardando el historial. Si no lo detecta, indica un selector CSS.</div>
      <div class="card table-wrap">${list.length ? `<table><thead><tr><th></th><th>Producto competidor</th><th>Comparar con</th>
        <th class="num">Su precio</th><th class="num">Cambio</th><th class="num">Mi precio</th><th class="num">Diferencia</th><th>Revisado</th><th></th></tr></thead><tbody>
        ${list.map(w => {
          const ch = w.prev_price != null && w.last_price != null ? w.last_price - w.prev_price : null;
          const diff = w.product_price != null && w.last_price != null ? w.product_price - w.last_price : null;
          return `<tr><td>${thumb(w.last_image)}</td>
          <td><a href="${esc(w.url)}" target="_blank" rel="noopener"><b class="ellipsis" style="display:block;max-width:300px">${esc(w.name || w.last_title || w.url)}</b></a>
            <div class="small muted ellipsis" style="max-width:300px">${esc(new URL(w.url).hostname)}${w.active ? '' : ' · pausada'}</div>
            ${w.last_error ? `<div class="small" style="color:var(--bad);max-width:320px">⚠ ${esc(w.last_error)}</div>` : ''}</td>
          <td>${esc(w.product_name || '—')}</td>
          <td class="num"><b>${money(w.last_price)}</b>${w.min_price != null && w.min_price !== w.max_price ? `<div class="small muted">${money(w.min_price)}–${money(w.max_price)}</div>` : ''}</td>
          <td class="num">${ch ? badge(`${ch < 0 ? '▼' : '▲'} ${money(Math.abs(ch))}`, ch < 0 ? 'bad' : 'good') : '<span class="muted">—</span>'}</td>
          <td class="num">${money(w.product_price)}</td>
          <td class="num">${diff == null ? '—' : diff > 0 ? badge(`tú +${money(diff)}`, 'warn') : badge(diff === 0 ? 'igual' : `tú ${money(diff)}`, 'good')}</td>
          <td class="small nowrap" title="${fmtDateTime(w.last_checked)}">${ago(w.last_checked)}<div class="muted">cada ${w.interval_hours} h</div></td>
          <td class="right nowrap"><button class="btn sm" data-chk="${w.id}">↻</button> <button class="btn sm" data-h="${w.id}">Historial</button>
            <button class="btn sm" data-e="${w.id}">Editar</button> <button class="btn sm danger" data-d="${w.id}">✕</button></td></tr>`;
        }).join('')}</tbody></table>` : '<div class="empty"><div class="big">◎</div>Aún no vigilas ningún precio.</div>'}</div>`;
    $$('[data-chk]').forEach(b => b.addEventListener('click', () => busy(b, async () => {
      const w = await api(`/api/watches/${b.dataset.chk}/check`, { method: 'POST' });
      toast(w.last_error ? `Error: ${w.last_error}` : `Precio actual: ${money(w.last_price)}`, w.last_error ? 'error' : 'ok'); load();
    })));
    $$('[data-e]').forEach(b => b.addEventListener('click', () => watchEditor(list.find(w => w.id === Number(b.dataset.e)))));
    $$('[data-h]').forEach(b => b.addEventListener('click', () => watchHistory(list.find(w => w.id === Number(b.dataset.h)))));
    $$('[data-d]').forEach(b => b.addEventListener('click', async () => {
      if (!await confirmDialog('¿Dejar de vigilar esta URL y borrar su historial?')) return;
      await api(`/api/watches/${b.dataset.d}`, { method: 'DELETE' }); load();
    }));
  };
  window.reloadWatches = load;
  await load();
});

async function watchEditor(w) {
  const products = await api('/api/products');
  const m = openModal({
    title: w.id ? 'Editar vigilancia' : 'Vigilar precio de un competidor',
    body: `<form id="wform" class="form-grid">
      <label class="field full">URL del producto *<input name="url" type="url" required placeholder="https://articulo.mercadolibre.com.mx/MLM-…" value="${esc(w.url || '')}"></label>
      <label class="field full">Nombre (opcional)<input name="name" placeholder="Se toma del título de la página" value="${esc(w.name || '')}"></label>
      <label class="field">Comparar con mi producto<select name="product_id"><option value="">—</option>${products.map(p => `<option value="${p.id}" ${p.id === w.product_id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></label>
      <label class="field">Revisar cada (horas)<input name="interval_hours" type="number" min="0.25" step="0.25" value="${w.interval_hours}"></label>
      <label class="field full">Selector CSS del precio (opcional)<input name="css_selector" placeholder="ej. .price-tag-fraction, #precio" value="${esc(w.css_selector || '')}"></label>
      <label class="row small"><input type="checkbox" name="active" style="width:auto" ${w.active ? 'checked' : ''}> Revisar automáticamente</label>
      <div class="full" id="w-test"></div></form>`,
    foot: '<button class="btn" id="w-try">Probar</button><span class="spacer"></span><button class="btn" data-close>Cancelar</button><button class="btn primary" id="w-save">Guardar</button>',
  });
  const read = () => { const f = formData($('#wform', m.el)); f.product_id = f.product_id ? Number(f.product_id) : null; return f; };
  $('#w-try', m.el).addEventListener('click', e => busy(e.currentTarget, async () => {
    const box = $('#w-test', m.el);
    try {
      const r = await api('/api/scrape/test', { method: 'POST', body: read() });
      box.innerHTML = `<div class="notice" style="margin:0"><div class="row">${thumb(r.image)}<div><b>${esc(r.title)}</b><br>Precio detectado: <b>${money(r.price)}</b> ${r.currency ? esc(r.currency) : ''} <span class="muted small">(método: ${esc(r.method)})</span></div></div></div>`;
    } catch (err) { box.innerHTML = `<div class="notice bad" style="margin:0">${esc(err.message)}</div>`; }
  }));
  $('#w-save', m.el).addEventListener('click', e => busy(e.currentTarget, async () => {
    const form = $('#wform', m.el); if (!form.reportValidity()) return;
    const saved = await api(w.id ? `/api/watches/${w.id}` : '/api/watches', { method: w.id ? 'PUT' : 'POST', body: read() });
    if (saved.last_error) toast(`Guardado, pero: ${saved.last_error}`, 'error'); else toast('Guardado', 'ok');
    m.close(); window.reloadWatches?.();
  }));
}

async function watchHistory(w) {
  const hist = await api(`/api/watches/${w.id}/history`);
  const m = openModal({
    title: w.name || w.last_title || 'Historial', wide: true,
    body: hist.length ? `<div class="card-head"><div class="legend"><span><i class="dot" style="background:var(--s1)"></i>Precio competidor</span>
      ${w.product_price != null ? '<span><i class="dot" style="background:var(--muted)"></i>Mi precio</span>' : ''}</div><span class="small muted">${hist.length} registros</span></div>
      <div class="chart-box"><canvas id="h-chart"></canvas></div>` : '<div class="empty">Sin registros todavía.</div>',
    onClose: () => {},
  });
  if (!hist.length) return;
  const ds = [{ label: 'Competidor', data: hist.map(h => h.price), borderColor: cssVar('--s1'), backgroundColor: cssVar('--s1'),
    borderWidth: 2, pointRadius: hist.length > 40 ? 0 : 3, pointHoverRadius: 5, stepped: 'before' }];
  if (w.product_price != null) ds.push({ label: 'Mi precio', data: hist.map(() => w.product_price), borderColor: cssVar('--muted'),
    borderDash: [5, 4], borderWidth: 1.5, pointRadius: 0 });
  const c = new Chart($('#h-chart', m.el), {
    type: 'line', data: { labels: hist.map(h => fmtDateTime(h.checked_at)), datasets: ds },
    options: baseChartOptions({ scales: { ...baseChartOptions().scales, y: { ...baseChartOptions().scales.y, beginAtZero: false } } }),
  });
  const obs = new MutationObserver(() => { if (!document.body.contains(m.el)) { c.destroy(); obs.disconnect(); } });
  obs.observe($('#modal-root'), { childList: true });
}

// ======================================================================= MERCADO
route('mercado', 'Búsquedas de mercado y novedades', async (rest, qs) => {
  setActions('<button class="btn primary" id="new-s">+ Nueva búsqueda</button>');
  $('#new-s').addEventListener('click', () => searchEditor({ site: state.settings.ml_site || 'MLM', interval_hours: 24, active: true }));
  const [searches, fresh] = await Promise.all([api('/api/searches'), api('/api/market/new-products')]);
  const selected = Number(qs.get('id')) || searches[0]?.id;
  view.innerHTML = `
    <div class="notice">Rastrea palabras clave en Mercado Libre: ve rango de precios, vendedores y detecta <b>productos nuevos</b> que aparecen entre revisiones.
    Funciona mejor con tu cuenta de Mercado Libre conectada (Configuración); si no, intenta leer la página pública de resultados.</div>
    ${searches.length ? `<div class="grid kpis" style="margin-bottom:16px">${searches.map(s => `
      <a class="card" href="#/mercado?id=${s.id}" style="color:inherit;text-decoration:none;${s.id === selected ? 'border-color:var(--accent)' : ''}">
        <div class="row"><b class="ellipsis grow" style="flex:1">“${esc(s.query)}”</b>${s.new_count ? badge(`${s.new_count} nuevos`, 'info') : ''}</div>
        <div class="kpi"><div class="value" style="font-size:20px">${s.avg_price != null ? money(s.avg_price) : '—'}</div>
        <div class="delta">${s.result_count} resultados · ${money(s.min_price)} – ${money(s.max_price)}</div></div>
        <div class="small muted">${esc(s.site)} · ${ago(s.last_run)}${s.last_source ? ` · vía ${s.last_source}` : ''}</div>
        ${s.last_error ? `<div class="small" style="color:var(--bad)">⚠ ${esc(s.last_error.slice(0, 140))}</div>` : ''}
      </a>`).join('')}</div>` : ''}
    <div class="grid cols-2">
      <div class="card" id="results">${searches.length ? '' : '<div class="empty"><div class="big">⌕</div>Crea una búsqueda, p. ej. “audífonos bluetooth”.</div>'}</div>
      <div class="card"><div class="card-head"><h2>✦ Nuevos en las últimas 48 h</h2></div>
        ${fresh.length ? `<div class="list">${fresh.slice(0, 25).map(r => `<a class="list-item" href="${esc(r.url)}" target="_blank" rel="noopener" style="color:inherit">
          ${thumb(r.thumbnail)}<div class="grow"><div class="ellipsis">${esc(r.title)}</div><div class="small muted">“${esc(r.query)}” · ${esc(r.seller || '')}</div></div>
          <b class="num">${money(r.price)}</b></a>`).join('')}</div>`
          : '<div class="empty small">Cuando una búsqueda detecte publicaciones que no existían en la revisión anterior, aparecerán aquí.</div>'}</div>
    </div>`;
  if (!selected) return;
  const s = searches.find(x => x.id === selected);
  const box = $('#results');
  let sort = 'price', onlyNew = false;
  const loadResults = async () => {
    const res = await api(`/api/searches/${s.id}/results?sort=${sort}&only_new=${onlyNew}`);
    box.innerHTML = `<div class="card-head"><h2>Resultados: “${esc(s.query)}”</h2>
        <div class="row"><select id="r-sort" style="width:auto"><option value="price">Menor precio</option><option value="recent">Más recientes</option><option value="sold">Más vendidos</option></select>
        <label class="row small"><input type="checkbox" id="r-new" style="width:auto" ${onlyNew ? 'checked' : ''}> Solo nuevos</label>
        <button class="btn sm" id="r-run">↻ Ejecutar</button><button class="btn sm" id="r-edit">Editar</button><button class="btn sm danger" id="r-del">✕</button></div></div>
      ${res.length ? `<div class="table-wrap"><table><thead><tr><th></th><th>Publicación</th><th>Vendedor</th><th class="num">Precio</th><th class="num">Vendidos</th><th>Visto</th><th></th></tr></thead><tbody>
      ${res.map(r => `<tr><td>${thumb(r.thumbnail)}</td><td><a href="${esc(r.url)}" target="_blank" rel="noopener" class="ellipsis" style="display:block;max-width:340px">${esc(r.title)}</a>
          <div class="small muted">${esc(r.external_id)} ${r.free_shipping ? '· envío gratis' : ''} ${r.is_new ? badge('nuevo', 'info') : ''}</div></td>
        <td class="small">${esc(r.seller || '—')}</td>
        <td class="num"><b>${money(r.price)}</b>${r.prev_price != null && r.prev_price !== r.price ? `<div class="small" style="color:var(${r.price < r.prev_price ? '--bad' : '--good'})">antes ${money(r.prev_price)}</div>` : ''}</td>
        <td class="num">${r.sold_quantity ?? '—'}</td><td class="small nowrap">${fmtDate(r.first_seen)}</td>
        <td><button class="btn sm" data-watch="${r.id}" title="Vigilar precio">◎</button></td></tr>`).join('')}</tbody></table></div>`
        : `<div class="empty">Sin resultados${s.last_error ? ' — revisa el error arriba' : ''}.</div>`}`;
    $('#r-sort').value = sort;
    $('#r-sort').addEventListener('change', e => { sort = e.target.value; loadResults(); });
    $('#r-new').addEventListener('change', e => { onlyNew = e.target.checked; loadResults(); });
    $('#r-run').addEventListener('click', e => busy(e.currentTarget, async () => {
      const r = await api(`/api/searches/${s.id}/run`, { method: 'POST' });
      toast(r.last_error ? r.last_error : `${r.result_count} resultados`, r.last_error ? 'error' : 'ok'); render();
    }));
    $('#r-edit').addEventListener('click', () => searchEditor(s));
    $('#r-del').addEventListener('click', async () => {
      if (!await confirmDialog(`¿Eliminar la búsqueda “${s.query}” y sus resultados?`)) return;
      await api(`/api/searches/${s.id}`, { method: 'DELETE' }); location.hash = '#/mercado'; render();
    });
    $$('[data-watch]').forEach(b => b.addEventListener('click', () => {
      const r = res.find(x => x.id === Number(b.dataset.watch));
      watchEditor({ url: r.url, name: r.title, interval_hours: 12, active: true });
    }));
  };
  await loadResults();
});

async function searchEditor(s) {
  const sites = await api('/api/ml-sites');
  const m = openModal({
    title: s.id ? 'Editar búsqueda' : 'Nueva búsqueda de mercado',
    body: `<form id="qform" class="form-grid">
      <label class="field full">Palabras clave *<input name="query" required minlength="2" placeholder="ej. audífonos bluetooth" value="${esc(s.query || '')}"></label>
      <label class="field">País / sitio<select name="site">${Object.entries(sites).map(([k, v]) => `<option value="${k}" ${k === s.site ? 'selected' : ''}>${k} · ${v}</option>`).join('')}</select></label>
      <label class="field">Revisar cada (horas)<input name="interval_hours" type="number" min="1" step="1" value="${s.interval_hours}"></label>
      <label class="row small"><input type="checkbox" name="active" style="width:auto" ${s.active ? 'checked' : ''}> Revisar automáticamente</label></form>`,
    foot: '<button class="btn" data-close>Cancelar</button><button class="btn primary" id="q-save">Guardar y ejecutar</button>',
  });
  $('#q-save', m.el).addEventListener('click', e => busy(e.currentTarget, async () => {
    const form = $('#qform', m.el); if (!form.reportValidity()) return;
    const saved = await api(s.id ? `/api/searches/${s.id}` : '/api/searches', { method: s.id ? 'PUT' : 'POST', body: formData(form) });
    if (saved.last_error) toast(saved.last_error, 'error');
    m.close(); location.hash = `#/mercado?id=${saved.id}`; render();
  }));
}

// ======================================================================= CONFIGURACIÓN
route('configuracion', 'Configuración', async (rest, qs) => {
  const [s, ml, sites] = await Promise.all([api('/api/settings'), api('/api/ml/status'), api('/api/ml-sites')]);
  if (qs.get('ml') === 'ok') toast('Cuenta de Mercado Libre conectada', 'ok');
  const callback = `${location.origin}/api/ml/callback`;
  view.innerHTML = `<div class="grid cols-2e">
    <div class="stack">
      <div class="card"><h2 style="margin-bottom:12px">Negocio</h2>
        <form id="f-biz" class="form-grid">
          <label class="field full">Nombre del negocio<input name="business_name" value="${esc(s.business_name)}"></label>
          <label class="field">Moneda<select name="currency">${['MXN', 'ARS', 'COP', 'CLP', 'PEN', 'UYU', 'BRL', 'USD', 'EUR'].map(c => `<option ${c === s.currency ? 'selected' : ''}>${c}</option>`).join('')}</select></label>
          <label class="field">País Mercado Libre<select name="ml_site">${Object.entries(sites).map(([k, v]) => `<option value="${k}" ${k === s.ml_site ? 'selected' : ''}>${k} · ${v}</option>`).join('')}</select></label>
        </form></div>
      <div class="card"><h2 style="margin-bottom:4px">Comisiones por canal</h2>
        <p class="small muted" style="margin-top:0">% que se descuenta automáticamente de cada venta si no capturas la comisión exacta.</p>
        <form id="f-fee" class="form-grid">
          ${Object.entries(CH).map(([k, v]) => `<label class="field">${v.label} (%)<input type="number" step="0.1" min="0" name="fee_${k}_pct" value="${esc(s[`fee_${k}_pct`])}"></label>`).join('')}
          <label class="field">Alertar si el competidor está ≥ X% más barato<input type="number" step="0.5" min="0" name="alert_cheaper_pct" value="${esc(s.alert_cheaper_pct)}"></label>
        </form></div>
      <div><button class="btn primary" id="save-settings">Guardar configuración</button></div>
    </div>
    <div class="stack">
      <div class="card"><div class="card-head"><h2>${chan('mercadolibre')}</h2>${ml.connected ? badge(`● Conectado: ${ml.nickname || ml.user_id}`, 'good') : badge('No conectado')}</div>
        ${ml.connected ? `<div class="row" style="margin-bottom:14px">
            <button class="btn" id="ml-orders">⇩ Importar pedidos (30 días)</button>
            <button class="btn" id="ml-items">⇩ Importar publicaciones</button>
            <button class="btn danger" id="ml-off">Desconectar</button></div>` : ''}
        <details ${ml.connected ? '' : 'open'}><summary class="small" style="cursor:pointer;margin-bottom:10px">Credenciales de la aplicación</summary>
        <ol class="small muted" style="padding-left:18px;margin-top:0">
          <li>Crea una app en <a href="https://developers.mercadolibre.com.mx/devcenter" target="_blank" rel="noopener">developers.mercadolibre.com</a>.</li>
          <li>Como <b>Redirect URI</b> usa: <code>${esc(callback)}</code> (debe ser HTTPS en producción).</li>
          <li>Copia aquí el App ID y la Secret Key, guarda y pulsa “Conectar”.</li></ol>
        <form id="f-ml" class="form-grid">
          <label class="field">App ID<input name="ml_app_id" value="${esc(s.ml_app_id)}"></label>
          <label class="field">Secret Key<input name="ml_client_secret" type="password" value="${esc(s.ml_client_secret)}"></label>
          <label class="field full">Redirect URI<input name="ml_redirect_uri" value="${esc(s.ml_redirect_uri || callback)}"></label>
        </form>
        <div class="row" style="margin-top:12px"><button class="btn" id="ml-save">Guardar credenciales</button><button class="btn primary" id="ml-connect">Conectar con Mercado Libre</button></div>
        </details></div>
      <div class="card"><h2 style="margin-bottom:8px">${chan('marketplace')}</h2>
        <p class="small muted" style="margin-top:0">Meta no ofrece API pública para publicar en Marketplace como particular. Opciones:</p>
        <ul class="small" style="padding-left:18px"><li>En cada producto, pestaña <b>Texto para publicar</b>: copia el anuncio y descarga las fotos.</li>
          <li>Si tienes tienda en Meta Commerce Manager, sube este catálogo (o úsalo como feed programado):</li></ul>
        <a class="btn" href="/api/export/meta-catalog.csv">⇩ Catálogo Meta (CSV)</a></div>
      <div class="card"><h2 style="margin-bottom:10px">Exportar datos</h2><div class="row">
        <a class="btn" href="/api/export/products.csv">Productos</a><a class="btn" href="/api/export/sales.csv">Ventas</a>
        <a class="btn" href="/api/export/customers.csv">Clientes</a><a class="btn" href="/api/export/expenses.csv">Gastos</a></div></div>
    </div></div>`;

  const saveAll = async (...forms) => {
    const values = Object.assign({}, ...forms.map(f => formData($(f))));
    for (const k in values) values[k] = String(values[k] ?? '');
    state.settings = await api('/api/settings', { method: 'PUT', body: values });
    $('#brand-name').textContent = state.settings.business_name;
  };
  $('#save-settings').addEventListener('click', e => busy(e.currentTarget, async () => { await saveAll('#f-biz', '#f-fee'); toast('Configuración guardada', 'ok'); }));
  $('#ml-save').addEventListener('click', e => busy(e.currentTarget, async () => { await saveAll('#f-ml'); toast('Credenciales guardadas', 'ok'); }));
  $('#ml-connect').addEventListener('click', e => busy(e.currentTarget, async () => {
    await saveAll('#f-ml'); const { url } = await api('/api/ml/auth-url'); location.href = url;
  }));
  if (ml.connected) {
    $('#ml-orders').addEventListener('click', e => busy(e.currentTarget, async () => {
      const r = await api('/api/ml/sync-orders?days=30', { method: 'POST' }); toast(`Pedidos: ${r.nuevas} nuevos, ${r.actualizadas} actualizados`, 'ok');
    }));
    $('#ml-items').addEventListener('click', e => busy(e.currentTarget, async () => {
      const r = await api('/api/ml/sync-listings', { method: 'POST' }); toast(`Publicaciones: ${r.nuevas} nuevas, ${r.actualizadas} actualizadas`, 'ok');
    }));
    $('#ml-off').addEventListener('click', async () => {
      if (!await confirmDialog('¿Desconectar la cuenta de Mercado Libre?', 'Desconectar')) return;
      await api('/api/ml/disconnect', { method: 'POST' }); render();
    });
  }
});

// ======================================================================= fotos
async function compressImage(file, max = 1600, quality = 0.85) {
  if (file.type === 'image/gif' || !window.createImageBitmap) return file;
  let bmp;
  try { bmp = await createImageBitmap(file); } catch { return file; }
  const scale = Math.min(1, max / Math.max(bmp.width, bmp.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(bmp.width * scale);
  canvas.height = Math.round(bmp.height * scale);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#ffffff';  // fondo blanco para PNG con transparencia
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise(r => canvas.toBlob(r, 'image/jpeg', quality));
  if (!blob || blob.size >= file.size && scale === 1 && file.type === 'image/jpeg') return file;
  return new File([blob], file.name.replace(/\.[^.]+$/, '') + '.jpg', { type: 'image/jpeg' });
}

// ======================================================================= acceso y configuración inicial
function fullScreen(html) {
  $('.layout').classList.add('hidden');
  let el = $('#gate');
  if (!el) { el = document.createElement('div'); el.id = 'gate'; el.className = 'gate'; document.body.appendChild(el); }
  el.innerHTML = `<div class="gate-box">${html}</div>`;
  return el;
}

function showLogin() {
  if ($('#gate #login-form')) return;
  const el = fullScreen(`
    <div class="brand" style="justify-content:center;padding-bottom:6px"><span class="logo"></span><span>${esc(state.settings.business_name || 'Panel de Ventas')}</span></div>
    <p class="muted" style="text-align:center;margin-top:0">Ingresa la contraseña del panel</p>
    <form id="login-form" class="stack" style="gap:10px">
      <input type="password" name="password" placeholder="Contraseña" autocomplete="current-password" required autofocus>
      <button class="btn primary" style="justify-content:center">Entrar</button>
      <div id="login-err" class="small" style="color:var(--bad);min-height:1.2em"></div>
    </form>`);
  $('#login-form', el).addEventListener('submit', async e => {
    e.preventDefault();
    const btn = $('button', e.target);
    btn.disabled = true;
    try {
      const res = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: e.target.password.value }) });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Error');
      location.reload();
    } catch (err) { $('#login-err', el).textContent = err.message; btn.disabled = false; }
  });
}

function showSetup(st) {
  const step = (ok, title, body) => `<li class="setup-step ${ok ? 'ok' : ''}"><b>${ok ? '✓' : '○'} ${title}</b><div class="small muted">${body}</div></li>`;
  fullScreen(`
    <h1 style="font-size:20px;margin-bottom:6px">¡Tu panel ya está en línea! 🎉</h1>
    <p class="muted" style="margin-top:0">Falta configurarlo en Vercel (una sola vez). Después pulsa <b>Redeploy</b>.</p>
    <ol class="setup">
      ${step(st.password_configured, 'Contraseña del panel',
        'Vercel → tu proyecto → <b>Settings → Environment Variables</b> → agrega <code>ADMIN_PASSWORD</code> con una contraseña larga.')}
      ${step(st.database_persistent && st.database_ok, 'Base de datos (para no perder tus datos)',
        'Vercel → tu proyecto → <b>Storage → Create Database → Neon (Postgres)</b> → Connect. Crea <code>DATABASE_URL</code> automáticamente.' +
        (st.database_error ? `<br><span style="color:var(--bad)">Error: ${esc(st.database_error)}</span>` : ''))}
      ${step(st.cron_configured, 'Revisiones automáticas de precios (opcional)',
        'Agrega <code>CRON_SECRET</code> con cualquier texto largo. Vercel revisará los precios 1 vez al día.')}
    </ol>
    <p class="small muted">Después de agregar las variables: <b>Deployments → ⋯ → Redeploy</b>, y recarga esta página.</p>
    <button class="btn primary" onclick="location.reload()">Ya lo hice, recargar</button>`);
}

function systemBanner(st) {
  const box = $('#sys-banner');
  if (!box) return;
  if (!st.database_ok) {
    box.innerHTML = `<div class="notice bad">⚠ No se puede conectar a la base de datos: ${esc(st.database_error)}</div>`;
  } else if (!st.database_persistent) {
    box.innerHTML = `<div class="notice warn">⚠ <b>Modo de prueba:</b> no hay base de datos conectada y lo que guardes se borrará.
      En Vercel ve a <b>Storage → Create Database → Neon</b>, conéctala al proyecto y haz <b>Redeploy</b>.</div>`;
  } else box.innerHTML = '';
}

$('#logout-btn')?.addEventListener('click', async () => {
  await fetch('/api/logout', { method: 'POST' });
  location.reload();
});

// ======================================================================= arranque
(async function init() {
  let st = {};
  try { st = state.status = await (await fetch('/api/status')).json(); } catch { /* sin conexión */ }
  if (st.auth_required && !st.password_configured) return showSetup(st);
  if (st.auth_required && !st.logged_in) return showLogin();
  if (!st.auth_required) $('#logout-btn')?.classList.add('hidden');
  systemBanner(st);
  try {
    state.settings = await api('/api/settings');
    $('#brand-name').textContent = state.settings.business_name;
    document.title = `${state.settings.business_name} · Panel`;
  } catch { /* se muestra el error en la vista */ }
  render();
})();
