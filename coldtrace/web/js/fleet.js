// Fleet rail (left sidebar) + "new shipment" flow.
const Fleet = (() => {
  let shipments = [], lanes = [], commodities = [], scenarios = {}, selected = null, onSelect = null;

  async function load() {
    [shipments, lanes, commodities, scenarios] = await Promise.all([
      API.get('/api/shipments'), API.get('/api/ref/lanes'), API.get('/api/ref/commodities'), API.get('/api/ref/scenarios'),
    ]);
    renderRail();
  }

  function renderRail() {
    const rail = document.getElementById('rail');
    UI.clear(rail);
    rail.appendChild(UI.el('div', { class: 'rail-head' }, [
      UI.el('h2', {}, `Fleet (${shipments.length})`),
      UI.el('button', { class: 'btn btn-sm btn-primary', onclick: openNewShipment }, '+ New'),
    ]));
    if (!shipments.length) rail.appendChild(UI.el('div', { class: 'empty' }, 'No shipments yet. Create one to start the demo.'));
    for (const s of shipments) {
      const led = !s.last_reading ? 'info' : s.out_of_band ? 'crit' : 'ok';
      const item = UI.el('div', { class: 'ship-item' + (selected === s.id ? ' active' : ''), onclick: () => onSelect && onSelect(s.id) }, [
        UI.el('div', { class: 'row1' }, [
          UI.el('div', { class: 'flex items-center gap-6' }, [UI.el('span', { class: 'led ' + led }), UI.el('span', { class: 'code' }, s.code)]),
          UI.el('span', { class: 'temp' }, s.last_reading ? UI.temp(s.last_reading.temp_c) : '—'),
        ]),
        UI.el('div', { class: 'lane' }, lanes.find(l => l.id === s.lane_id)?.name || s.lane_id),
        UI.el('div', { class: 'lane' }, `${s.status} · ${s.scenario.replace('_', ' ')}`),
      ]);
      rail.appendChild(item);
    }
    return rail;
  }

  function setSelected(id) { selected = id; renderRail(); }

  async function openNewShipment() {
    const laneSel = UI.el('select', { id: 'ns-lane' }, lanes.map(l => UI.el('option', { value: l.id }, `${l.name} (${Math.round(l.distance_km || 0)} km)`)));
    const comSel = UI.el('select', { id: 'ns-com' });
    const scSel = UI.el('select', { id: 'ns-scn' }, Object.entries(scenarios).map(([k, v]) => UI.el('option', { value: k }, v)));
    function refreshCommodities() {
      const lane = lanes.find(l => l.id === laneSel.value);
      UI.clear(comSel);
      for (const code of lane.commodities) {
        const c = commodities.find(x => x.code === code);
        comSel.appendChild(UI.el('option', { value: code }, c ? c.name : code));
      }
    }
    laneSel.addEventListener('change', refreshCommodities);

    // Default the departure time to somewhere inside the actually-loaded weather window, not "now" -
    // ERA5 archive data always lags several days behind real time, so "now" is never valid.
    let defaultDepart = new Date(Date.now() - new Date().getTimezoneOffset() * 60000);
    let windowHint = '';
    try {
      const status = await API.get('/api/ref/data-status');
      const w = status.weather;
      if (w && w.ready && w.from && w.to) {
        const from = new Date(w.from), to = new Date(w.to);
        // Leave a day of buffer at the start so a multi-day trip has room to run inside the window.
        const target = new Date(Math.min(from.getTime() + 24 * 3600 * 1000, to.getTime()));
        defaultDepart = new Date(target.getTime() - target.getTimezoneOffset() * 60000);
        windowHint = `Loaded weather covers ${w.from.slice(0, 16).replace('T', ' ')} → ${w.to.slice(0, 16).replace('T', ' ')} UTC.`;
      } else {
        windowHint = 'No weather loaded yet - run scripts/fetch_data.py --weather, then pick a date it covers.';
      }
    } catch { /* data-status not reachable; fall back to "now" and let the create call report the real window */ }

    const departInput = UI.el('input', { type: 'datetime-local', id: 'ns-depart', value: defaultDepart.toISOString().slice(0, 16) });
    const qtyInput = UI.el('input', { type: 'number', id: 'ns-qty', placeholder: 'auto (typical load)' });
    const valueInput = UI.el('input', { type: 'number', id: 'ns-value', placeholder: 'auto (from Agmarknet price)' });
    const err = UI.el('div', { class: 'hint', style: 'color:var(--red);min-height:16px' });
    const body = UI.el('div', {}, [
      UI.el('div', { class: 'field' }, [UI.el('label', {}, 'Lane (real market → destination)'), laneSel]),
      UI.el('div', { class: 'field' }, [UI.el('label', {}, 'Commodity'), comSel]),
      UI.el('div', { class: 'field-row' }, [
        UI.el('div', { class: 'field' }, [UI.el('label', {}, 'Depart (UTC)'), departInput]),
        UI.el('div', { class: 'field' }, [UI.el('label', {}, 'Scenario'), scSel]),
      ]),
      windowHint ? UI.el('div', { class: 'hint' }, windowHint) : null,
      UI.el('div', { class: 'field-row' }, [
        UI.el('div', { class: 'field' }, [UI.el('label', {}, 'Quantity, kg'), qtyInput]),
        UI.el('div', { class: 'field' }, [UI.el('label', {}, 'Declared value, INR'), valueInput]),
      ]),
      err,
      UI.el('button', { class: 'btn btn-primary', style: 'width:100%', onclick: submit }, 'Create shipment'),
    ]);
    refreshCommodities();
    const close = UI.modal('New shipment', body);
    async function submit() {
      try {
        const depart_ts = new Date(departInput.value).toISOString().replace(/\.\d+Z$/, 'Z');
        const s = await API.post('/api/shipments', {
          lane_id: laneSel.value, commodity_code: comSel.value, depart_ts, scenario: scSel.value,
          qty_kg: qtyInput.value ? Number(qtyInput.value) : null, declared_value_inr: valueInput.value ? Number(valueInput.value) : null,
        });
        close();
        UI.toast(`Created ${s.code}`, 'ok');
        await load();
        onSelect && onSelect(s.id);
      } catch (e) { err.textContent = e.message; }
    }
  }

  function setOnSelect(fn) { onSelect = fn; }
  function get(id) { return shipments.find(s => s.id === id); }
  function patchLocal(id, patch) { const s = get(id); if (s) Object.assign(s, patch); renderRail(); }

  return { load, renderRail, setSelected, setOnSelect, get, patchLocal, all: () => shipments };
})();
