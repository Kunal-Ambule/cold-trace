(() => {
  let activeTab = 'fleet', es = null;

  function showApp(show) {
    document.getElementById('login-screen').style.display = show ? 'none' : 'flex';
    document.getElementById('app').classList.toggle('shown', show);
  }

  async function boot() {
    if (!API.getToken()) { showApp(false); return; }
    try {
      const me = await API.get('/api/auth/me');
      document.getElementById('whoami').textContent = `${me.name || me.username} · ${me.role}`;
      showApp(true);
      document.getElementById('rail').style.display = '';
      document.getElementById('feed').style.display = '';
      await Fleet.load();
      Fleet.setOnSelect((id) => { activeTab = 'fleet'; setTab('fleet'); Fleet.setSelected(id); ShipmentView.render(id); });
      setTab('fleet');
      connectStream();
    } catch (e) { showApp(false); }
  }

  function setTab(tab) {
    activeTab = tab;
    for (const t of document.querySelectorAll('.tab')) t.classList.toggle('active', t.dataset.tab === tab);
    if (tab !== 'fleet') ShipmentView.stopPlay();  // don't keep simulating in the background while looking at another tab
    const isFleet = tab === 'fleet';
    document.getElementById('rail').style.display = isFleet ? '' : 'none';
    document.getElementById('feed').style.display = isFleet ? '' : 'none';
    document.getElementById('app').classList.toggle('full-width', !isFleet);
    if (tab === 'fleet') { if (!ShipmentView.current()) { UI.clear(document.getElementById('main')); document.getElementById('main').appendChild(UI.el('div', { class: 'empty' }, 'Select a shipment from the fleet list, or create a new one.')); } }
    else if (tab === 'disputes') DisputesView.render();
    else if (tab === 'prices') PricesView.render();
    else if (tab === 'admin') AdminView.render();
  }

  function connectStream() {
    if (es) es.close();
    const url = '/api/stream?token=' + encodeURIComponent(API.getToken());
    es = new EventSource(url);
    const led = document.getElementById('conn-led'), txt = document.getElementById('conn-text');
    es.addEventListener('ready', () => { led.className = 'led ok'; txt.textContent = 'live'; });
    es.onerror = () => { led.className = 'led crit'; txt.textContent = 'reconnecting…'; };
    es.addEventListener('alert', (e) => { const a = JSON.parse(e.data); pushFeed(`⚠ ${a.message}`, a.severity); ShipmentView.onLive(a); Fleet.load(); });
    es.addEventListener('action', (e) => { const a = JSON.parse(e.data); if (a.status === 'proposed') pushFeed(`Agent proposal: ${a.proposal?.explanation?.headline || a.kind}`, 'warn'); ShipmentView.onLive(a); });
    es.addEventListener('reading', (e) => { const d = JSON.parse(e.data); ShipmentView.onLive(d); Fleet.patchLocal(d.shipment_id, { last_reading: d.reading }); });
    es.addEventListener('agent_step', () => { if (ShipmentView.current()) ShipmentView.onLive({ shipment_id: ShipmentView.current() }); });
  }

  function pushFeed(msg, sev) {
    const feed = document.getElementById('feed');
    if (!feed.querySelector('.rail-head')) feed.appendChild(UI.el('div', { class: 'rail-head' }, UI.el('h2', {}, 'Live feed')));
    const item = UI.el('div', { class: 'card', style: 'padding:8px 10px;font-size:12px' }, [
      UI.el('div', { class: 'hint' }, new Date().toLocaleTimeString('en-IN', { hour12: false })),
      UI.el('div', {}, msg),
    ]);
    feed.insertBefore(item, feed.children[1] || null);
    while (feed.children.length > 25) feed.removeChild(feed.lastChild);
    UI.toast(msg, sev);
  }

  document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const u = document.getElementById('login-user').value, p = document.getElementById('login-pass').value;
    const err = document.getElementById('login-error');
    try { const r = await API.login(u, p); API.setToken(r.token); err.textContent = ''; boot(); }
    catch (ex) { err.textContent = ex.message; }
  });
  for (const b of document.querySelectorAll('.demo-users .btn')) {
    b.addEventListener('click', () => { document.getElementById('login-user').value = b.dataset.user; document.getElementById('login-pass').value = 'coldtrace'; document.getElementById('login-form').requestSubmit(); });
  }
  document.getElementById('logout-btn').addEventListener('click', () => { API.setToken(null); if (es) es.close(); location.reload(); });
  document.getElementById('tabs').addEventListener('click', (e) => { const t = e.target.closest('.tab'); if (t) setTab(t.dataset.tab); });

  boot();
})();
