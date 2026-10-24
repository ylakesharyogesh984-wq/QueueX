Chart.defaults.color = '#94A3B8';
Chart.defaults.font.family = 'Inter';

let counterChart, peakChart;

function loadOverview() {
  fetch('/api/admin/overview')
    .then(res => {
      if (!res.ok) throw new Error('Unable to load overview');
      return res.json();
    })
    .then(data => {
      const grid = document.getElementById('overview-grid');
      grid.innerHTML = '';
      data.forEach(c => {
        const card = document.createElement('div');
        card.className = 'card overview-card';

        const title = document.createElement('h4');
        title.textContent = c.name;

        const current = document.createElement('div');
        current.className = 'big';
        current.textContent = '#' + c.current_token;

        const sub = document.createElement('div');
        sub.className = 'sub';
        sub.textContent = `${c.waiting_count} waiting · ${c.served_today} served today`;

        card.append(title, current, sub);
        grid.appendChild(card);
      });
    })
    .catch(console.error);
}

function loadAnalytics() {
  fetch('/api/admin/analytics')
    .then(res => {
      if (!res.ok) throw new Error('Unable to load analytics');
      return res.json();
    })
    .then(data => {
      document.getElementById('stat-total').textContent = data.total_today;
      document.getElementById('stat-wait').textContent = data.avg_wait + 'm';
      document.getElementById('stat-busiest').textContent = data.busiest_counter;

      const counterLabels = data.tokens_per_counter.map(x => x.name);
      const counterCounts = data.tokens_per_counter.map(x => x.count);

      if (counterChart) counterChart.destroy();
      counterChart = new Chart(document.getElementById('counterChart'), {
        type: 'bar',
        data: {
          labels: counterLabels,
          datasets: [{
            label: 'Tokens',
            data: counterCounts,
            backgroundColor: '#6366F1',
            borderRadius: 6
          }]
        },
        options: {
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { display: false } },
            y: { grid: { color: '#1B2540' }, beginAtZero: true, ticks: { stepSize: 1 } }
          }
        }
      });

      const peakLabels = data.peak_hours.map(x => x.hour);
      const peakCounts = data.peak_hours.map(x => x.count);

      if (peakChart) peakChart.destroy();
      peakChart = new Chart(document.getElementById('peakChart'), {
        type: 'line',
        data: {
          labels: peakLabels,
          datasets: [{
            label: 'Tokens',
            data: peakCounts,
            borderColor: '#FBBF24',
            backgroundColor: 'rgba(251,191,36,0.1)',
            fill: true,
            tension: 0.35
          }]
        },
        options: {
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { display: false } },
            y: { grid: { color: '#1B2540' }, beginAtZero: true, ticks: { stepSize: 1 } }
          }
        }
      });
    })
    .catch(console.error);
}

loadOverview();
loadAnalytics();
setInterval(() => { loadOverview(); loadAnalytics(); }, 5000);
