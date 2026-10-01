'use strict';

// Flight history: the "My flights" tab. Shares $, api, toast and fmt with app.js.

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

let historyFlights = [];

// -------------------------------------------------------------------- tabs
function showTab(name) {
  $('pane-history').hidden = name !== 'history';
  $('pane-live').hidden = name !== 'live';
  $('tab-history').classList.toggle('on', name === 'history');
  $('tab-live').classList.toggle('on', name === 'live');
}
$('tab-history').addEventListener('click', () => showTab('history'));
$('tab-live').addEventListener('click', () => showTab('live'));

// ---------------------------------------------------------------- flat map
const RAD = Math.PI / 180;
let routeLayer = null;

// Great-circle path between two [lat, lon] points, longitudes unwrapped so the
// line is continuous across the antimeridian.
function greatCircle(a, b) {
  const vec = ([la, lo]) => [Math.cos(la * RAD) * Math.cos(lo * RAD),
                             Math.cos(la * RAD) * Math.sin(lo * RAD),
                             Math.sin(la * RAD)];
  const va = vec(a), vb = vec(b);
  const dot = Math.min(1, Math.max(-1, va[0] * vb[0] + va[1] * vb[1] + va[2] * vb[2]));
  const ang = Math.acos(dot), sin = Math.sin(ang);
  if (sin < 1e-9) return [a, b];
  const n = Math.max(2, Math.ceil(ang / (1.5 * RAD)));
  const out = [];
  let prev = null;
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    const k1 = Math.sin((1 - t) * ang) / sin, k2 = Math.sin(t * ang) / sin;
    const x = k1 * va[0] + k2 * vb[0], y = k1 * va[1] + k2 * vb[1],
          z = k1 * va[2] + k2 * vb[2];
    let lon = Math.atan2(y, x) / RAD;
    if (prev !== null) {
      while (lon - prev > 180) lon -= 360;
      while (lon - prev < -180) lon += 360;
    }
    prev = lon;
    out.push([Math.asin(Math.max(-1, Math.min(1, z))) / RAD, lon]);
  }
  return out;
}

function routesToMap(routes, airports) {
  if (typeof map === 'undefined' || !map) return;
  if (!routeLayer) routeLayer = L.layerGroup().addTo(map);
  routeLayer.clearLayers();
  // Draw each route and airport in the neighbouring world copies too, so a
  // route that crosses the antimeridian still meets its far airport.
  for (const shift of [-360, 0, 360]) {
    for (const r of routes) {
      L.polyline(greatCircle(r.a, r.b).map(([la, lo]) => [la, lo + shift]),
                 { color: '#5fd0dd', weight: 1.6, opacity: 0.75,
                   interactive: false }).addTo(routeLayer);
    }
    for (const a of airports) {
      L.circleMarker([a.lat, a.lon + shift],
                     { radius: 3.5, color: '#dff7fa', weight: 1,
                       fillColor: '#5fd0dd', fillOpacity: 1 })
        .bindTooltip(`${a.code} · ${a.name}`, { className: 'tag' })
        .addTo(routeLayer);
    }
  }
}

function showFlight(f) {
  if (f.from.lat == null || f.to.lat == null) return;
  const a = [f.from.lat, f.from.lon], b = [f.to.lat, f.to.lon];
  if (view === 'globe' && window.Globe3D) {
    window.Globe3D.flyToRoute(a, b);
  } else {
    map.fitBounds(L.latLngBounds(greatCircle(a, b)),
                  { padding: [50, 50], maxZoom: 6 });
  }
}

