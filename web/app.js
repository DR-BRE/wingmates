'use strict';

const $ = id => document.getElementById(id);
const REFRESH_MS = 4000;

let map, selected = null;
const trackedLayers = new Map();   // key -> {marker, trail}
let nearbyLayer = null;
let lastAlertStamp = null;
let view = 'map';                  // 'globe' once globe.js has loaded
let lastFlights = [];
let liveOn = false;
const meReady = api('/api/me');

// ------------------------------------------------------------- globe / map
const globe = () => (view === 'globe' ? window.Globe3D : null);

function setView(next) {
  if (next === 'globe' && !window.Globe3D) return;
  const centre = viewCenter();
  view = next;
  $('globe').hidden = view !== 'globe';
  $('map').style.display = view === 'map' ? '' : 'none';
  $('btn-globe').classList.toggle('on', view === 'globe');
  $('btn-map').classList.toggle('on', view === 'map');
  if (view === 'map') {
    map.invalidateSize();
    map.setView([centre.lat, centre.lng], map.getZoom());
  } else {
    window.Globe3D.setTracked(lastFlights, selected);
  }
}

function viewCenter() {
  return globe() ? globe().getCenter() : map.getCenter();
}

function focusOn(lat, lon, zoom) {
  if (globe()) globe().flyTo(lat, lon, 1.9);
  else map.setView([lat, lon], zoom);
}

// ---------------------------------------------------------------- map setup
function initMap() {
  map = L.map('map', { zoomControl: true, worldCopyJump: true })
         .setView([33.64, -84.43], 6);
  // CARTO's free dark tiles now demand an API key; Esri's dark gray set does not.
  const esri = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/';
  L.tileLayer(esri + 'World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap '
      + 'contributors · ADS-B via adsb.lol / OpenSky',
    maxZoom: 16
  }).addTo(map);
  L.tileLayer(esri + 'World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}',
              { maxZoom: 16 }).addTo(map);
  nearbyLayer = L.layerGroup().addTo(map);
}

// A simple arrow glyph, rotated to the aircraft's track. Original artwork.
function planeIcon(track, colour, scale) {
  const s = scale || 1;
  const svg =
    `<svg class="plane" width="${26 * s}" height="${26 * s}" viewBox="0 0 26 26"
          style="transform:rotate(${(track || 0)}deg)">
       <path d="M13 1 L18 16 L13 13 L8 16 Z" fill="${colour}"
             stroke="#080c11" stroke-width="1" stroke-linejoin="round"/>
     </svg>`;
  return L.divIcon({ html: svg, className: '', iconSize: [26 * s, 26 * s],
                     iconAnchor: [13 * s, 13 * s] });
}

function fmt(n, unit) {
  if (n === null || n === undefined) return '—';
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 }) + (unit || '');
}

function toast(msg, bad) {
  const t = $('toast');
  t.textContent = msg;
  t.className = 'toast show' + (bad ? ' bad' : '');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.className = 'toast'; }, 4200);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({ error: 'bad response' }));
  // A session that has expired, or an account with no username yet, cannot
  // use the app: go to the page that fixes it.
  if (res.status === 401) location.href = '/login';
  if (res.status === 409 && data.error === 'choose a username first') {
    location.href = '/welcome';
  }
  if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
  return data;
}

// Every write goes through here: the server refuses a POST that is not JSON.
const post = (path, body) => api(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {}),
});

// Values from the feed and from other people are never trusted as HTML.
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function avatar(p) {
  const url = p.picture_url || '';
  // Only https pictures are ever used as an image source.
  return url.startsWith('https://')
    ? `<img class="av" src="${esc(url)}" alt="" referrerpolicy="no-referrer">`
    : `<span class="av">${esc((p.name || p.username || '?').charAt(0).toUpperCase())}</span>`;
}

// ------------------------------------------------------------ render: state
function renderStatus(s) {
  $('pill-source').textContent = s.source || 'offline';
  $('pill-source').className = 'pill' + (s.feed_errors.length ? ' bad' : '');
  $('pill-tracked').textContent = `${s.tracked}/${s.max_tracked} tracked`;
  if (s.last_poll) {
    const age = Math.round((Date.now() - new Date(s.last_poll)) / 1000);
    $('pill-poll').textContent = `polled ${age}s ago`;
  }
}

