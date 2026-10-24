const DisputesView = (() => {
  async function render() {
    const main = document.getElementById('main');
    UI.clear(main);
    document.getElementById('rail').style.display = 'none';
    document.getElementById('feed').style.display = 'none';
    const [disputes, shipments] = await Promise.all([API.get('/api/disputes'), API.get('/api/shipments')]);
    main.appendChild(UI.el('div', { class: 'flex justify-between items-center section' }, [
      UI.el('h2', {}, 'Disputes'),
      UI.el('button', { class: 'btn btn-primary btn-sm', onclick: () => openNew(shipments) }, '+ File dispute'),
    ]));
    const list = UI.el('div', {});
    main.appendChild(list);
    if (!disputes.length) list.appendChild(UI.el('div', { class: 'empty' }, 'No disputes filed yet.'));
    for (const d of disputes) {
      list.appendChild(UI.el('div', { class: 'card', style: 'padding:12px;margin-bottom:10px;cursor:pointer', onclick: () => openReport(d.id) }, [
        UI.el('div', { class: 'flex justify-between' }, [
          UI.el('b', {}, `#${d.id} · ${d.shipment_code}`),
          UI.el('span', { class: 'pill ' + (d.status === 'resolved' ? 'ok' : d.status === 'error' ? 'crit' : 'warn') }, d.status),
        ]),
        UI.el('div', { class: 'hint', style: 'margin-top:4px' }, `${d.claimant} vs ${d.respondent || '—'} · filed ${UI.dt(d.created_at)}`),
        d.description ? UI.el('div', { style: 'margin-top:6px;font-size:13px' }, d.description) : null,
      ]));
    }
  }

  function openNew(shipments) {
    if (!shipments.length) {
      UI.modal('New dispute', UI.el('div', { class: 'empty' }, 'No shipments yet — create one on the Fleet tab first.'));
      return;
    }
    const shipSel = UI.el('select', {}, shipments.map(s => UI.el('option', { value: s.id }, s.code)));
    const readyHint = UI.el('div', { class: 'hint', style: 'margin-top:4px' }, '');
    async function refreshReadyHint() {
      readyHint.textContent = 'Checking telemetry…';
      try {
        const v = await API.get(`/api/shipments/${shipSel.value}/ledger`);
        const verified = v.blocks.filter(b => b.ok).reduce((n, b) => n + (b.last_seq - b.first_seq + 1), 0);
        readyHint.textContent = verified >= 3
          ? `${verified} verified reading(s) sealed - ready to apportion liability.`
          : `Only ${verified} verified reading(s) sealed so far (need at least 3). Advance the shipment on the ` +
            'Fleet tab before filing, or file now to record the claim and recompute later.';
      } catch { readyHint.textContent = ''; }
    }
    shipSel.addEventListener('change', refreshReadyHint);
    refreshReadyHint();
    const claimant = UI.el('input', { type: 'text', value: 'Wholesale buyer' });
    const respondent = UI.el('input', { type: 'text', value: 'Regional reefer carrier' });
    const desc = UI.el('textarea', { rows: 3, style: 'width:100%' }, 'Cargo arrived outside the agreed temperature band.');
    const err = UI.el('div', { class: 'hint', style: 'color:var(--red)' });
    const body = UI.el('div', {}, [
      UI.el('div', { class: 'field' }, [UI.el('label', {}, 'Shipment'), shipSel, readyHint]),
      UI.el('div', { class: 'field-row' }, [
        UI.el('div', { class: 'field' }, [UI.el('label', {}, 'Claimant'), claimant]),
        UI.el('div', { class: 'field' }, [UI.el('label', {}, 'Respondent'), respondent]),
      ]),
      UI.el('div', { class: 'field' }, [UI.el('label', {}, 'Description'), desc]),
      err,
      UI.el('button', { class: 'btn btn-primary', style: 'width:100%', onclick: submit }, 'File and run dispute agents'),
    ]);
    const close = UI.modal('New dispute', body);
    async function submit() {
      try {
        const d = await API.post('/api/disputes', { shipment_id: Number(shipSel.value), claimant: claimant.value, respondent: respondent.value, description: desc.value });
        close(); UI.toast('Dispute filed — agents are processing', 'ok');
        setTimeout(() => openReport(d.id), 2500);
        render();
      } catch (e) { err.textContent = e.message; }
    }
  }

  async function openReport(id, attempt = 0) {
    const d = await API.get(`/api/disputes/${id}`);
    if (d.status === 'processing' && attempt < 15) { setTimeout(() => openReport(id, attempt + 1), 1000); return; }
    if (d.status === 'error') {
      UI.modal(`Dispute #${id} — ${d.shipment_code || ''}`, UI.el('div', { class: 'empty', style: 'color:var(--red)' },
        'The dispute agents hit an error processing this shipment. Try Recompute from the list once the underlying issue is fixed.'));
      return;
    }
    const r = d.report;
    if (!r) { UI.modal(`Dispute #${id}`, UI.el('div', { class: 'empty' }, 'Still processing…')); return; }
    const findRows = r.findings.map(f => UI.el('div', { class: 'card', style: 'padding:10px;margin-bottom:8px' }, [
      UI.el('div', { class: 'flex justify-between' }, [UI.el('b', {}, `${f.id} · ${f.party}`), UI.el('span', { class: 'pill' }, f.clause ? 'SLA ' + f.clause : '—')]),
      UI.el('div', { style: 'margin-top:4px;font-size:13px' }, f.narrative),
    ]));
    const body = UI.el('div', {}, [
      UI.el('div', { class: 'pill ' + (r.evidence.ledger.ok ? 'ok' : 'crit'), style: 'margin-bottom:10px' }, r.evidence.ledger.ok ? 'Ledger verified' : 'Tampering detected'),
      UI.el('p', {}, r.summary),
      UI.el('p', { class: 'hint' }, r.recommendation),
      UI.el('div', { class: 'hr' }),
      ...findRows,
      UI.el('div', { class: 'flex gap-8', style: 'margin-top:10px' }, [
        UI.el('a', { class: 'btn btn-sm', href: `/api/disputes/${id}/docket.pdf?token=${API.getToken()}`, target: '_blank' }, 'Download PDF docket'),
        UI.el('button', { class: 'btn btn-sm', onclick: async () => { await API.post(`/api/disputes/${id}/recompute`); UI.toast('Recomputed'); openReport(id); } }, 'Recompute'),
      ]),
    ]);
    UI.modal(`Dispute #${id} — ${d.shipment_code || ''}`, body, { wide: true });
  }

  return { render };
})();
