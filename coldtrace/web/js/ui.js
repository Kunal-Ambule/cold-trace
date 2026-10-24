// Small DOM + formatting helpers shared by every view.
const UI = (() => {
  function el(tag, attrs = {}, children = []) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'class') e.className = v;
      else if (k === 'html') e.innerHTML = v;
      else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined) e.setAttribute(k, v);
    }
    for (const c of [].concat(children)) {
      if (c === null || c === undefined) continue;
      e.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return e;
  }
  function inr(n) { if (n === null || n === undefined) return '—'; return '₹' + Math.round(n).toLocaleString('en-IN'); }
  function temp(n) { return (n === null || n === undefined) ? '—' : n.toFixed(1) + '°C'; }
  function pct(n) { return (n === null || n === undefined) ? '—' : n.toFixed(2) + '%'; }
  function dt(ts) { if (!ts) return '—'; const d = new Date(ts); return d.toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }); }
  function timeOnly(ts) { if (!ts) return '—'; return new Date(ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false }); }
  function sevClass(sev) { return sev === 'critical' ? 'crit' : sev === 'warning' ? 'warn' : sev === 'info' ? 'info' : 'ok'; }
  function riskClass(r) { return r === 'critical' ? 'crit' : (r === 'high' || r === 'moderate') ? 'warn' : 'ok'; }
  function toast(msg, sev = 'info') {
    const wrap = document.getElementById('toast-wrap');
    const t = el('div', { class: 'toast ' + sevClass(sev) }, msg);
    wrap.appendChild(t);
    setTimeout(() => t.remove(), 6500);
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function modal(title, bodyNode, { wide = false } = {}) {
    const root = document.getElementById('modal-root');
    clear(root);
    const close = () => clear(root);
    const card = el('div', { class: 'card modal', style: wide ? 'width:min(820px,94vw)' : '' }, [
      el('div', { class: 'modal-head' }, [el('h3', {}, title), el('button', { class: 'btn btn-ghost btn-sm', onclick: close }, '✕')]),
      el('div', { class: 'modal-body' }, bodyNode),
    ]);
    const backdrop = el('div', { class: 'modal-backdrop', onclick: (e) => { if (e.target === backdrop) close(); } }, card);
    root.appendChild(backdrop);
    return close;
  }
  return { el, inr, temp, pct, dt, timeOnly, sevClass, riskClass, toast, clear, modal };
})();