function renderFlights(flights) {
  $('flights-count').textContent = flights.length;
  $('flights-empty').style.display = flights.length ? 'none' : 'block';
  const box = $('flights');
  box.innerHTML = '';

  const live = new Set();
  for (const f of flights) {
    live.add(f.key);
    const card = document.createElement('div');
    card.className = 'card' + (selected === f.key ? ' sel' : '')
                   + (f.emergency ? ' emerg' : '');
    card.innerHTML = `
      <div class="top">
        <span class="cs">${esc(f.callsign)}</span>
        <span class="reg">${esc(f.registration || '')} ${esc(f.aircraft_type || '')}</span>
        <button class="x" title="Stop tracking" data-key="${esc(f.key)}">×</button>
      </div>
      <span class="phase ${esc(f.phase)}">${esc(f.phase.replace(/_/g, ' '))}${
        f.vertical && f.phase === 'airborne' ? ' · ' + esc(f.vertical) : ''}</span>
      <dl class="metrics">
        <div><dt>Alt</dt><dd>${fmt(f.altitude_ft)}</dd></div>
        <div><dt>Speed</dt><dd>${fmt(f.ground_speed_kt)}<span style="font-size:10px"> kt</span></dd></div>
        <div><dt>V/S</dt><dd>${f.vertical_rate_fpm ? fmt(f.vertical_rate_fpm) : '—'}</dd></div>
      </dl>`;
    card.querySelector('.x').addEventListener('click', async e => {
      e.stopPropagation();
      await post('/api/untrack', { key: e.target.dataset.key });
      toast('Stopped tracking — moved to the flight log.');
      refresh();
    });
    card.addEventListener('click', () => {
      selected = f.key;
      if (f.lat != null) focusOn(f.lat, f.lon, Math.max(map.getZoom(), 7));
      refresh();
    });
    box.appendChild(card);

    // --- map layers
    const colour = f.emergency ? '#e0574d'
                 : (selected === f.key ? '#4fb6c2' : '#7f9bb0');
    let layer = trackedLayers.get(f.key);
    if (f.lat == null) continue;
    if (!layer) {
      layer = {
        marker: L.marker([f.lat, f.lon],
                         { icon: planeIcon(f.track_deg, colour, 1.15) }).addTo(map),
        trail: L.polyline(f.trail || [], { color: colour, weight: 2,
                                           opacity: .75 }).addTo(map)
      };
      trackedLayers.set(f.key, layer);
    } else {
      layer.marker.setLatLng([f.lat, f.lon]);
      layer.marker.setIcon(planeIcon(f.track_deg, colour, 1.15));
      layer.trail.setLatLngs(f.trail || []);
      layer.trail.setStyle({ color: colour });
    }
    layer.marker.bindTooltip(f.callsign, { permanent: true, direction: 'right',
                                           className: 'tag', offset: [10, 0] });
    layer.marker.bindPopup(
      `<div class="pop"><b>${esc(f.callsign)}</b><br>
       ${esc(f.registration || '—')} · ${esc(f.aircraft_type || '—')}<br>
       ${esc(f.phase.replace(/_/g, ' '))} · ${esc(f.vertical)}<br>
       ${fmt(f.altitude_ft, ' ft')} · ${fmt(f.ground_speed_kt, ' kt')}<br>
       squawk ${esc(f.squawk || '—')} · seen ${fmt(f.stale_s, 's')} ago</div>`);
  }

  for (const [key, layer] of trackedLayers) {
    if (!live.has(key)) {
      map.removeLayer(layer.marker); map.removeLayer(layer.trail);
      trackedLayers.delete(key);
    }
  }

  lastFlights = flights;
  if (globe()) globe().setTracked(flights, selected);
}

function renderAlerts(alerts) {
  $('alerts-empty').style.display = alerts.length ? 'none' : 'block';
  const box = $('alerts');
  box.innerHTML = '';
  for (const a of alerts) {
    const el = document.createElement('div');
    const alarm = a.type === 'EmergencySquawk';
    el.className = 'ev' + (a.loud ? ' loud' : '') + (alarm ? ' alarm' : '');
    const t = new Date(a.at);
    el.innerHTML = `<span class="t">${String(t.getHours()).padStart(2, '0')}:${
      String(t.getMinutes()).padStart(2, '0')}</span>
      <span class="b"><span class="h">${esc(a.title)}</span>
      <span class="d">${esc(a.detail)}</span>
      <span class="f">${esc(a.flight)}</span></span>`;
    box.appendChild(el);
  }
  // Surface genuinely new loud events rather than silently updating the list.
  const newest = alerts[0];
  if (newest && newest.at !== lastAlertStamp) {
    if (lastAlertStamp !== null && newest.loud) {
      toast(`${newest.flight}: ${newest.title} — ${newest.detail}`,
            newest.type === 'EmergencySquawk');
    }
    lastAlertStamp = newest.at;
  }
}

