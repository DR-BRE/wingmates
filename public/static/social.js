'use strict';

// Social tab: find people by username, answer requests, compare wingspans.
// Shares $, api, post, esc, fmt, toast and meReady with app.js, and mapRoutes
// and the 'tab' event with history.js.

const EARTH_MI = 24901;
const MATE_COLOUR = '#f08a6b';

let social = null;          // last /api/social payload
let openMateId = null;      // the mate shown head-to-head, if any

const laps = mi => (mi / EARTH_MI).toFixed(1);

function person(p) {
  return `${avatar(p)}<span class="pn"><b>${esc(p.name)}</b>
    <span class="un">@${esc(p.username)}</span></span>`;
}

function button(label, cls, fn) {
  const b = document.createElement('button');
  b.textContent = label;
  if (cls) b.className = cls;
  b.addEventListener('click', e => { e.stopPropagation(); fn(b); });
  return b;
}

function note(text) {
  const s = document.createElement('span');
  s.className = 'st';
  s.textContent = text;
  return s;
}

function findHint(msg, bad) {
  const h = $('find-hint');
  h.className = 'hint' + (bad ? ' error' : '');
  h.textContent = msg;
}

// ------------------------------------------------------------------- data
async function loadSocial() {
  try {
    renderSocial(await api('/api/social'));
  } catch (e) {
    findHint(`Could not load your mates: ${e.message}`, true);
  }
}

// Run one action, then refresh the page's state and any open lookup card.
async function act(path, body, done) {
  try {
    await post(path, body);
    if (done) toast(done);
  } catch (e) {
    toast(e.message, true);
  }
  await loadSocial();
  const shown = $('find-card').dataset.username;
  if (shown) lookup(shown);
}

// ----------------------------------------------------------------- lookup
async function lookup(username) {
  const box = $('find-card');
  try {
    renderCard(await api('/api/users/lookup?username=' + encodeURIComponent(username)));
    findHint('Type their exact username.');
  } catch (e) {
    box.innerHTML = '';
    delete box.dataset.username;
    findHint(e.message, true);
  }
}

function renderCard(p) {
  const box = $('find-card');
  box.innerHTML = '';
  box.dataset.username = p.username;
  const row = document.createElement('div');
  row.className = 'logrow prow';
  row.innerHTML = person(p);
  if (p.relation === 'self') {
    row.append(note('This is you'));
  } else if (p.relation === 'mate') {
    row.append(note('Already mates'));
  } else if (p.relation === 'requested') {
    row.append(note('Requested'),
               button('Cancel', 'quiet', () => act(`/api/mates/${p.id}/cancel`)));
  } else if (p.relation === 'incoming') {
    row.append(button('Accept', '', () => act(`/api/mates/${p.id}/accept`, {},
                      `You and @${p.username} are mates now.`)));
  } else {
    row.append(button('Add mate', '', () => act('/api/mates/request',
                      { username: p.username })));
  }
  box.appendChild(row);
}

$('find-form').addEventListener('submit', e => {
  e.preventDefault();
  const q = $('find-user').value.trim();
  if (q) lookup(q);
});

