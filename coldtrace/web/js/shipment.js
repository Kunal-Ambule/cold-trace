// Shipment detail: overview stats, map + telemetry chart, alerts/actions, timeline, ledger, attribution.
const ShipmentView = (() => {
  let current = null, sub = 'overview', readings = [], lane = null, route = null, playTimer = null;

  function stopPlay() { if (playTimer) { clearInterval(playTimer); playTimer = null; } }

  async function render(id) {
    if (current !== id) stopPlay();  // switching shipments stops any running auto-play for the old one
    current = id;
    const main = document.getElementById('main');
    UI.clear(main);
    const s = await API.get(`/api/shipments/${id}`);
    const [rts, evts, alerts, actions, summary, lanes] = await Promise.all([
      API.get(`/api/shipments/${id}/readings?limit=5000`), API.get(`/api/shipments/${id}/events`),
      API.get(`/api/shipments/${id}/alerts`), API.get(`/api/shipments/${id}/actions`),
      API.get(`/api/shipments/${id}/summary`), API.get('/api/ref/lanes'),
    ]);
    readings = rts;
    lane = lanes.find(l => l.id === s.lane_id);
    const com = (await API.get('/api/ref/commodities')).find(c => c.code === s.commodity_code);

    main.appendChild(header(s, summary));
    main.appendChild(subtabs());
    const body = UI.el('div', { id: 'ship-body' });
    main.appendChild(body);
    await renderSub(body, s, com, evts, alerts, actions, summary);
  }

  function header(s, summary) {
    const risk = summary.risk_level;
    return UI.el('div', { class: 'section' }, [
      UI.el('div', { class: 'flex justify-between items-center' }, [
        UI.el('div', {}, [
          UI.el('h2', { style: 'font-size:22px' }, s.code),
          UI.el('div', { class: 'muted', style: 'font-size:12.5px;margin-top:2px' }, `${s.commodity_code} · ${s.carrier} · departed ${UI.dt(s.depart_ts)}`),
        ]),
        UI.el('div', { class: 'flex gap-8 items-center' }, [
          UI.el('span', { class: 'pill ' + UI.riskClass(risk) }, `${risk} risk`),
          UI.el('button', { class: 'btn btn-sm', onclick: () => openEdit(s) }, '✎ Edit'),
          UI.el('button', { class: 'btn btn-sm btn-danger', onclick: () => confirmDelete(s) }, '🗑'),
          s.data_source === 'twin' && s.status !== 'completed' ? advanceControls(s.id) : null,
        ]),
      ]),
      UI.el('div', { class: 'grid3', style: 'margin-top:12px' }, [
        UI.el('div', { class: 'card stat' }, [UI.el('div', { class: 'label' }, 'Value at risk'), UI.el('div', { class: 'value' }, UI.inr(summary.value_at_risk_inr)), UI.el('div', { class: 'sub' }, `${UI.pct(summary.loss_pct)} of ₹${Math.round(s.declared_value_inr).toLocaleString('en-IN')}`)]),
        UI.el('div', { class: 'card stat' }, [UI.el('div', { class: 'label' }, 'Minutes out of band'), UI.el('div', { class: 'value' }, (summary.minutes_out_of_band ?? 0).toFixed(0)), UI.el('div', { class: 'sub' }, summary.first_breach_ts ? 'first at ' + UI.timeOnly(summary.first_breach_ts) : 'no breach recorded')]),
        UI.el('div', { class: 'card stat' }, [UI.el('div', { class: 'label' }, 'Current / peak temp'), UI.el('div', { class: 'value' }, UI.temp(summary.current_temp_c)), UI.el('div', { class: 'sub' }, 'peak ' + UI.temp(summary.max_temp_c))]),
      ]),
    ]);
  }

  function openEdit(s) {
    const qtyInput = UI.el('input', { type: 'number', value: s.qty_kg });
    const valueInput = UI.el('input', { type: 'number', value: Math.round(s.declared_value_inr) });
    const carrierInput = UI.el('input', { type: 'text', value: s.carrier || '' });
    const receiverInput = UI.el('input', { type: 'text', value: s.receiver || '' });
    const err = UI.el('div', { class: 'hint', style: 'color:var(--red);min-height:16px' });
    const body = UI.el('div', {}, [
      UI.el('div', { class: 'hint', style: 'margin-bottom:12px' },
        'Lane, commodity, departure time, and scenario are fixed once a shipment is created (like a real waybill) - ' +
        'you can edit operational details below, or create a new shipment if the trip itself needs to change.'),
      UI.el('div', { class: 'field-row' }, [
        UI.el('div', { class: 'field' }, [UI.el('label', {}, 'Quantity, kg'), qtyInput]),
        UI.el('div', { class: 'field' }, [UI.el('label', {}, 'Declared value, INR'), valueInput]),
      ]),
      UI.el('div', { class: 'field-row' }, [
        UI.el('div', { class: 'field' }, [UI.el('label', {}, 'Carrier'), carrierInput]),
        UI.el('div', { class: 'field' }, [UI.el('label', {}, 'Receiver'), receiverInput]),
      ]),
      err,
      UI.el('button', { class: 'btn btn-primary', style: 'width:100%', onclick: submit }, 'Save changes'),
    ]);
    const close = UI.modal('Edit shipment', body);
    async function submit() {
      try {
        await API.patch(`/api/shipments/${s.id}`, {
          qty_kg: Number(qtyInput.value), declared_value_inr: Number(valueInput.value),
          carrier: carrierInput.value, receiver: receiverInput.value,
        });
        close(); await render(s.id); Fleet.load();
        UI.toast('Shipment updated');
      } catch (e) { err.textContent = e.message; }
    }
  }

  function confirmDelete(s) {
    const body = UI.el('div', {}, [
      UI.el('div', { class: 'hint', style: 'margin-bottom:14px' },
        `Delete ${s.code}? This only works while no telemetry has been sealed into the tamper-evident ` +
        'ledger yet - once real readings are recorded, the shipment is part of the audit trail and can\'t be deleted.'),
      UI.el('button', { class: 'btn btn-danger', style: 'width:100%', onclick: doDelete }, 'Delete shipment'),
    ]);
    const close = UI.modal('Delete shipment', body);
    async function doDelete() {
      try {
        await API.del(`/api/shipments/${s.id}`);
        close(); current = null; Fleet.load();
        document.getElementById('main').replaceChildren(UI.el('div', { class: 'empty' }, 'Shipment deleted. Select another, or create a new one.'));
      } catch (e) { UI.toast(e.message, 'crit'); }
    }
  }

  function advanceControls(id) {
    const playBtn = UI.el('button', { class: 'btn btn-sm' + (playTimer ? ' btn-primary' : ''), onclick: togglePlay }, playTimer ? '⏸ Pause' : '▶ Auto-play');
    function togglePlay() {
      if (playTimer) { clearInterval(playTimer); playTimer = null; playBtn.textContent = '▶ Auto-play'; playBtn.classList.remove('btn-primary'); return; }
      playBtn.textContent = '⏸ Pause'; playBtn.classList.add('btn-primary');
      playTimer = setInterval(async () => {
        const r = await API.post(`/api/shipments/${id}/advance`, { n: 6 });
        Fleet.load();
        if (current === id) await render(id);
        if (r.done) { clearInterval(playTimer); playTimer = null; }
      }, 1500);
    }
    return UI.el('div', { class: 'flex gap-6' }, [
      UI.el('button', { class: 'btn btn-sm', onclick: async () => { await API.post(`/api/shipments/${id}/advance`, { n: 6 }); await render(id); Fleet.load(); } }, '+1h'),
      playBtn,
      UI.el('button', { class: 'btn btn-sm btn-primary', onclick: async () => { await API.post(`/api/shipments/${id}/fast-forward`); await render(id); Fleet.load(); } }, '⏭ Fast-forward to end'),
    ]);
  }

  function subtabs() {
    const tabs = [['overview', 'Overview'], ['timeline', 'Timeline'], ['ledger', 'Ledger'], ['attribution', 'Liability']];
    return UI.el('div', { class: 'tabs', style: 'margin-bottom:12px' }, tabs.map(([k, label]) =>
      UI.el('div', { class: 'tab' + (sub === k ? ' active' : ''), onclick: () => { sub = k; render(current); } }, label)));
  }

  async function renderSub(body, s, com, evts, alerts, actions, summary) {
    UI.clear(body);
    if (sub === 'overview') return await renderOverview(body, s, com, alerts, actions);
    if (sub === 'timeline') return renderTimeline(body, s);
    if (sub === 'ledger') return renderLedger(body, s);
    if (sub === 'attribution') return renderAttribution(body, s);
  }

  async function renderOverview(body, s, com, alerts, actions) {
    const grid = UI.el('div', { class: 'grid2' });
    const left = UI.el('div', {});
    left.appendChild(UI.el('div', { class: 'section' }, [UI.el('h3', {}, 'Route'), UI.el('div', { id: 'map', class: 'card' })]));
    left.appendChild(UI.el('div', { class: 'section' }, [UI.el('h3', {}, 'Cargo temperature vs. allowed band'),
      UI.el('div', { class: 'card', style: 'height:260px;padding:10px' }, UI.el('canvas', { id: 'chart' }))]));
    const right = UI.el('div', {});
    const openActions = actions.filter(a => a.status === 'proposed');
    if (openActions.length) {
      right.appendChild(UI.el('div', { class: 'section' }, [UI.el('h3', {}, 'Pending decisions'), ...openActions.map(actionCard)]));
    }
    right.appendChild(UI.el('div', { class: 'section' }, [UI.el('h3', {}, `Alerts (${alerts.length})`), alertsTable(alerts)]));
    right.appendChild(UI.el('div', { class: 'section' }, [UI.el('h3', {}, 'Agent activity'), UI.el('div', { id: 'agent-runs' }, 'Loading…')]));
    grid.appendChild(left); grid.appendChild(right);
    body.appendChild(grid);

    MapView.destroy();
    await MapView.ensure('map');
    API.get(`/api/shipments/${s.id}/route`).then(r => {
      route = r;
      MapView.drawRoute(r.points, lane ? lane.dest : null);
      const last = readings[readings.length - 1];
      if (last) MapView.setTruck(last.lat, last.lon, last.temp_c > com.t_max || last.temp_c < com.t_min ? '#dc2626' : '#0d9488');
    });
    Telemetry.destroy();
    Telemetry.render(document.getElementById('chart'), readings.slice(-300), { t_min: com.t_min, t_max: com.t_max });
    loadAgentRuns(s.id);
  }

  function actionCard(a) {
    const p = a.proposal;
    const exp = p.explanation || {};
    return UI.el('div', { class: 'action-card kind-' + a.kind, style: 'margin-bottom:10px' }, [
      UI.el('h4', {}, exp.headline || a.kind),
      UI.el('div', { class: 'rationale' }, exp.rationale || ''),
      exp.driver_instruction ? UI.el('div', { class: 'hint', style: 'margin-bottom:8px' }, `Driver instruction: “${exp.driver_instruction}”`) : null,
      UI.el('div', { class: 'row' }, [
        UI.el('button', { class: 'btn btn-primary btn-sm', onclick: () => decide(a.id, true) }, 'Approve'),
        UI.el('button', { class: 'btn btn-danger btn-sm', onclick: () => decide(a.id, false) }, 'Reject'),
      ]),
      UI.el('div', { class: 'badge-src ' + (p.explained_by === 'llm' ? 'llm' : ''), style: 'margin-top:8px;display:inline-block' }, p.explained_by === 'llm' ? 'explained by LLM (grounding-checked)' : 'template explanation'),
    ]);
  }

  async function decide(actionId, approve) {
    try { await API.post(`/api/actions/${actionId}/decide`, { approve }); UI.toast(approve ? 'Approved' : 'Rejected', 'ok'); await render(current); Fleet.load(); }
    catch (e) { UI.toast(e.message, 'crit'); }
  }

  function alertsTable(alerts) {
    if (!alerts.length) return UI.el('div', { class: 'empty' }, 'No alerts.');
    const rows = alerts.slice().reverse().slice(0, 12).map(a => UI.el('tr', {}, [
      UI.el('td', { class: 'mono' }, UI.timeOnly(a.ts)),
      UI.el('td', {}, UI.el('span', { class: 'led ' + UI.sevClass(a.severity) })),
      UI.el('td', {}, a.kind.replace(/_/g, ' ')),
      UI.el('td', {}, a.message),
      UI.el('td', {}, a.status),
    ]));
    return UI.el('table', { class: 'data' }, [UI.el('thead', {}, UI.el('tr', {}, ['time', '', 'kind', 'message', 'status'].map(h => UI.el('th', {}, h)))), UI.el('tbody', {}, rows)]);
  }

  async function loadAgentRuns(id) {
    const runs = await API.get(`/api/shipments/${id}/agent-runs`);
    const box = document.getElementById('agent-runs');
    if (!box) return;
    UI.clear(box);
    if (!runs.length) { box.appendChild(UI.el('div', { class: 'empty' }, 'No agent runs yet — the monitoring agent runs automatically when an alert fires (e.g. a temperature breach), and the dispute agents run when a dispute is filed on this shipment.')); return; }
    for (const r of runs.slice(0, 3)) {
      const wrap = UI.el('div', { class: 'card', style: 'padding:10px;margin-bottom:8px' });
      wrap.appendChild(UI.el('div', { class: 'flex justify-between' }, [UI.el('b', { style: 'font-size:12.5px' }, `${r.kind} run #${r.id}`), UI.el('span', { class: 'hint' }, r.status)]));
      for (const st of (r.steps || [])) {
        wrap.appendChild(UI.el('div', { class: 'agent-step ' + st.type }, [
          UI.el('div', { class: 'kind' }, `${st.type} · ${st.name}${st.ms !== undefined ? ' · ' + st.ms + 'ms' : ''}`),
          st.note ? UI.el('div', { class: 'hint' }, st.note) : null,
        ]));
      }
      box.appendChild(wrap);
    }
  }

  function renderTimeline(body, s) {
    body.appendChild(UI.el('h3', {}, 'Evidence-linked timeline'));
    const box = UI.el('div', { class: 'timeline' });
    body.appendChild(box);
    API.get(`/api/shipments/${s.id}/agent-runs`); // warm cache
    fetch(`/api/shipments/${s.id}/attribution`); // not used here directly
    API.get(`/api/shipments/${s.id}`).then(async () => {
      const items = await fetchTimeline(s.id);
      UI.clear(box);
      for (const it of items) {
        box.appendChild(UI.el('div', { class: 'tl-item k-' + it.kind }, [UI.el('div', { class: 'ts' }, UI.dt(it.ts)), UI.el('div', { class: 'label' }, it.label)]));
      }
    });
  }
  async function fetchTimeline(id) {
    // build_timeline is exposed only via the attribution/dispute path in this API surface;
    // reconstruct the same view client-side from events + alerts for direct browsing.
    const [evts, alerts] = await Promise.all([API.get(`/api/shipments/${id}/events`), API.get(`/api/shipments/${id}/alerts`)]);
    const items = evts.map(e => ({ ts: e.ts, kind: 'custody', label: `[${e.party}] ${e.event.replace(/_/g, ' ')}: ${e.note || ''}` }))
      .concat(alerts.map(a => ({ ts: a.ts, kind: 'alert', label: `Alert (${a.severity}): ${a.message}` })));
    return items.sort((a, b) => a.ts.localeCompare(b.ts));
  }

  async function renderLedger(body, s) {
    body.appendChild(UI.el('h3', {}, 'Tamper-evident ledger'));
    const v = await API.get(`/api/shipments/${s.id}/ledger`);
    const status = v.ok ? UI.el('div', { class: 'pill ok' }, '✓ verified — no tampering detected') : UI.el('div', { class: 'pill crit' }, `✗ tampering detected at block ${v.first_broken_height}`);
    body.appendChild(UI.el('div', { class: 'section' }, [status,
      UI.el('div', { class: 'hint', style: 'margin-top:8px' }, `${v.n_blocks} sealed blocks · ${v.pending_readings} readings not yet sealed · head hash `),
      UI.el('div', { class: 'mono hint' }, v.head_hash),
    ]));
    const rows = v.blocks.map(b => UI.el('tr', {}, [
      UI.el('td', {}, b.height), UI.el('td', {}, `${b.first_seq}–${b.last_seq}`),
      UI.el('td', {}, UI.el('span', { class: 'led ' + (b.ok ? 'ok' : 'crit') })),
      UI.el('td', { class: 'mono', style: 'font-size:11px' }, b.block_hash.slice(0, 20) + '…'),
      UI.el('td', {}, b.reasons.join('; ') || '—'),
    ]));
    body.appendChild(UI.el('table', { class: 'data' }, [
      UI.el('thead', {}, UI.el('tr', {}, ['height', 'seq range', 'ok', 'block hash', 'issue'].map(h => UI.el('th', {}, h)))),
      UI.el('tbody', {}, rows),
    ]));
  }

  async function renderAttribution(body, s) {
    body.appendChild(UI.el('h3', {}, 'Liability apportionment (counterfactual replay)'));
    const a = await API.get(`/api/shipments/${s.id}/attribution`);
    if (!a.totals) { body.appendChild(UI.el('div', { class: 'empty' }, 'Not enough verified readings yet.')); return; }
    body.appendChild(UI.el('div', { class: 'grid3', style: 'margin-bottom:14px' }, [
      UI.el('div', { class: 'card stat' }, [UI.el('div', { class: 'label' }, 'Assessed loss'), UI.el('div', { class: 'value' }, UI.pct(a.totals.loss_pct)), UI.el('div', { class: 'sub' }, UI.inr(a.totals.loss_inr))]),
      UI.el('div', { class: 'card stat' }, [UI.el('div', { class: 'label' }, 'Ledger'), UI.el('div', { class: 'value', style: 'font-size:15px' }, a.evidence.ledger_ok ? 'Verified' : 'Tampered'), UI.el('div', { class: 'sub' }, `${a.evidence.readings_verified}/${a.evidence.readings_total} readings used`)]),
      UI.el('div', { class: 'card stat' }, [UI.el('div', { class: 'label' }, 'Findings'), UI.el('div', { class: 'value' }, a.findings.length)]),
    ]));
    const partyRows = Object.entries(a.parties).map(([party, p]) => UI.el('tr', {}, [
      UI.el('td', {}, party), UI.el('td', {}, p.share_pct + '%'), UI.el('td', {}, p.minutes), UI.el('td', {}, UI.inr(p.amount_inr)), UI.el('td', {}, p.capped ? 'yes' : ''),
    ]));
    body.appendChild(UI.el('div', { class: 'section' }, [UI.el('h3', {}, 'By party'), UI.el('table', { class: 'data' }, [
      UI.el('thead', {}, UI.el('tr', {}, ['party', 'share', 'minutes', 'amount', 'capped'].map(h => UI.el('th', {}, h)))),
      UI.el('tbody', {}, partyRows),
    ])]));
    const findBox = UI.el('div', { class: 'section' });
    findBox.appendChild(UI.el('h3', {}, 'Findings'));
    for (const f of a.findings) {
      findBox.appendChild(UI.el('div', { class: 'card', style: 'padding:10px;margin-bottom:8px' }, [
        UI.el('div', { class: 'flex justify-between' }, [UI.el('b', {}, `${f.id} · ${f.party}`), UI.el('span', { class: 'pill' }, f.clause ? 'SLA ' + f.clause : 'no clause')]),
        UI.el('div', { style: 'margin-top:4px;font-size:13px' }, f.description),
        UI.el('div', { class: 'hint', style: 'margin-top:4px' }, `${f.share_pct}% of loss · ${f.minutes} min · readings ${JSON.stringify(f.seq_ranges)}`),
      ]));
    }
    body.appendChild(findBox);
    body.appendChild(UI.el('div', { class: 'hint' }, a.assumptions.map(x => '• ' + x).join('  ')));
  }

  function onLive(msg) {
    if (!current || msg.shipment_id !== current) return;
    if (sub === 'overview') render(current);
  }

  return { render, onLive, current: () => current, stopPlay };
})();
