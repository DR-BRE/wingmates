'use strict';

// The passport: a three-spread book with two turning leaves, replacing the
// old sidebar tabs. Shares $, esc, fmt with app.js and historyFlights with
// history.js. Fires the same 'tab' event the old tabs fired, so social.js
// needs no changes.

const VP_SPREADS = [
  { name: 'history', tab: 'vp-tab-0' },
  { name: 'social', tab: 'vp-tab-1' },
  { name: 'stamps', tab: 'vp-tab-2' },
];
const ACTIVE_Z = 5;
const TURN_MS = 450;
const REDUCE_MOTION = matchMedia('(prefers-reduced-motion: reduce)').matches;

let vpSpread = 0;

function leafEl(n) { return $('vp-leaf' + n); }
function shadeFor(n) { return leafEl(n).querySelector('.vp-shade'); }

// A leaf can only be grabbed when it is the top of whichever pile it rests
// in: leaf 1 between spreads 0 and 1, leaf 2 between spreads 1 and 2.
function leafActive(n) { return vpSpread === n - 1 || vpSpread === n; }
function restAngle(n) { return vpSpread >= n ? -180 : 0; }
function restZ(n, angle) { return n === 1 ? (angle <= -90 ? 1 : 3) : 2; }

function setLeaf(n, angle, z) {
  const el = leafEl(n);
  el.style.setProperty('--vp-angle', angle + 'deg');
  el.style.setProperty('--vp-z', z);
}

// A full, non-dragged turn: peak the shadow immediately, fade it as the
// leaf settles. Used by a tap on the grip, the tabs and the keyboard.
function animateLeaf(n, toAngle) {
  setLeaf(n, toAngle, ACTIVE_Z);
  const shade = shadeFor(n);
  shade.style.opacity = '.35';
  setTimeout(() => { shade.style.opacity = '0'; }, REDUCE_MOTION ? 0 : TURN_MS / 2);
  setTimeout(() => { setLeaf(n, toAngle, restZ(n, toAngle)); }, REDUCE_MOTION ? 0 : TURN_MS);
}

function updateChrome() {
  VP_SPREADS.forEach((s, i) => $(s.tab).setAttribute('aria-selected', String(i === vpSpread)));
  $('vp-stage').dataset.spread = String(vpSpread);
  for (const n of [1, 2]) {
    const grip = leafEl(n).querySelector('.vp-grip');
    grip.style.cursor = leafActive(n) ? 'grab' : 'default';
    grip.style.pointerEvents = leafActive(n) ? 'auto' : 'none';
  }
}

function announceSpread() {
  document.dispatchEvent(new CustomEvent('tab', { detail: VP_SPREADS[vpSpread].name }));
}

function goToSpread(target) {
  target = Math.max(0, Math.min(2, target));
  if (target === vpSpread) return;
  const from = vpSpread;
  vpSpread = target;
  if ((from < 1) !== (target < 1)) animateLeaf(1, restAngle(1));
  if ((from < 2) !== (target < 2)) animateLeaf(2, restAngle(2));
  updateChrome();
  announceSpread();
}

for (const s of VP_SPREADS) {
  $(s.tab).addEventListener('click', () => goToSpread(VP_SPREADS.indexOf(s)));
}

// ------------------------------------------------------------------ drag
let drag = null; // { n, startX, startAngle, width, angle }

function toggleLeaf(n) {
  goToSpread(vpSpread === n - 1 ? n : n - 1);
}

for (const n of [1, 2]) {
  const leaf = leafEl(n), grip = leaf.querySelector('.vp-grip');

  grip.addEventListener('pointerdown', e => {
    if (!leafActive(n)) return;
    if (REDUCE_MOTION) { toggleLeaf(n); return; }
    drag = { n, startX: e.clientX, startAngle: restAngle(n),
             width: leaf.getBoundingClientRect().width, angle: restAngle(n) };
    leaf.classList.add('dragging');
    setLeaf(n, drag.angle, ACTIVE_Z);
    grip.setPointerCapture(e.pointerId);
  });

  grip.addEventListener('pointermove', e => {
    if (!drag || drag.n !== n) return;
    const dx = e.clientX - drag.startX;
    drag.angle = Math.max(-180, Math.min(0, drag.startAngle + (dx / drag.width) * 180));
    setLeaf(n, drag.angle, ACTIVE_Z);
    shadeFor(n).style.opacity = String(Math.sin((Math.abs(drag.angle) / 180) * Math.PI) * 0.35);
  });

  const release = e => {
    if (!drag || drag.n !== n) return;
    leaf.classList.remove('dragging');
    const moved = Math.abs(drag.angle - drag.startAngle) > 2;
    if (!moved) {
      drag = null;
      toggleLeaf(n);
      return;
    }
    const committed = Math.abs(drag.angle) > 90;
    const toAngle = committed ? (drag.startAngle === 0 ? -180 : 0) : drag.startAngle;
    vpSpread = toAngle === -180 ? Math.max(vpSpread, n) : Math.min(vpSpread, n - 1);
    setLeaf(n, toAngle, ACTIVE_Z);
    shadeFor(n).style.opacity = '0';
    setTimeout(() => setLeaf(n, toAngle, restZ(n, toAngle)), REDUCE_MOTION ? 0 : TURN_MS);
    updateChrome();
    announceSpread();
    drag = null;
  };
  grip.addEventListener('pointerup', release);
  grip.addEventListener('pointercancel', release);
}