function renderLog(log) {
  $('log-count').textContent = log.length;
  const box = $('log');
  box.innerHTML = '';
  for (const l of log) {
    const el = document.createElement('div');
    el.className = 'logrow';
    el.innerHTML = `<span class="c">${esc(l.callsign)}</span>
      <span style="color:var(--faint)">${esc(l.registration || '—')}</span>
      <span class="m">${fmt(l.max_altitude_ft, ' ft')} · ${fmt(l.max_speed_kt, ' kt')}</span>`;
    box.appendChild(el);
  }
}

// -------------------------------------------------------------- data cycle
async function refresh() {
  if (!liveOn) return;
  try {
    const s = await api('/api/state');
    renderStatus(s.status);
    renderFlights(s.flights);
    renderAlerts(s.alerts);
    renderLog(s.log);
  } catch (e) {
    $('pill-source').textContent = 'server unreachable';
    $('pill-source').className = 'pill bad';
  }
}

// ------------------------------------------------------------------ actions
$('add-form').addEventListener('submit', async e => {
  e.preventDefault();
  const input = $('cs'), hint = $('add-hint'), btn = $('add-btn');
  const cs = input.value.trim();
  if (!cs) return;
  btn.disabled = true; btn.textContent = '…';
  hint.className = 'hint'; hint.textContent = 'Looking up on the live feed…';
  try {
    const f = await post('/api/track', { callsign: cs });
    input.value = '';
    hint.textContent = `Tracking ${f.callsign}${f.registration ? ' · ' + f.registration : ''}.`;
    selected = f.key;
    if (f.lat != null) focusOn(f.lat, f.lon, 7);
    toast(`Tracking ${f.callsign}`);
    refresh();
  } catch (err) {
    hint.className = 'hint error';
    hint.textContent = err.message;
  } finally {
    btn.disabled = false; btn.textContent = 'Track';
  }
});

