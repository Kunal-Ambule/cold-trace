// Offline-first driver check-ins. Failed POSTs are queued in IndexedDB and flushed on reconnect / a timer.
// Works with the reefer display switched off and patchy rural signal: every action is captured locally first.
const DB_NAME = 'coldtrace-driver', STORE = 'queue';
let idb;

function openDB() {
  return new Promise((res, rej) => {
    const r = indexedDB.open(DB_NAME, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(STORE, { keyPath: 'idem_key' });
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
}
async function queueAdd(item) {
  const tx = idb.transaction(STORE, 'readwrite');
  tx.objectStore(STORE).put(item);
  return new Promise((res) => { tx.oncomplete = res; });
}
async function queueAll() {
  return new Promise((res) => {
    const tx = idb.transaction(STORE, 'readonly');
    const req = tx.objectStore(STORE).getAll();
    req.onsuccess = () => res(req.result);
  });
}
async function queueDelete(key) {
  const tx = idb.transaction(STORE, 'readwrite');
  tx.objectStore(STORE).delete(key);
  return new Promise((res) => { tx.oncomplete = res; });
}

let token = localStorage.getItem('ct_driver_token') || null;
function authHeaders() { return token ? { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' }; }

function nowIso() { return new Date().toISOString().replace(/\.\d+Z$/, 'Z'); }
function uid() { return Date.now() + '-' + Math.random().toString(36).slice(2, 8); }

function getLocation() {
  return new Promise((res) => {
    if (!navigator.geolocation) return res(null);
    navigator.geolocation.getCurrentPosition(
      (p) => res({ lat: p.coords.latitude, lon: p.coords.longitude }),
      () => res(null), { timeout: 4000, maximumAge: 30000 },
    );
  });
}

function logRow(item, pending) {
  const log = document.getElementById('log');
  const row = document.createElement('div');
  row.className = 'row' + (pending ? ' pending' : '');
  row.innerHTML = `<span class="ts">${new Date(item.ts).toLocaleTimeString('en-IN', { hour12: false })}</span><span>${item.event.replace(/_/g, ' ')}${item.note ? ' — ' + item.note : ''}${pending ? ' (queued, will sync)' : ''}</span>`;
  log.insertBefore(row, log.firstChild);
}

async function submitCheckin(shipmentId, event, note) {
  const loc = await getLocation();
  const item = { idem_key: uid(), shipmentId, ts: nowIso(), party: 'carrier', event, note: note || null, lat: loc?.lat, lon: loc?.lon };
  const ok = await trySend(item);   // trySend itself queues the item in IndexedDB on failure
  logRow(item, !ok);
  updateQueueBadge();
}

async function trySend(item) {
  try {
    const res = await fetch(`/api/shipments/${item.shipmentId}/events`, {
      method: 'POST', headers: authHeaders(),
      body: JSON.stringify({ ts: item.ts, party: item.party, event: item.event, note: item.note, lat: item.lat, lon: item.lon, idem_key: item.idem_key }),
    });
    if (!res.ok) throw new Error('http ' + res.status);
    return true;
  } catch (e) {
    await queueAdd(item);
    return false;
  }
}

async function flushQueue() {
  const items = await queueAll();
  for (const item of items) {
    const ok = await trySend(item);
    if (ok) await queueDelete(item.idem_key);
  }
  updateQueueBadge();
  updateNetStatus();
}

async function updateQueueBadge() {
  const items = await queueAll();
  document.getElementById('queue-badge').textContent = items.length ? `${items.length} queued` : '';
}

function updateNetStatus() {
  const led = document.getElementById('net-led'), txt = document.getElementById('net-text');
  if (navigator.onLine) { led.className = 'led ok'; txt.textContent = 'online — check-ins sync immediately'; }
  else { led.className = 'led warn'; txt.textContent = 'offline — check-ins are queued on this phone'; }
}

async function loadShipments() {
  const res = await fetch('/api/shipments', { headers: authHeaders() });
  if (!res.ok) return;
  const ships = await res.json();
  const sel = document.getElementById('ship-select');
  sel.innerHTML = '';
  for (const s of ships.filter(s => s.status !== 'completed')) {
    const opt = document.createElement('option');
    opt.value = s.id; opt.textContent = `${s.code} (${s.status})`;
    sel.appendChild(opt);
  }
}

async function boot() {
  idb = await openDB();
  updateNetStatus();
  window.addEventListener('online', () => { updateNetStatus(); flushQueue(); });
  window.addEventListener('offline', updateNetStatus);
  setInterval(flushQueue, 20000);

  if (token) {
    document.getElementById('login-box').style.display = 'none';
    document.getElementById('app-box').style.display = '';
    await loadShipments();
    await flushQueue();
  }

  document.getElementById('login-btn').addEventListener('click', async () => {
    const u = document.getElementById('user').value, p = document.getElementById('pass').value;
    try {
      const r = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: u, password: p }) });
      if (!r.ok) throw new Error((await r.json()).detail || 'Login failed');
      const d = await r.json();
      token = d.token; localStorage.setItem('ct_driver_token', token);
      document.getElementById('login-box').style.display = 'none';
      document.getElementById('app-box').style.display = '';
      await loadShipments();
    } catch (e) { document.getElementById('login-err').textContent = e.message; }
  });

  document.getElementById('logout').addEventListener('click', () => {
    token = null; localStorage.removeItem('ct_driver_token'); location.reload();
  });

  for (const btn of document.querySelectorAll('.big-btn')) {
    btn.addEventListener('click', () => {
      const sid = Number(document.getElementById('ship-select').value);
      if (!sid) return alert('Pick a shipment first');
      submitCheckin(sid, btn.dataset.event);
      navigator.vibrate && navigator.vibrate(30);
    });
  }
  document.getElementById('send-note').addEventListener('click', () => {
    const sid = Number(document.getElementById('ship-select').value);
    const note = document.getElementById('note').value.trim();
    if (!sid || !note) return;
    submitCheckin(sid, 'driver_note', note);
    document.getElementById('note').value = '';
  });
}

if ('serviceWorker' in navigator) navigator.serviceWorker.register('/driver/sw.js').catch(() => {});
boot();