// ----------------------------------------------------------------- render
function renderSocial(d) {
  social = d;

  const badge = $('social-badge');
  badge.hidden = d.incoming.length === 0;
  badge.textContent = d.incoming.length;

  const reqs = $('req-list');
  reqs.innerHTML = '';
  $('req-section').hidden = d.incoming.length + d.outgoing.length === 0;
  $('req-count').textContent = d.incoming.length + d.outgoing.length;
  for (const p of d.incoming) {
    const row = document.createElement('div');
    row.className = 'logrow prow';
    row.innerHTML = person(p);
    row.append(
      button('Accept', '', () => act(`/api/mates/${p.id}/accept`, {},
             `You and @${p.username} are mates now.`)),
      button('Decline', 'quiet', () => act(`/api/mates/${p.id}/decline`)));
    reqs.appendChild(row);
  }
  for (const p of d.outgoing) {
    const row = document.createElement('div');
    row.className = 'logrow prow';
    row.innerHTML = person(p);
    row.append(note('Requested'),
               button('Cancel', 'quiet', () => act(`/api/mates/${p.id}/cancel`)));
    reqs.appendChild(row);
  }

  $('mates-count').textContent = d.mates.length;
  $('mates-empty').style.display = d.mates.length ? 'none' : 'block';
  const board = $('board');
  board.innerHTML = '';
  const everyone = [{ ...d.me, isMe: true }, ...d.mates]
    .sort((a, b) => b.stats.distance_mi - a.stats.distance_mi);
  everyone.forEach((p, i) => {
    const s = p.stats;
    const row = document.createElement('div');
    row.className = 'logrow prow brow' + (p.isMe ? ' me' : '')
                  + (p.id === openMateId ? ' open' : '');
    row.innerHTML = `<span class="rank${i < 3 ? ' medal m' + (i + 1) : ''}">${i + 1}</span>${person(p)}
      <span class="ws">${fmt(s.distance_mi)}<small>mi</small></span>
      <span class="sub">${laps(s.distance_mi)}× around the Earth ·
        ${fmt(s.countries)} countries · ${fmt(s.airports)} airports</span>`;
    if (!p.isMe) row.addEventListener('click', () => toggleMate(p.id));
    board.appendChild(row);
  });

  if (openMateId === null) return;
  if (d.mates.some(m => m.id === openMateId)) renderH2H();
  else closeMate();
}

// ----------------------------------------------------------- head to head
const H2H_ROWS = [['Wingspan', 'distance_mi', ' mi'], ['Flights', 'flights', ''],
                  ['Airports', 'airports', ''], ['Countries', 'countries', '']];

function renderH2H() {
  const mate = social.mates.find(m => m.id === openMateId);
  const me = social.me.stats, them = mate.stats;
  const box = $('h2h');
  box.hidden = false;
  box.innerHTML = `<h2>You vs @${esc(mate.username)}</h2>
    <table class="h2h">${H2H_ROWS.map(([label, key, unit]) => `<tr>
      <td class="${me[key] > them[key] ? 'lead' : ''}">${fmt(me[key], unit)}</td>
      <th>${label}</th>
      <td class="${them[key] > me[key] ? 'lead' : ''}">${fmt(them[key], unit)}</td>
    </tr>`).join('')}</table>`;
  // Removing takes two clicks, like deleting a flight.
  box.appendChild(button('Remove mate', 'quiet', b => {
    if (b.dataset.armed !== '1') {
      b.dataset.armed = '1';
      b.textContent = `Remove @${mate.username}?`;
      setTimeout(() => { b.dataset.armed = ''; b.textContent = 'Remove mate'; }, 3000);
      return;
    }
    act(`/api/mates/${mate.id}/remove`, {}, `Removed @${mate.username}.`);
  }));
}

function drawMate(routes) {
  const arcs = routes.map(r => ({ a: [r.from.lat, r.from.lon],
                                  b: [r.to.lat, r.to.lon] }));
  const airports = new Map();
  for (const r of routes) {
    for (const a of [r.from, r.to]) {
      airports.set(a.iata, { lat: a.lat, lon: a.lon, code: a.iata,
                             name: `${a.name} · ${a.city}` });
    }
  }
  if (window.Globe3D) window.Globe3D.setMateRoutes(arcs, [...airports.values()]);
  mapRoutes('mate', arcs, [...airports.values()], MATE_COLOUR);
}

async function toggleMate(id) {
  if (openMateId === id) return closeMate();
  openMateId = id;
  renderSocial(social);
  try {
    const d = await api(`/api/mates/${id}/routes`);
    if (openMateId === id) drawMate(d.routes);
  } catch (e) {
    toast(e.message, true);
  }
}

function closeMate() {
  openMateId = null;
  $('h2h').hidden = true;
  drawMate([]);
  if (social) renderSocial(social);
}

// ------------------------------------------------------------------- boot
document.addEventListener('tab', e => {
  if (e.detail === 'social') loadSocial();
  else if (openMateId !== null) closeMate();
});

// Load once at start so the tab shows its request count.
meReady.then(loadSocial).catch(() => {});
