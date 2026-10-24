const AdminView = (() => {
  async function render() {
    const main = document.getElementById('main');
    UI.clear(main);
    document.getElementById('rail').style.display = 'none';
    document.getElementById('feed').style.display = 'none';
    main.appendChild(UI.el('h2', { class: 'section' }, 'Data sources & model status'));
    const status = await API.get('/api/ref/data-status');
    const box = UI.el('div', { class: 'grid3 section' }, [
      UI.el('div', { class: 'card stat' }, [UI.el('div', { class: 'label' }, 'Mandi price listings'), UI.el('div', { class: 'value' }, status.prices.listings), UI.el('div', { class: 'sub' }, `${status.prices.commodities} commodities · ${status.prices.states} states · ${status.prices.source}`)]),
      UI.el('div', { class: 'card stat' }, [UI.el('div', { class: 'label' }, 'Weather (ERA5 reanalysis)'), UI.el('div', { class: 'value' }, status.weather.ready ? 'Loaded' : 'Missing'), UI.el('div', { class: 'sub' }, `${status.weather.stations_loaded}/${status.weather.stations_needed} stations · ${status.weather.from || ''} → ${status.weather.to || ''}`)]),
      UI.el('div', { class: 'card stat' }, [
        UI.el('div', { class: 'label' }, 'Local LLM (Ollama)'),
        UI.el('div', { class: 'value', style: 'font-size:16px' }, status.llm.available ? 'Connected' : 'Not connected'),
        UI.el('div', { class: 'sub' }, status.llm.detail || status.llm.model),
        !status.llm.available ? UI.el('div', { class: 'hint', style: 'margin-top:6px' },
          'Optional - agents fall back to clear template text without it. To enable plain-language narration, ' +
          'install Ollama from ollama.com, run "ollama pull llama3.2:3b", then "ollama serve", and reload this page.') : null,
      ]),
    ]);
    main.appendChild(box);

    main.appendChild(UI.el('h3', { class: 'section' }, 'ML model card'));
    const cardBox = UI.el('div', { class: 'card', style: 'padding:14px' });
    main.appendChild(cardBox);
    function renderCard() {
      UI.clear(cardBox);
      if (!status.model) { cardBox.appendChild(UI.el('div', { class: 'empty' }, 'No model trained yet.')); return; }
      const m = status.model;
      cardBox.appendChild(UI.el('pre', { class: 'mono', style: 'white-space:pre-wrap;font-size:11.5px;color:var(--text-dim);max-height:420px;overflow:auto' }, JSON.stringify(m, null, 2)));
    }
    renderCard();
    main.appendChild(UI.el('div', { class: 'flex gap-8 section' }, [
      UI.el('button', { class: 'btn', onclick: async () => { UI.toast('Fetching weather (ERA5)…'); await API.post('/api/ml/fetch-weather'); UI.toast('Weather refreshed', 'ok'); render(); } }, 'Fetch weather'),
      UI.el('button', { class: 'btn btn-primary', onclick: async () => { await API.post('/api/ml/train', {}); UI.toast('Training started — check back shortly'); } }, 'Train / retrain model'),
    ]));
  }
  return { render };
})();