$('btn-nearby').addEventListener('click', async () => {
  const c = viewCenter();
  // The globe shows far more ground than the map, so widen the search with it.
  const dist = globe()
    ? Math.round(Math.min(250, Math.max(90, globe().viewRadiusNm()))) : 90;
  const btn = $('btn-nearby');
  btn.disabled = true; btn.textContent = '…';
  try {
    const d = await api(`/api/nearby?lat=${c.lat.toFixed(4)}&lon=${c.lng.toFixed(4)}&dist=${dist}`);
    nearbyLayer.clearLayers();
    const onGlobe = [];
    for (const a of d.aircraft) {
      if (a.lat == null) continue;
      const colour = a.emergency ? '#e0574d' : (a.on_ground ? '#5d6b7b' : '#d79a45');
      const html = `<div class="pop"><b>${esc(a.callsign)}</b><br>
        ${esc(a.registration || '—')} · ${esc(a.aircraft_type || '—')}<br>
        ${fmt(a.altitude_ft, ' ft')} · ${fmt(a.ground_speed_kt, ' kt')}<br>
        <button data-track="${esc(a.callsign)}">Track this</button></div>`;
      const m = L.marker([a.lat, a.lon],
                         { icon: planeIcon(a.track_deg, colour, .85) });
      m.bindPopup(html);
      nearbyLayer.addLayer(m);
      onGlobe.push({ lat: a.lat, lon: a.lon, track: a.track_deg, colour, html });
    }
    if (window.Globe3D) window.Globe3D.setNearby(onGlobe);
    toast(`${d.aircraft.length} aircraft within ${dist} nm of the view centre.`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false; btn.textContent = 'Nearby';
  }
});

window.quickTrack = async cs => {
  try {
    const f = await post('/api/track', { callsign: cs });
    selected = f.key;
    toast(`Tracking ${f.callsign}`);
    map.closePopup();
    if (window.Globe3D) window.Globe3D.closePopup();
    refresh();
  } catch (e) { toast(e.message, true); }
};

// Popups are built from HTML strings, so their Track button is wired here.
document.addEventListener('click', e => {
  const btn = e.target.closest('[data-track]');
  if (btn) window.quickTrack(btn.dataset.track);
});

$('btn-clear').addEventListener('click', () => {
  nearbyLayer.clearLayers();
  if (window.Globe3D) { window.Globe3D.clearNearby(); window.Globe3D.closePopup(); }
  toast('Nearby aircraft hidden.');
});

$('btn-refresh').addEventListener('click', async () => {
  const b = $('btn-refresh');
  b.disabled = true; b.textContent = '…';
  try {
    const r = await post('/api/poll');
    toast(`Polled the feed — ${r.updated} flight(s) updated.`);
    refresh();
  } catch (e) { toast(e.message, true); }
  finally { b.disabled = false; b.textContent = 'Poll now'; }
});

$('reg-form').addEventListener('submit', async e => {
  e.preventDefault();
  const reg = $('reg').value.trim();
  if (!reg) return;
  try {
    const a = await api('/api/aircraft?reg=' + encodeURIComponent(reg));
    const html = `<div class="pop"><b>${esc(a.registration)}</b><br>
       flying as ${esc(a.callsign)} · ${esc(a.aircraft_type || '—')}<br>
       ${fmt(a.altitude_ft, ' ft')} · ${fmt(a.ground_speed_kt, ' kt')}<br>
       <button data-track="${esc(a.callsign)}">Track this</button></div>`;
    focusOn(a.lat, a.lon, 8);
    if (globe()) globe().showPopup(a.lat, a.lon, html);
    else L.popup().setLatLng([a.lat, a.lon]).setContent(html).openOn(map);
    toast(`${a.registration} is flying as ${a.callsign}.`);
  } catch (err) { toast(err.message, true); }
});

function enableGlobe() {
  $('viewtoggle').hidden = false;
  window.Globe3D.onSelect(key => { selected = key; refresh(); });
  setView('globe');
}

$('btn-globe').addEventListener('click', () => setView('globe'));
$('btn-map').addEventListener('click', () => setView('map'));

function renderWho(me) {
  const who = $('who');
  if (me.auth === 'google') {
    who.innerHTML = `<details class="acct">
        <summary>${avatar(me)}<span class="me">@${esc(me.username)}</span></summary>
        <div class="menu">
          <button id="acct-out" class="quiet">Sign out</button>
          <button id="acct-del" class="quiet">Delete account</button>
          <form id="del-form" hidden autocomplete="off">
            <p>This removes your account and every flight you have logged.
               It cannot be undone.</p>
            <input id="del-confirm" placeholder="Type DELETE" spellcheck="false">
            <button type="submit" class="danger">Delete forever</button>
          </form>
        </div>
      </details>`;
    $('acct-out').addEventListener('click', async () => {
      try { await post('/auth/logout'); location.href = '/login'; }
      catch (err) { toast(err.message, true); }
    });
    $('acct-del').addEventListener('click', () => {
      $('del-form').hidden = false;
      $('del-confirm').focus();
    });
    $('del-form').addEventListener('submit', async e => {
      e.preventDefault();
      try {
        await post('/api/account/delete', { confirm: $('del-confirm').value });
        location.href = '/login';
      } catch (err) { toast(err.message, true); }
    });
    return;
  }
  who.innerHTML = `<span class="me">@${esc(me.username)}</span>` + (me.dev_users
    ? `<form id="dev-form"><input id="dev-user" placeholder="dev: switch user"
         spellcheck="false" autocapitalize="none"></form>` : '');
  if (!me.dev_users) return;
  $('dev-form').addEventListener('submit', async e => {
    e.preventDefault();
    try {
      await post('/dev/login', { username: $('dev-user').value });
      location.reload();
    } catch (err) { toast(err.message, true); }
  });
}

initMap();
// The globe needs WebGL and a CDN; if either is missing the flat map stays.
if (window.Globe3D) enableGlobe();
else window.addEventListener('globe-ready', enableGlobe, { once: true });

meReady.then(me => {
  renderWho(me);
  liveOn = me.live;
  document.body.classList.toggle('no-live', !me.live);
  if (!me.live) return;
  refresh();
  setInterval(refresh, REFRESH_MS);
}).catch(() => {
  $('pill-source').textContent = 'server unreachable';
  $('pill-source').className = 'pill bad';
});