// --------------------------------------------------------- open / close
function openPassport() {
  $('vp-backdrop').hidden = false;
  $('vp-stage').hidden = false;
  requestAnimationFrame(() => {
    $('vp-backdrop').classList.add('show');
    $('vp-stage').classList.add('show');
  });
}

function closePassport() {
  $('vp-backdrop').classList.remove('show');
  $('vp-stage').classList.remove('show');
  setTimeout(() => {
    if (!$('vp-stage').classList.contains('show')) {
      $('vp-backdrop').hidden = true;
      $('vp-stage').hidden = true;
    }
  }, REDUCE_MOTION ? 0 : 300);
}

$('vp-open').addEventListener('click', openPassport);
$('vp-close').addEventListener('click', closePassport);
$('vp-backdrop').addEventListener('click', closePassport);

// A global listener, like Escape: nothing inside the book reliably holds
// keyboard focus, so scoping this to an element would miss most presses.
document.addEventListener('keydown', e => {
  if (!$('vp-stage').classList.contains('show')) return;
  if (e.key === 'Escape') { closePassport(); return; }
  const t = document.activeElement;
  if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
  if (t && t.isContentEditable) return;
  if (e.key === 'ArrowRight') { goToSpread(vpSpread + 1); e.preventDefault(); }
  else if (e.key === 'ArrowLeft') { goToSpread(vpSpread - 1); e.preventDefault(); }
  else if (e.key === 'Home') { goToSpread(0); e.preventDefault(); }
  else if (e.key === 'End') { goToSpread(2); e.preventDefault(); }
});

// ---------------------------------------------------------- the record
const FIRST_COLOUR = ['var(--vp-stamp-plum)', 'var(--vp-stamp-teal)', 'var(--vp-stamp-brick)',
                       'var(--vp-stamp-forest)', 'var(--vp-stamp-navy)'];
function inkFor(code) {
  let h = 0;
  for (const c of code) h = (h * 31 + c.charCodeAt(0)) | 0;
  return FIRST_COLOUR[Math.abs(h) % FIRST_COLOUR.length];
}

function renderStamps(flights) {
  const byCountry = new Map();
  for (const f of flights) {
    for (const end of ['from', 'to']) {
      const a = f[end];
      if (!a.country) continue;
      const rec = byCountry.get(a.country) || { cities: new Set(), count: 0, first: f.date };
      rec.cities.add(a.city || a.iata);
      rec.count += 1;
      if (f.date < rec.first) rec.first = f.date;
      byCountry.set(a.country, rec);
    }
  }
  const box = $('vp-stamps');
  box.innerHTML = '';
  $('vp-stamps-count').textContent = byCountry.size;
  $('vp-stamps-empty').style.display = byCountry.size ? 'none' : 'block';
  const codes = [...byCountry.keys()].sort();
  for (const code of codes) {
    const rec = byCountry.get(code);
    const el = document.createElement('div');
    el.className = 'vp-stamp';
    el.style.setProperty('--stamp-ink', inkFor(code));
    el.style.setProperty('--stamp-tilt', (((code.charCodeAt(0) * 7) % 13) - 6) + 'deg');
    el.innerHTML = `<b>${esc(code)}</b><span>${fmt(rec.count)} visit${rec.count === 1 ? '' : 's'}</span>`;
    el.title = [...rec.cities].join(', ');
    box.appendChild(el);
  }
}

function renderRecord(flights) {
  const empty = $('vp-record-empty'), dl = $('vp-record');
  if (!flights.length) {
    dl.innerHTML = '';
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';
  const furthest = flights.reduce((a, b) => b.distance_mi > a.distance_mi ? b : a);
  const first = flights.reduce((a, b) => b.date < a.date ? b : a);
  const counts = new Map();
  for (const f of flights) {
    const key = [f.from.iata, f.to.iata].sort().join('-');
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  const [mostKey, mostCount] = [...counts.entries()].reduce((a, b) => b[1] > a[1] ? b : a);
  dl.innerHTML = `
    <div><dt>Furthest flight</dt><dd>${esc(furthest.from.iata)} → ${esc(furthest.to.iata)}
      <small>${fmt(furthest.distance_mi)} mi</small></dd></div>
    <div><dt>First flight</dt><dd>${esc(first.from.iata)} → ${esc(first.to.iata)}
      <small>${esc(first.date)}</small></dd></div>
    <div><dt>Most-flown route</dt><dd>${esc(mostKey.replace('-', ' → '))}
      <small>${fmt(mostCount)}×</small></dd></div>`;
}

document.addEventListener('flights', e => {
  renderStamps(e.detail.flights);
  renderRecord(e.detail.flights);
});

// The Countries tile on the Totals page jumps straight to the stamps.
$('h-stats').addEventListener('click', e => {
  if (e.target.closest('#h-stat-countries')) goToSpread(2);
});

// ------------------------------------------------------------------ boot
setLeaf(1, 0, 3);
setLeaf(2, 0, 2);
updateChrome();