// ------------------------------------------------------------ draw routes
// One arc per airport pair, whichever direction it was flown.
function drawRoutes() {
  const routes = new Map(), airports = new Map();
  for (const f of historyFlights) {
    if (f.from.lat == null || f.to.lat == null) continue;
    const pair = [f.from.iata, f.to.iata].sort().join('-');
    routes.set(pair, { a: [f.from.lat, f.from.lon], b: [f.to.lat, f.to.lon] });
    for (const a of [f.from, f.to]) {
      airports.set(a.iata, { lat: a.lat, lon: a.lon, code: a.iata,
                             name: `${a.name} · ${a.city}` });
    }
  }
  routesToMap([...routes.values()], [...airports.values()]);
  if (window.Globe3D) {
    window.Globe3D.setRoutes([...routes.values()], [...airports.values()]);
  }
}
window.addEventListener('globe-ready', drawRoutes);

// -------------------------------------------------------------------- edit
let editingId = null;
const FIELDS = { 'h-from': f => f.from.iata, 'h-to': f => f.to.iata,
  'h-date': f => f.date, 'h-airline': f => f.airline,
  'h-flight': f => f.flight_number, 'h-aircraft': f => f.aircraft,
  'h-seat': f => f.seat, 'h-notes': f => f.notes };

function enterEdit(f) {
  editingId = f.id;
  for (const [id, get] of Object.entries(FIELDS)) $(id).value = get(f) || '';
  if (f.airline || f.flight_number || f.aircraft || f.seat || f.notes) {
    $('hist-form').querySelector('details').open = true;
  }
  $('hist-form').classList.add('editing');
  $('h-label').textContent = 'Edit flight';
  $('h-add').textContent = 'Save changes';
  $('h-cancel').hidden = false;
  $('h-import').hidden = true;
  hint(`Editing ${f.from.iata} → ${f.to.iata} on ${f.date}.`);
  $('hist-form').scrollIntoView({ block: 'nearest' });
  $('h-from').focus();
  markEditing();
}

function exitEdit() {
  editingId = null;
  $('hist-form').classList.remove('editing');
  $('h-label').textContent = 'Add a flight';
  $('h-add').textContent = 'Add flight';
  $('h-cancel').hidden = true;
  $('h-import').hidden = false;
  for (const id of Object.keys(FIELDS)) $(id).value = '';
  markEditing();
}

function markEditing() {
  for (const el of document.querySelectorAll('.frow')) {
    el.classList.toggle('editing', Number(el.dataset.id) === editingId);
  }
}

$('h-cancel').addEventListener('click', () => {
  exitEdit();
  hint('Edit cancelled.');
});

// ------------------------------------------------------------------ render
function renderHistory(d) {
  historyFlights = d.flights;
  const s = d.stats;
  $('h-stats').innerHTML = `
    <div><dt>Flights</dt><dd>${fmt(s.flights)}</dd></div>
    <div><dt>Distance</dt><dd>${fmt(s.distance_mi)}<small>mi</small></dd></div>
    <div><dt>Airports</dt><dd>${fmt(s.airports)}</dd></div>
    <div><dt>Countries</dt><dd>${fmt(s.countries)}</dd></div>`;

  $('h-count').textContent = d.flights.length;
  $('h-empty').style.display = d.flights.length ? 'none' : 'block';
  const box = $('h-list');
  box.innerHTML = '';
  for (const f of d.flights) {
    const el = document.createElement('div');
    el.className = 'logrow frow';
    el.dataset.id = f.id;
    const sub = [f.airline, f.flight_number, f.aircraft, f.seat && 'seat ' + f.seat,
                 f.notes].filter(Boolean).join(' · ');
    el.innerHTML = `<span class="d">${esc(f.date)}</span>
      <span class="c">${esc(f.from.iata)} → ${esc(f.to.iata)}</span>
      <span class="m">${fmt(f.distance_mi, ' mi')}</span>
      <button class="ed" title="Edit this flight">✎</button>
      <button class="x" title="Delete this flight">×</button>
      <span class="sub">${esc(f.from.city)} to ${esc(f.to.city)}${
        sub ? ' · ' + esc(sub) : ''}</span>`;
    el.addEventListener('click', () => showFlight(f));
    el.querySelector('.ed').addEventListener('click', e => {
      e.stopPropagation();
      enterEdit(f);
    });
    // Deleting takes two clicks, so a stray tap can't lose a flight.
    const x = el.querySelector('.x');
    x.addEventListener('click', async e => {
      e.stopPropagation();
      if (x.dataset.armed !== '1') {
        x.dataset.armed = '1';
        x.textContent = 'Delete?';
        setTimeout(() => { x.dataset.armed = ''; x.textContent = '×'; }, 3000);
        return;
      }
      try {
        await api('/api/history/delete', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: f.id }) });
        if (editingId === f.id) exitEdit();
        loadHistory();
      } catch (err) { toast(err.message, true); }
    });
    box.appendChild(el);
  }
  markEditing();
  drawRoutes();
}

