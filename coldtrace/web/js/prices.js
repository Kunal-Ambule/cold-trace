const PricesView = (() => {
  async function render() {
    const main = document.getElementById('main');
    UI.clear(main);
    document.getElementById('rail').style.display = 'none';
    document.getElementById('feed').style.display = 'none';
    const commodities = await API.get('/api/ref/commodities');
    main.appendChild(UI.el('div', { class: 'section' }, [
      UI.el('h2', {}, 'Real market prices'),
      UI.el('div', { class: 'hint' }, 'Source: Agmarknet (Ministry of Agriculture and Farmers Welfare) via data.gov.in — a real snapshot bundled with this project.'),
    ]));
    const sel = UI.el('select', {}, commodities.filter(c => c.agmarknet).map(c => UI.el('option', { value: c.code }, c.name)));
    const stateSel = UI.el('select', {}, [UI.el('option', { value: '' }, 'All states')]);
    main.appendChild(UI.el('div', { class: 'field-row section' }, [
      UI.el('div', { class: 'field' }, [UI.el('label', {}, 'Commodity'), sel]),
      UI.el('div', { class: 'field' }, [UI.el('label', {}, 'State'), stateSel]),
    ]));
    const out = UI.el('div', {});
    main.appendChild(out);
    async function refreshStates() {
      const states = await API.get(`/api/ref/prices/${sel.value}/states`);
      UI.clear(stateSel);
      stateSel.appendChild(UI.el('option', { value: '' }, 'All states'));
      for (const s of states) stateSel.appendChild(UI.el('option', { value: s }, s));
    }
    async function load() {
      const data = await API.get(`/api/ref/prices/${sel.value}/explorer` + (stateSel.value ? `?state=${encodeURIComponent(stateSel.value)}` : ''));
      UI.clear(out);
      if (!data.summary) { out.appendChild(UI.el('div', { class: 'empty' }, 'No listings for this commodity.')); return; }
      out.appendChild(UI.el('div', { class: 'grid3 section' }, [
        UI.el('div', { class: 'card stat' }, [UI.el('div', { class: 'label' }, 'Median modal price'), UI.el('div', { class: 'value' }, '₹' + data.summary.median.toLocaleString('en-IN')), UI.el('div', { class: 'sub' }, data.unit)]),
        UI.el('div', { class: 'card stat' }, [UI.el('div', { class: 'label' }, 'Range'), UI.el('div', { class: 'value', style: 'font-size:16px' }, `₹${data.summary.min.toLocaleString('en-IN')} – ₹${data.summary.max.toLocaleString('en-IN')}`)]),
        UI.el('div', { class: 'card stat' }, [UI.el('div', { class: 'label' }, 'Listings'), UI.el('div', { class: 'value' }, data.summary.n), UI.el('div', { class: 'sub' }, 'as of ' + data.summary.as_of)]),
      ]));
      const rows = data.rows.map(r => UI.el('tr', {}, [
        UI.el('td', {}, r.state), UI.el('td', {}, r.market), UI.el('td', {}, r.variety || '—'), UI.el('td', {}, r.grade || '—'),
        UI.el('td', { class: 'right mono' }, r.min_price), UI.el('td', { class: 'right mono' }, r.max_price), UI.el('td', { class: 'right mono' }, r.modal_price),
      ]));
      out.appendChild(UI.el('table', { class: 'data' }, [
        UI.el('thead', {}, UI.el('tr', {}, ['state', 'market', 'variety', 'grade', 'min', 'max', 'modal'].map(h => UI.el('th', {}, h)))),
        UI.el('tbody', {}, rows),
      ]));
    }
    sel.addEventListener('change', async () => { await refreshStates(); load(); });
    stateSel.addEventListener('change', load);
    await refreshStates(); await load();
  }
  return { render };
})();
