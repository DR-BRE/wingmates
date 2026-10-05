'use strict';

// Finding flights in email. Shares $, post, api, toast with app.js, and hint
// with history.js.
//
// The rule this file exists to enforce: a scan proposes, a person disposes.
// Nothing here ever adds a flight on its own. Anything the extractor was not
// certain about arrives unticked, so the lazy path is the safe one.

let proposals = [];
let gmailReady = false;

const panel = () => $('g-panel');

function setLabel(text) {
  const label = $('g-connect-label');
  if (label) label.textContent = text;
}

// ------------------------------------------------------------------ status
async function refreshStatus() {
  const btn = $('g-connect');
  if (!btn) return;
  try {
    const s = await api('/api/gmail/status');
    if (!s.available) {
      btn.hidden = true;            // local mode: no Google app to connect to
      return;
    }
    btn.hidden = false;
    gmailReady = s.connected;
    setLabel(s.connected ? 'Check email for flights' : 'Find my flights');
    btn.title = s.connected
      ? `Connected as ${s.email || 'your account'} — searches for confirmations`
      : 'Connect your email so flights can be found automatically';
  } catch {
    btn.hidden = true;
  }
}

// -------------------------------------------------------------------- scan
async function scan() {
  const btn = $('g-connect');
  btn.disabled = true;
  setLabel('Looking…');
  hint('Searching your email for flight confirmations. '
       + 'This can take a few seconds.');
  try {
    const r = await post('/api/gmail/scan', {});
    proposals = r.proposals || [];
    render(r);
  } catch (e) {
    if (/connect gmail/i.test(e.message)) {
      gmailReady = false;
      setLabel('Find my flights');
      hint('Your email connection has ended. Connect again to keep finding '
           + 'flights.', true);
    } else {
      hint(e.message, true);
    }
  } finally {
    btn.disabled = false;
    if (gmailReady) setLabel('Check email for flights');
  }
}

// ------------------------------------------------------------------ render
function render(result) {
  const list = $('g-list');
  list.innerHTML = '';

  if (!proposals.length) {
    panel().hidden = true;
    const looked = result.scanned
      ? `Looked through ${result.scanned} email${result.scanned === 1 ? '' : 's'}`
      : 'Looked through your email';
    hint(`${looked} and found nothing new — everything is already in your log.`);
    return;
  }

  for (const [i, p] of proposals.entries()) {
    const sure = p.confidence === 'high';
    const li = document.createElement('li');
    li.className = 'proposal' + (sure ? ' on' : '');
    li.innerHTML = `
      <input type="checkbox" id="g-p${i}" ${sure ? 'checked' : ''}
             aria-label="Add ${p.from} to ${p.to} on ${p.date}">
      <div class="body">
        <div class="route">${p.from} → ${p.to}
          <span class="tagline ${sure ? 'sure' : 'maybe'}">${
            sure ? 'from your ticket' : 'check this one'}</span>
        </div>
        <div class="meta">${p.date}${
          p.flight_number ? ' · ' + p.flight_number : ''}${
          p.airline ? ' · ' + p.airline : ''}</div>
        <div class="from">${p.subject || ''}</div>
      </div>`;
    const box = li.querySelector('input');
    box.addEventListener('change', () => {
      li.classList.toggle('on', box.checked);
      updateCount();
    });
    list.appendChild(li);
  }

  panel().hidden = false;
  const unsure = proposals.length - (result.high_confidence || 0);
  const parts = [`Found ${proposals.length} flight${
    proposals.length === 1 ? '' : 's'} not yet in your log`];
  if (unsure > 0) {
    parts.push(`${unsure} came from the wording of an email rather than the `
               + `ticket itself, so ${unsure === 1 ? "it is" : "they are"} `
               + `unticked — have a look before adding`);
  }
  $('g-summary').textContent = parts.join('. ') + '.';
  updateCount();
  panel().scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function chosen() {
  return proposals.filter((_, i) => $('g-p' + i)?.checked);
}

function updateCount() {
  const n = chosen().length;
  $('g-add').disabled = n === 0;
  $('g-add').textContent = n ? `Add ${n} flight${n === 1 ? '' : 's'}` : 'Add selected';
}

function setAll(on) {
  proposals.forEach((_, i) => {
    const box = $('g-p' + i);
    if (box) {
      box.checked = on;
      box.closest('.proposal').classList.toggle('on', on);
    }
  });
  updateCount();
}

// ------------------------------------------------------------------ wiring
function wire() {
  const btn = $('g-connect');
  if (!btn) return;

  btn.addEventListener('click', () => {
    if (gmailReady) return scan();
    // Leaving the page, so no spinner — the redirect is the feedback.
    window.location.href = '/auth/gmail/connect';
  });

  $('g-all').addEventListener('click', () => setAll(true));
  $('g-none').addEventListener('click', () => setAll(false));
  $('g-close').addEventListener('click', () => { panel().hidden = true; });

  $('g-add').addEventListener('click', async () => {
    const picked = chosen();
    if (!picked.length) return;
    $('g-add').disabled = true;
    try {
      const r = await post('/api/gmail/import', { flights: picked });
      const parts = [`Added ${r.added} flight${r.added === 1 ? '' : 's'}`];
      if (r.skipped) parts.push(`${r.skipped} already in your log`);
      if (r.errors?.length) parts.push(`${r.errors.length} could not be added`);
      hint(parts.join('. ') + '.', (r.errors?.length || 0) > 0);
      toast(`Added ${r.added} flight${r.added === 1 ? '' : 's'}`);
      panel().hidden = true;
      proposals = [];
      if (typeof loadHistory === 'function') loadHistory();
    } catch (e) {
      hint(e.message, true);
      $('g-add').disabled = false;
    }
  });

  // Coming back from Google. Clean the query out of the address bar so a
  // refresh does not replay the message.
  const params = new URLSearchParams(window.location.search);
  const outcome = params.get('gmail');
  if (outcome) {
    history.replaceState({}, '', window.location.pathname);
    if (outcome === 'connected') {
      gmailReady = true;
      setLabel('Check email for flights');
      scan();
    } else if (outcome === 'denied') {
      hint('No problem — you can still add flights by hand or import a CSV.');
    } else if (outcome === 'unavailable') {
      hint('Email searching is not set up on this server.', true);
    } else {
      hint('That connection did not complete. Try again.', true);
    }
  }

  refreshStatus();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', wire);
} else {
  wire();
}