async function loadHistory() {
  try {
    renderHistory(await api('/api/history'));
  } catch (e) {
    hint(`Could not load your flights: ${e.message}`, true);
  }
}

function hint(msg, bad) {
  const h = $('h-hint');
  h.className = 'hint' + (bad ? ' error' : '');
  h.textContent = msg;
}

// ----------------------------------------------------------- autocomplete
let suggestTimer = null;
function suggest(e) {
  const q = e.target.value.trim();
  clearTimeout(suggestTimer);
  if (q.length < 2) return;
  suggestTimer = setTimeout(async () => {
    try {
      const d = await api('/api/airports?q=' + encodeURIComponent(q));
      $('apt-list').innerHTML = d.airports.map(a =>
        `<option value="${esc(a.iata)}">${esc(a.city)} · ${esc(a.name)}</option>`
      ).join('');
    } catch (err) { /* suggestions are optional */ }
  }, 150);
}
$('h-from').addEventListener('input', suggest);
$('h-to').addEventListener('input', suggest);

// ----------------------------------------------------------------- actions
$('hist-form').addEventListener('submit', async e => {
  e.preventDefault();
  const val = id => $(id).value.trim();
  const btn = $('h-add');
  const editing = editingId !== null;
  btn.disabled = true;
  try {
    const f = await api(editing ? '/api/history/update' : '/api/history',
      { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: editingId,
          date: val('h-date'), from: val('h-from'), to: val('h-to'),
          airline: val('h-airline'), flight_number: val('h-flight'),
          aircraft: val('h-aircraft'), seat: val('h-seat'), notes: val('h-notes'),
        }) });
    if (editing) {
      exitEdit();
      hint(`Saved ${f.from.iata} → ${f.to.iata}, ${fmt(f.distance_mi, ' mi')}.`);
    } else {
      hint(`Added ${f.from.iata} → ${f.to.iata}, ${fmt(f.distance_mi, ' mi')}.`);
      // Set up for the next leg: it most likely starts where this one ended.
      $('h-from').value = f.to.iata;
      for (const id of ['h-to', 'h-flight', 'h-seat', 'h-notes']) $(id).value = '';
      $('h-to').focus();
    }
    await loadHistory();
    showFlight(f);
  } catch (err) {
    hint(err.message, true);
  } finally {
    btn.disabled = false;
  }
});

$('h-import').addEventListener('click', () => $('h-file').click());
$('h-file').addEventListener('change', async e => {
  const file = e.target.files[0];
  e.target.value = '';
  if (!file) return;
  try {
    const r = await api('/api/history/import', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ csv: await file.text() }) });
    const parts = [`Imported ${r.added} flight(s)`];
    if (r.skipped) parts.push(`${r.skipped} already in your log`);
    if (r.errors.length) {
      parts.push(`${r.errors.length} row(s) skipped: ` + r.errors.slice(0, 4)
        .map(x => `line ${x.line} ${x.error}`).join('; ')
        + (r.errors.length > 4 ? '; …' : ''));
    }
    hint(parts.join('. ') + '.', r.errors.length > 0);
    loadHistory();
  } catch (err) {
    hint(err.message, true);
  }
});

loadHistory();
