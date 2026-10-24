// Chart.js wrapper for the temperature-vs-band chart on a shipment's detail page.
const Telemetry = (() => {
  let chart;
  function render(canvas, readings, band) {
    const labels = readings.map(r => r.ts);
    const temps = readings.map(r => r.temp_c);
    const amb = readings.map(r => r.ambient_c);
    if (chart) chart.destroy();
    chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [
          { label: 'Cargo temp', data: temps, borderColor: '#0d9488', backgroundColor: 'transparent', tension: 0.25, pointRadius: 0, borderWidth: 2.5 },
          { label: 'Ambient', data: amb, borderColor: '#94a3b8', backgroundColor: 'transparent', tension: 0.25, pointRadius: 0, borderWidth: 1.5, borderDash: [3, 3] },
          { label: 'Max band', data: labels.map(() => band.t_max), borderColor: '#dc262699', pointRadius: 0, borderWidth: 1.5 },
          { label: 'Min band', data: labels.map(() => band.t_min), borderColor: '#dc262699', pointRadius: 0, borderWidth: 1.5 },
        ],
      },
      options: {
        animation: false, responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { labels: { color: '#475569', boxWidth: 12, font: { size: 11 } } } },
        scales: {
          x: { ticks: { color: '#64748b', maxTicksLimit: 8, font: { size: 10 } }, grid: { color: '#e2e8f0' } },
          y: { ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: '#e2e8f0' } },
        },
      },
    });
  }
  function destroy() { if (chart) { chart.destroy(); chart = null; } }
  return { render, destroy };
})();
