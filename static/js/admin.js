// QueueX Super Admin Command Center Controller
if (typeof Chart !== 'undefined') {
  Chart.defaults.color = '#94A3B8';
  Chart.defaults.font.family = "'Inter', -apple-system, sans-serif";
}

let counterChart = null;
let peakChart = null;
let statusChart = null;
let deptChart = null;

let allStudents = [];
let allEmployees = [];
let allCounters = [];
let allComplaints = [];

let currentDateFilter = 'today';

// Toast notifications
function showToast(message, type = 'info') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.classList.add('show'), 10);
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// Escape HTML for XSS prevention
function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Date Filter Controller
function setDateFilter(filterVal) {
  currentDateFilter = filterVal;

  // Update button active state
  document.querySelectorAll('.date-pill-btn').forEach(btn => {
    if (btn.getAttribute('data-date') === filterVal) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });

  // Human friendly label
  let labelText = 'Today';
  if (filterVal === 'today') labelText = 'Today';
  else if (filterVal === 'yesterday') labelText = 'Yesterday';
  else if (filterVal === '7days') labelText = 'Last 7 Days';
  else if (filterVal === '30days') labelText = 'Last 30 Days';
  else if (filterVal === 'all') labelText = 'All Time';
  else labelText = filterVal;

  document.querySelectorAll('.period-label').forEach(el => {
    el.textContent = labelText;
  });

  loadOverview();
  loadAnalytics();
}

function refreshCurrentView() {
  loadOverview();
  loadAnalytics();
  loadCounters();
  loadStudents();
  loadEmployees();
  loadComplaints();
  showToast('Dashboard data updated', 'info');
}

// 1. Overview & Telemetry Cards
function loadOverview() {
  fetch(`/api/admin/overview?date=${encodeURIComponent(currentDateFilter)}`)
    .then(res => {
      if (!res.ok) throw new Error('Unable to load overview');
      return res.json();
    })
    .then(data => {
      const counters = Array.isArray(data) ? data : (data.counters || []);
      const kpis = data.kpis || {};

      // Campus Assets KPIs
      const studTotal = document.getElementById('stat-students-total');
      if (studTotal) studTotal.textContent = kpis.total_students ?? 0;

      const studSub = document.getElementById('stat-students-sub');
      if (studSub) studSub.textContent = `${kpis.active_students ?? 0} verified active`;

      const opTotal = document.getElementById('stat-operators-total');
      if (opTotal) opTotal.textContent = kpis.total_employees ?? 0;

      const opSub = document.getElementById('stat-operators-sub');
      if (opSub) opSub.textContent = `${kpis.active_employees ?? 0} assigned active`;

      const counterTotal = document.getElementById('stat-counters');
      if (counterTotal) counterTotal.textContent = kpis.active_counters ?? counters.length;

      const counterSub = document.getElementById('stat-counters-sub');
      if (counterSub) counterSub.textContent = `${kpis.total_counters ?? counters.length} operational stations`;

      const complaintTotal = document.getElementById('stat-complaints-count');
      if (complaintTotal) complaintTotal.textContent = kpis.pending_complaints ?? 0;

      // Period Token Throughput KPIs
      const totalIssued = document.getElementById('stat-total');
      if (totalIssued) totalIssued.textContent = kpis.total_tokens_period ?? 0;

      const waitingEl = document.getElementById('stat-waiting');
      if (waitingEl) waitingEl.textContent = kpis.waiting_tokens ?? 0;

      const servedEl = document.getElementById('stat-served');
      if (servedEl) servedEl.textContent = kpis.served_tokens ?? 0;

      const waitEl = document.getElementById('stat-wait');
      if (waitEl) waitEl.textContent = (kpis.avg_wait ?? 0) + 'm';

      // Telemetry Station Grid
      const grid = document.getElementById('overview-grid');
      if (grid) {
        grid.innerHTML = '';
        if (counters.length === 0) {
          grid.innerHTML = '<div class="empty-state" style="grid-column: 1 / -1;"><p>No operational counters found.</p></div>';
        } else {
          counters.forEach(c => {
            const card = document.createElement('div');
            card.className = 'card overview-card';

            const statusClass = c.status === 'open' ? 'badge-status-open' : (c.status === 'paused' ? 'badge-status-paused' : 'badge-status-closed');
            const statusLabel = (c.status || 'open').toUpperCase();

            card.innerHTML = `
              <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px;">
                <h4 style="margin:0; font-size:15px;">${escapeHtml(c.name)}</h4>
                <span class="badge ${statusClass}" style="font-size:10px; padding:2px 8px;">${statusLabel}</span>
              </div>
              <div class="big" style="font-size:30px; margin: 4px 0;">#${escapeHtml(c.current_token || '-')}</div>
              <div class="sub">
                <strong>${c.waiting_count || 0}</strong> waiting · <strong>${c.served_today || 0}</strong> served
              </div>
              <div style="font-size:11.5px; color:var(--text-muted); margin-top:8px; border-top:1px solid var(--glass-border); padding-top:6px;">
                📍 ${escapeHtml(c.location || 'Main Block')}
              </div>
            `;
            grid.appendChild(card);
          });
        }
      }
    })
    .catch(console.error);
}

// 2. Deep Telemetry & Analytics Charts
function loadAnalytics() {
  fetch(`/api/admin/analytics?date=${encodeURIComponent(currentDateFilter)}`)
    .then(res => {
      if (!res.ok) throw new Error('Unable to load analytics');
      return res.json();
    })
    .then(data => {
      const isLight = document.documentElement.getAttribute('data-theme') === 'light';
      const textColor = isLight ? '#475569' : '#94A3B8';
      const gridColor = isLight ? 'rgba(0, 0, 0, 0.06)' : 'rgba(255, 255, 255, 0.08)';

      const busiestSub = document.getElementById('stat-busiest-sub');
      if (busiestSub && data.busiest_counter) {
        busiestSub.textContent = `Peak: ${data.busiest_counter}`;
      }

      // Chart 1: Tokens per Counter (Bar)
      const counterLabels = (data.tokens_per_counter || []).map(x => x.name);
      const counterCounts = (data.tokens_per_counter || []).map(x => x.count);
      const counterCanvas = document.getElementById('counterChart');

      if (counterCanvas && typeof Chart !== 'undefined') {
        if (counterChart) counterChart.destroy();
        counterChart = new Chart(counterCanvas, {
          type: 'bar',
          data: {
            labels: counterLabels,
            datasets: [{
              label: 'Tokens Issued',
              data: counterCounts,
              backgroundColor: '#8B5CF6',
              hoverBackgroundColor: '#A78BFA',
              borderRadius: 8,
              borderSkipped: false
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false },
              tooltip: {
                backgroundColor: 'rgba(15, 23, 42, 0.95)',
                borderColor: 'rgba(255, 255, 255, 0.15)',
                borderWidth: 1,
                padding: 10,
                cornerRadius: 8
              }
            },
            scales: {
              x: { grid: { display: false }, ticks: { color: textColor } },
              y: { grid: { color: gridColor }, beginAtZero: true, ticks: { stepSize: 1, color: textColor } }
            }
          }
        });
      }

      // Chart 2: Peak Hours & Rush (Line)
      const peakLabels = (data.peak_hours || []).map(x => x.hour);
      const peakCounts = (data.peak_hours || []).map(x => x.count);
      const peakCanvas = document.getElementById('peakChart');

      if (peakCanvas && typeof Chart !== 'undefined') {
        if (peakChart) peakChart.destroy();
        peakChart = new Chart(peakCanvas, {
          type: 'line',
          data: {
            labels: peakLabels,
            datasets: [{
              label: 'Rush Volume',
              data: peakCounts,
              borderColor: '#38BDF8',
              borderWidth: 2.5,
              pointBackgroundColor: '#06B6D4',
              pointBorderColor: '#FFFFFF',
              pointRadius: 4,
              pointHoverRadius: 6,
              backgroundColor: 'rgba(56, 189, 248, 0.12)',
              fill: true,
              tension: 0.38
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false },
              tooltip: {
                backgroundColor: 'rgba(15, 23, 42, 0.95)',
                borderColor: 'rgba(255, 255, 255, 0.15)',
                borderWidth: 1,
                padding: 10,
                cornerRadius: 8
              }
            },
            scales: {
              x: { grid: { display: false }, ticks: { color: textColor } },
              y: { grid: { color: gridColor }, beginAtZero: true, ticks: { stepSize: 1, color: textColor } }
            }
          }
        });
      }

      // Chart 3: Token Status Breakdown (Doughnut)
      const statusDist = data.status_distribution || { served: 0, waiting: 0, skipped: 0, cancelled: 0 };
      const statusCanvas = document.getElementById('statusChart');

      if (statusCanvas && typeof Chart !== 'undefined') {
        if (statusChart) statusChart.destroy();
        statusChart = new Chart(statusCanvas, {
          type: 'doughnut',
          data: {
            labels: ['Served', 'Waiting', 'Skipped', 'Cancelled'],
            datasets: [{
              data: [statusDist.served || 0, statusDist.waiting || 0, statusDist.skipped || 0, statusDist.cancelled || 0],
              backgroundColor: ['#10B981', '#06B6D4', '#F59E0B', '#EF4444'],
              borderWidth: 2,
              borderColor: isLight ? '#FFFFFF' : '#0F172A'
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: {
                position: 'right',
                labels: { color: textColor, boxWidth: 12, padding: 14 }
              },
              tooltip: {
                backgroundColor: 'rgba(15, 23, 42, 0.95)',
                borderColor: 'rgba(255, 255, 255, 0.15)',
                borderWidth: 1,
                padding: 10,
                cornerRadius: 8
              }
            },
            cutout: '68%'
          }
        });
      }

      // Chart 4: Department-Wise Volume (Horizontal Bar)
      const deptLabels = (data.department_analytics || []).map(x => x.department);
      const deptCounts = (data.department_analytics || []).map(x => x.count);
      const deptCanvas = document.getElementById('deptChart');

      if (deptCanvas && typeof Chart !== 'undefined') {
        if (deptChart) deptChart.destroy();
        deptChart = new Chart(deptCanvas, {
          type: 'bar',
          data: {
            labels: deptLabels.length ? deptLabels : ['General Campus'],
            datasets: [{
              label: 'Tokens by Dept',
              data: deptCounts.length ? deptCounts : [0],
              backgroundColor: '#EC4899',
              hoverBackgroundColor: '#F472B6',
              borderRadius: 6,
              borderSkipped: false
            }]
          },
          options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false },
              tooltip: {
                backgroundColor: 'rgba(15, 23, 42, 0.95)',
                borderColor: 'rgba(255, 255, 255, 0.15)',
                borderWidth: 1,
                padding: 10,
                cornerRadius: 8
              }
            },
            scales: {
              x: { grid: { color: gridColor }, beginAtZero: true, ticks: { stepSize: 1, color: textColor } },
              y: { grid: { display: false }, ticks: { color: textColor } }
            }
          }
        });
      }
    })
    .catch(console.error);
}

// 3. Counter & Station Management
function loadCounters() {
  const tbody = document.getElementById('counters-tbody');
  const badgeEl = document.getElementById('counters-badge');

  fetch('/api/admin/counters')
    .then(res => {
      if (!res.ok) throw new Error('Failed to load counters');
      return res.json();
    })
    .then(data => {
      allCounters = data.counters || [];
      const activeCount = allCounters.filter(c => c.status !== 'deactivated').length;
      if (badgeEl) badgeEl.textContent = `${activeCount} OF ${allCounters.length} OPERATIONAL`;
      if (!tbody) return;
      tbody.innerHTML = '';

      if (allCounters.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="table-empty-cell"><p>No counter stations created yet.</p></td></tr>`;
        return;
      }

      allCounters.forEach(c => {
        const tr = document.createElement('tr');

        let statusBadge = '<span class="badge badge-status-open">OPEN</span>';
        if (c.status === 'paused') statusBadge = '<span class="badge badge-status-paused">PAUSED</span>';
        else if (c.status === 'closed') statusBadge = '<span class="badge badge-status-closed">CLOSED</span>';
        else if (c.status === 'deactivated') statusBadge = '<span class="badge badge-status-deactivated">DEACTIVATED</span>';

        const operatorsText = (c.operators && c.operators.length > 0)
          ? c.operators.map(op => `<span class="roll-pill">${escapeHtml(op)}</span>`).join(' ')
          : '<span class="status-muted">Unassigned</span>';

        const isDeactivated = c.status === 'deactivated';
        const toggleDeactBtn = isDeactivated
          ? `<button type="button" class="btn btn-outline btn-sm" onclick="toggleCounterStatus(${c.id}, 'open')">Activate</button>`
          : `<button type="button" class="btn btn-outline btn-sm" onclick="toggleCounterStatus(${c.id}, 'deactivated')">Deactivate</button>`;

        tr.innerHTML = `
          <td>
            <strong>${escapeHtml(c.name)}</strong>
            <div class="roll-pill">slug: ${escapeHtml(c.slug)}</div>
          </td>
          <td>
            <div>📍 ${escapeHtml(c.location || 'Admin Wing')}</div>
            <div style="font-size:12px; color:var(--text-muted);">🕒 ${escapeHtml(c.operating_hours || '09:00 - 17:00')}</div>
          </td>
          <td>${statusBadge}</td>
          <td>
            <div style="font-size:13px;">
              <span style="color:var(--cyan-light); font-weight:600;">${c.waiting_count || 0} waiting</span> · 
              <span style="color:var(--emerald-light); font-weight:600;">${c.served_count || 0} served</span>
            </div>
            <div style="font-size:11.5px; color:var(--text-dim); margin-top:2px;">Serving: #${c.current_token || '-'}</div>
          </td>
          <td>${operatorsText}</td>
          <td>
            <div class="action-btn-group">
              <button type="button" class="btn btn-outline btn-sm" onclick="openEditCounterModal(${c.id})">Edit</button>
              ${toggleDeactBtn}
              <button type="button" class="btn btn-danger btn-sm" onclick="deleteCounter(${c.id}, '${escapeHtml(c.name).replace(/'/g, "\\'")}')">Delete</button>
            </div>
          </td>
        `;
        tbody.appendChild(tr);
      });
    })
    .catch(err => {
      console.error(err);
      if (tbody) tbody.innerHTML = `<tr><td colspan="6" class="table-error-cell">Failed to load counter stations.</td></tr>`;
    });
}

function openAddCounterModal() {
  const modal = document.getElementById('add-counter-modal');
  if (modal) modal.classList.add('open');
}

function closeAddCounterModal() {
  const modal = document.getElementById('add-counter-modal');
  if (modal) modal.classList.remove('open');
}

function submitAddCounter(event) {
  event.preventDefault();
  const form = document.getElementById('add-counter-form');
  if (!form) return;
  const submitBtn = document.getElementById('ac-submit-btn');
  if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Creating...'; }

  const formData = new FormData(form);
  fetch('/api/admin/counters/add', { method: 'POST', body: formData })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        showToast(data.message || 'Counter created!', 'success');
        form.reset();
        closeAddCounterModal();
        loadCounters();
        loadOverview();
      } else {
        alert(data.error || 'Failed to create counter');
      }
    })
    .catch(err => alert('Network error: ' + err.message))
    .finally(() => {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = '🏢 Create Campus Counter'; }
    });
}

function openEditCounterModal(counterId) {
  const counter = allCounters.find(c => c.id === counterId);
  if (!counter) return;

  document.getElementById('ec-id').value = counter.id;
  document.getElementById('ec-name').value = counter.name;
  document.getElementById('ec-status').value = counter.status || 'open';
  document.getElementById('ec-location').value = counter.location || '';
  document.getElementById('ec-hours').value = counter.operating_hours || '';
  document.getElementById('ec-desc').value = counter.description || '';

  const modal = document.getElementById('edit-counter-modal');
  if (modal) modal.classList.add('open');
}

function closeEditCounterModal() {
  const modal = document.getElementById('edit-counter-modal');
  if (modal) modal.classList.remove('open');
}

function submitEditCounter(event) {
  event.preventDefault();
  const counterId = document.getElementById('ec-id').value;
  const form = document.getElementById('edit-counter-form');
  if (!counterId || !form) return;

  const submitBtn = document.getElementById('ec-submit-btn');
  if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Saving...'; }

  const formData = new FormData(form);
  fetch(`/api/admin/counters/${counterId}/edit`, { method: 'POST', body: formData })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        showToast(data.message || 'Counter updated!', 'success');
        closeEditCounterModal();
        loadCounters();
        loadOverview();
      } else {
        alert(data.error || 'Failed to update counter');
      }
    })
    .catch(err => alert('Network error: ' + err.message))
    .finally(() => {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = '💾 Save Counter Changes'; }
    });
}

function toggleCounterStatus(counterId, newStatus) {
  const formData = new FormData();
  formData.append('status', newStatus);

  fetch(`/api/admin/counters/${counterId}/toggle-status`, { method: 'POST', body: formData })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        showToast(data.message || `Counter marked as ${newStatus}`, 'success');
        loadCounters();
        loadOverview();
      } else {
        alert(data.error || 'Failed to update counter status');
      }
    })
    .catch(err => alert('Network error: ' + err.message));
}

function deleteCounter(counterId, counterName) {
  if (!confirm(`Are you sure you want to deactivate/delete counter "${counterName}"? Existing token history will be preserved.`)) {
    return;
  }
  fetch(`/api/admin/counters/${counterId}/delete`, { method: 'POST' })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        showToast(data.message || 'Counter removed successfully', 'success');
        loadCounters();
        loadOverview();
      } else {
        alert(data.error || 'Failed to delete counter');
      }
    })
    .catch(err => alert('Network error: ' + err.message));
}

// 4. Student Directory Management
function loadStudents() {
  const qInput = document.getElementById('student-search-input');
  const dSelect = document.getElementById('student-dept-select');
  const q = qInput ? qInput.value.trim() : '';
  const dept = dSelect ? dSelect.value : 'all';

  fetch(`/api/admin/students?q=${encodeURIComponent(q)}&dept=${encodeURIComponent(dept)}`)
    .then(res => {
      if (!res.ok) throw new Error('Failed to load students');
      return res.json();
    })
    .then(data => {
      allStudents = data.students || [];
      const tbody = document.getElementById('students-tbody');
      const countEl = document.getElementById('student-count-display');
      const badgeEl = document.getElementById('students-badge');

      if (countEl) countEl.textContent = allStudents.length;
      if (badgeEl && data.total_count) badgeEl.textContent = `${data.total_count} VERIFIED STUDENTS`;

      if (dSelect && dSelect.options.length <= 1 && data.departments) {
        data.departments.forEach(d => {
          const opt = document.createElement('option');
          opt.value = d;
          opt.textContent = d;
          dSelect.appendChild(opt);
        });
      }

      if (!tbody) return;
      tbody.innerHTML = '';

      if (allStudents.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="table-empty-cell"><div class="empty-state-compact"><span>🔍</span><p>No student records found matching your query.</p></div></td></tr>`;
        return;
      }

      allStudents.forEach(s => {
        const tr = document.createElement('tr');

        let tokenHtml = '<span class="status-muted">No Active Queue</span>';
        if (s.active_token) {
          tokenHtml = `<span class="badge badge-waiting">Waiting #${s.active_token}</span>`;
        } else if (s.total_tokens > 0) {
          tokenHtml = `<span class="token-count-pill">${s.total_tokens} past passes</span>`;
        }

        const isDeactivated = s.status === 'deactivated';
        const statusBadge = isDeactivated 
          ? '<span class="badge badge-status-deactivated">INACTIVE</span>'
          : '<span class="badge badge-status-open">ACTIVE</span>';

        const toggleBtnText = isDeactivated ? 'Activate' : 'Deactivate';
        const toggleNextStatus = isDeactivated ? 'active' : 'deactivated';

        tr.innerHTML = `
          <td><span class="student-uid-badge">${escapeHtml(s.student_uid || 'N/A')}</span></td>
          <td>
            <strong>${escapeHtml(s.full_name)}</strong>
            <div class="roll-pill">Roll: ${escapeHtml(s.roll_no || 'N/A')}</div>
          </td>
          <td>${escapeHtml(s.department || 'N/A')}</td>
          <td><span class="badge-role" style="font-size:11px;">${escapeHtml(s.semester || 'N/A')}</span></td>
          <td>
            <div class="contact-sub">✉️ ${escapeHtml(s.email || '-')}</div>
            <div class="contact-sub">📱 ${escapeHtml(s.phone || '-')}</div>
          </td>
          <td>${statusBadge}</td>
          <td>${tokenHtml}</td>
          <td>
            <div class="action-btn-group">
              <button type="button" class="btn btn-outline btn-sm" onclick="viewStudentTokens(${s.id})">Inspect</button>
              <button type="button" class="btn btn-outline btn-sm" onclick="openEditStudentModal(${s.id})">Edit</button>
              <button type="button" class="btn btn-outline btn-sm" onclick="toggleStudentStatus(${s.id}, '${toggleNextStatus}')">${toggleBtnText}</button>
              <button type="button" class="btn btn-danger btn-sm" onclick="deleteStudent(${s.id}, '${escapeHtml(s.full_name).replace(/'/g, "\\'")}')">Delete</button>
            </div>
          </td>
        `;
        tbody.appendChild(tr);
      });
    })
    .catch(err => {
      console.error(err);
      const tbody = document.getElementById('students-tbody');
      if (tbody) tbody.innerHTML = `<tr><td colspan="8" class="table-error-cell">Failed to load student records. Please refresh.</td></tr>`;
    });
}

function openAddStudentModal() {
  const modal = document.getElementById('add-student-modal');
  if (modal) modal.classList.add('open');
}

function closeAddStudentModal() {
  const modal = document.getElementById('add-student-modal');
  if (modal) modal.classList.remove('open');
}

function submitAddStudent(event) {
  event.preventDefault();
  const form = document.getElementById('add-student-form');
  if (!form) return;
  const submitBtn = document.getElementById('as-submit-btn');
  if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Enrolling...'; }

  const formData = new FormData(form);
  fetch('/api/admin/students/add', { method: 'POST', body: formData })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        showToast(data.message || 'Student enrolled successfully!', 'success');
        form.reset();
        closeAddStudentModal();
        loadStudents();
        loadOverview();
      } else {
        alert(data.error || 'Failed to add student');
      }
    })
    .catch(err => alert('Network error: ' + err.message))
    .finally(() => {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = '🚀 Save & Enroll Student'; }
    });
}

function openEditStudentModal(studentId) {
  const s = allStudents.find(x => x.id === studentId);
  if (!s) return;

  document.getElementById('es-id').value = s.id;
  document.getElementById('es-name').value = s.full_name || '';
  document.getElementById('es-roll').value = s.roll_no || '';
  document.getElementById('es-dept').value = s.department || 'Computer Science';
  document.getElementById('es-sem').value = s.semester || '1st';
  document.getElementById('es-phone').value = s.phone || '';
  document.getElementById('es-email').value = s.email || '';

  const modal = document.getElementById('edit-student-modal');
  if (modal) modal.classList.add('open');
}

function closeEditStudentModal() {
  const modal = document.getElementById('edit-student-modal');
  if (modal) modal.classList.remove('open');
}

function submitEditStudent(event) {
  event.preventDefault();
  const studentId = document.getElementById('es-id').value;
  const form = document.getElementById('edit-student-form');
  if (!studentId || !form) return;

  const submitBtn = document.getElementById('es-submit-btn');
  if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Saving...'; }

  const formData = new FormData(form);
  fetch(`/api/admin/students/${studentId}/edit`, { method: 'POST', body: formData })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        showToast(data.message || 'Student profile updated!', 'success');
        closeEditStudentModal();
        loadStudents();
      } else {
        alert(data.error || 'Failed to update student');
      }
    })
    .catch(err => alert('Network error: ' + err.message))
    .finally(() => {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = '💾 Save Student Changes'; }
    });
}

function toggleStudentStatus(studentId, newStatus) {
  const formData = new FormData();
  formData.append('status', newStatus);

  fetch(`/api/admin/students/${studentId}/toggle-status`, { method: 'POST', body: formData })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        showToast(data.message || `Student marked as ${newStatus}`, 'success');
        loadStudents();
        loadOverview();
      } else {
        alert(data.error || 'Failed to toggle student status');
      }
    })
    .catch(err => alert('Network error: ' + err.message));
}

function deleteStudent(userId, studentName) {
  if (!confirm(`Are you sure you want to remove student "${studentName}"? This will delete their passes and account.`)) {
    return;
  }
  fetch(`/api/admin/students/${userId}/delete`, { method: 'POST' })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        showToast(data.message || 'Student removed successfully', 'success');
        loadStudents();
        loadOverview();
      } else {
        alert(data.error || 'Failed to remove student');
      }
    })
    .catch(err => alert('Network error: ' + err.message));
}

// Student History Modal
function viewStudentTokens(userId) {
  const modal = document.getElementById('student-modal');
  const content = document.getElementById('modal-content');
  if (!modal || !content) return;

  content.innerHTML = `<div class="modal-loading-state"><div class="spinner"></div><p>Fetching student records...</p></div>`;
  modal.classList.add('open');

  fetch(`/api/admin/student/${userId}/tokens`)
    .then(res => res.json())
    .then(data => {
      const s = data.student;
      const tokens = data.tokens || [];

      let tokenRows = '';
      if (tokens.length === 0) {
        tokenRows = `<div class="empty-state-compact"><p>No token passes issued yet for this student.</p></div>`;
      } else {
        tokenRows = tokens.map(t => {
          let badgeClass = t.status === 'served' ? 'badge-served' : (t.status === 'waiting' ? 'badge-waiting' : 'badge-skipped');
          return `
            <div class="token-history-row">
              <div>
                <strong>#${t.token_number} — ${escapeHtml(t.counter_name)}</strong>
                <div class="meta-date">${escapeHtml(t.created_at)}</div>
              </div>
              <span class="badge ${badgeClass}">${t.status.toUpperCase()}</span>
            </div>
          `;
        }).join('');
      }

      content.innerHTML = `
        <div class="modal-body-header">
          <span class="student-uid-badge">${escapeHtml(s.student_uid || 'N/A')}</span>
          <h3 class="modal-title">${escapeHtml(s.full_name)}</h3>
          <p class="modal-subtitle">
            ${escapeHtml(s.department)} · ${escapeHtml(s.semester || '')} Semester · Roll: ${escapeHtml(s.roll_no)}
          </p>
        </div>
        <div class="modal-info-box">
          <div><strong>Email:</strong> ${escapeHtml(s.email || '-')}</div>
          <div><strong>Phone:</strong> ${escapeHtml(s.phone || '-')}</div>
          <div><strong>Campus Node:</strong> Apex Institute of Technology (AIT)</div>
        </div>
        <h4 class="modal-section-title">Token Pass History (${tokens.length})</h4>
        <div class="token-history-list">${tokenRows}</div>
      `;
    })
    .catch(err => {
      content.innerHTML = `<div class="modal-error-state"><p>Failed to load student details.</p></div>`;
    });
}

function closeStudentModal() {
  const modal = document.getElementById('student-modal');
  if (modal) modal.classList.remove('open');
}

// 5. Staff & Operator Management
function loadEmployees() {
  const tbody = document.getElementById('employees-tbody');
  const badgeEl = document.getElementById('employees-badge');

  fetch('/api/admin/employees')
    .then(res => {
      if (!res.ok) throw new Error('Failed to load employees');
      return res.json();
    })
    .then(data => {
      allEmployees = data.employees || [];
      const activeOps = allEmployees.filter(e => e.active).length;
      if (badgeEl) badgeEl.textContent = `${activeOps} OF ${allEmployees.length} OPERATORS ACTIVE`;
      if (!tbody) return;
      tbody.innerHTML = '';

      if (allEmployees.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="table-empty-cell"><p>No operator accounts provisioned yet.</p></td></tr>`;
        return;
      }

      allEmployees.forEach(emp => {
        const tr = document.createElement('tr');
        const assigned = emp.counter_name 
          ? `<span class="station-pill">${escapeHtml(emp.counter_name)}</span>` 
          : '<span class="status-muted">All Stations (Float)</span>';

        const statusBadge = emp.active 
          ? '<span class="badge badge-status-open">ACTIVE</span>' 
          : '<span class="badge badge-status-deactivated">INACTIVE</span>';

        const toggleBtnText = emp.active ? 'Deactivate' : 'Activate';
        const toggleNextActive = emp.active ? 0 : 1;

        tr.innerHTML = `
          <td><span class="employee-id-badge">${escapeHtml(emp.employee_id || 'OP-STAFF')}</span></td>
          <td><strong>${escapeHtml(emp.full_name)}</strong></td>
          <td>${assigned}</td>
          <td>
            <div class="contact-sub">✉️ ${escapeHtml(emp.email || '-')}</div>
            <div class="contact-sub">📱 ${escapeHtml(emp.phone || '-')}</div>
          </td>
          <td><span class="served-count-badge">${emp.served_today || 0} served</span></td>
          <td>${statusBadge}</td>
          <td>
            <div class="action-btn-group">
              <button type="button" class="btn btn-outline btn-sm" onclick="openEditEmployeeModal(${emp.user_id})">Edit</button>
              <button type="button" class="btn btn-outline btn-sm" onclick="toggleEmployeeStatus(${emp.user_id}, ${toggleNextActive})">${toggleBtnText}</button>
              <button type="button" class="btn btn-danger btn-sm" onclick="deleteEmployee(${emp.user_id}, '${escapeHtml(emp.full_name).replace(/'/g, "\\'")}')">Remove</button>
            </div>
          </td>
        `;
        tbody.appendChild(tr);
      });
    })
    .catch(err => {
      console.error(err);
      if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="table-error-cell">Failed to load staff records.</td></tr>`;
    });
}

function openAddEmployeeModal() {
  const modal = document.getElementById('add-employee-modal');
  if (modal) modal.classList.add('open');
}

function closeAddEmployeeModal() {
  const modal = document.getElementById('add-employee-modal');
  if (modal) modal.classList.remove('open');
}

function submitAddEmployee(event) {
  event.preventDefault();
  const form = document.getElementById('add-employee-form');
  if (!form) return;
  const submitBtn = document.getElementById('ae-submit-btn');
  if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Creating...'; }

  const formData = new FormData(form);
  fetch('/api/admin/employees/add', { method: 'POST', body: formData })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        showToast(data.message || 'Operator terminal provisioned!', 'success');
        form.reset();
        closeAddEmployeeModal();
        loadEmployees();
        loadOverview();
      } else {
        alert(data.error || 'Failed to create operator');
      }
    })
    .catch(err => alert('Network error: ' + err.message))
    .finally(() => {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = '⚡ Create Operator Terminal Access'; }
    });
}

function openEditEmployeeModal(userId) {
  const emp = allEmployees.find(e => e.user_id === userId);
  if (!emp) return;

  document.getElementById('ee-id').value = emp.user_id;
  document.getElementById('ee-name').value = emp.full_name || '';
  document.getElementById('ee-id-val').value = emp.employee_id || '';
  document.getElementById('ee-station').value = emp.assigned_counter || '';
  document.getElementById('ee-phone').value = emp.phone || '';
  document.getElementById('ee-email').value = emp.email || '';

  const modal = document.getElementById('edit-employee-modal');
  if (modal) modal.classList.add('open');
}

function closeEditEmployeeModal() {
  const modal = document.getElementById('edit-employee-modal');
  if (modal) modal.classList.remove('open');
}

function submitEditEmployee(event) {
  event.preventDefault();
  const userId = document.getElementById('ee-id').value;
  const form = document.getElementById('edit-employee-form');
  if (!userId || !form) return;

  const submitBtn = document.getElementById('ee-submit-btn');
  if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Saving...'; }

  const formData = new FormData(form);
  fetch(`/api/admin/employees/${userId}/edit`, { method: 'POST', body: formData })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        showToast(data.message || 'Staff profile updated!', 'success');
        closeEditEmployeeModal();
        loadEmployees();
      } else {
        alert(data.error || 'Failed to update operator');
      }
    })
    .catch(err => alert('Network error: ' + err.message))
    .finally(() => {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = '💾 Save Staff Changes'; }
    });
}

function toggleEmployeeStatus(userId, newActiveState) {
  const formData = new FormData();
  formData.append('active', newActiveState);

  fetch(`/api/admin/employees/${userId}/toggle-status`, { method: 'POST', body: formData })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        showToast(data.message || 'Staff status toggled', 'success');
        loadEmployees();
        loadOverview();
      } else {
        alert(data.error || 'Failed to toggle staff status');
      }
    })
    .catch(err => alert('Network error: ' + err.message));
}

function deleteEmployee(userId, employeeName) {
  if (!confirm(`Are you sure you want to remove operator "${employeeName}"? Terminal access will be revoked immediately.`)) {
    return;
  }
  fetch(`/api/admin/employees/${userId}/delete`, { method: 'POST' })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        showToast(data.message || 'Operator access revoked', 'success');
        loadEmployees();
        loadOverview();
      } else {
        alert(data.error || 'Failed to remove operator');
      }
    })
    .catch(err => alert('Network error: ' + err.message));
}

// 6. Student Complaints & Feedback Desk
function loadComplaints() {
  const statusSelect = document.getElementById('complaints-status-select');
  const searchInput = document.getElementById('complaints-search-input');
  const status = statusSelect ? statusSelect.value : 'pending';
  const q = searchInput ? searchInput.value.trim() : '';

  fetch(`/api/admin/complaints?status=${encodeURIComponent(status)}&q=${encodeURIComponent(q)}`)
    .then(res => {
      if (!res.ok) throw new Error('Failed to load feedback');
      return res.json();
    })
    .then(data => {
      allComplaints = data.complaints || [];
      const tbody = document.getElementById('complaints-tbody');
      const countEl = document.getElementById('complaints-count-display');
      const badgeEl = document.getElementById('complaints-badge');

      if (countEl) countEl.textContent = allComplaints.length;
      if (badgeEl) badgeEl.textContent = `${allComplaints.length} TICKETS FOUND`;

      if (!tbody) return;
      tbody.innerHTML = '';

      if (allComplaints.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="table-empty-cell"><p>No student complaints or feedback found in this filter.</p></td></tr>`;
        return;
      }

      allComplaints.forEach(item => {
        const tr = document.createElement('tr');
        const isResolved = item.status === 'resolved';
        const statusBadge = isResolved
          ? '<span class="badge badge-resolved">RESOLVED</span>'
          : '<span class="badge badge-pending">PENDING</span>';

        const subjectSnippet = item.subject ? `<strong>${escapeHtml(item.subject)}</strong><br>` : '';
        const messagePreview = escapeHtml(item.message || '').substring(0, 90) + (item.message && item.message.length > 90 ? '...' : '');

        tr.innerHTML = `
          <td>
            <strong>${escapeHtml(item.student_name)}</strong>
            <div class="roll-pill">Roll: ${escapeHtml(item.roll_no || 'N/A')}</div>
            <div style="font-size:11px; color:var(--text-muted);">${escapeHtml(item.department || '')}</div>
          </td>
          <td><span class="badge-role" style="font-size:11px;">${escapeHtml(item.category || 'General')}</span></td>
          <td>
            ${subjectSnippet}
            <span style="font-size:12.5px; color:var(--text-secondary);">${messagePreview}</span>
          </td>
          <td style="font-size:12px; color:var(--text-muted);">${escapeHtml(item.created_at)}</td>
          <td>${statusBadge}</td>
          <td>
            <button type="button" class="btn btn-outline btn-sm" onclick="openReplyComplaintModal(${item.id})">
              ${isResolved ? 'Inspect' : 'Review & Reply'}
            </button>
          </td>
        `;
        tbody.appendChild(tr);
      });
    })
    .catch(err => {
      console.error(err);
      const tbody = document.getElementById('complaints-tbody');
      if (tbody) tbody.innerHTML = `<tr><td colspan="6" class="table-error-cell">Failed to load student feedback.</td></tr>`;
    });
}

function openReplyComplaintModal(complaintId) {
  const item = allComplaints.find(c => c.id === complaintId);
  if (!item) return;

  const detailBox = document.getElementById('complaint-detail-content');
  if (detailBox) {
    const replyHtml = item.admin_reply ? `
      <div class="complaint-reply-box">
        <strong style="color:var(--emerald-light); font-size:12px;">Existing Response (${escapeHtml(item.resolved_at || '')}):</strong>
        <p style="margin-top:4px; font-size:13px; color:var(--text-secondary);">${escapeHtml(item.admin_reply)}</p>
      </div>
    ` : '';

    detailBox.innerHTML = `
      <div class="modal-info-box">
        <div><strong>Student:</strong> ${escapeHtml(item.student_name)} (${escapeHtml(item.roll_no || '-')}) — ${escapeHtml(item.department || '')}</div>
        <div><strong>Contact:</strong> ✉️ ${escapeHtml(item.email || '-')} · 📱 ${escapeHtml(item.phone || '-')}</div>
        <div><strong>Submitted:</strong> ${escapeHtml(item.created_at)} · <strong>Category:</strong> ${escapeHtml(item.category || 'General')}</div>
      </div>
      <div style="background:rgba(255,255,255,0.03); border:1px solid var(--glass-border); border-radius:var(--radius-sm); padding:12px; margin-bottom:12px;">
        <h4 style="margin:0 0 6px 0; font-size:15px;">${escapeHtml(item.subject || 'Student Feedback')}</h4>
        <p style="margin:0; font-size:13px; color:var(--text-primary); white-space:pre-wrap;">${escapeHtml(item.message)}</p>
      </div>
      ${replyHtml}
    `;
  }

  document.getElementById('rc-id').value = item.id;
  document.getElementById('rc-status').value = item.status === 'resolved' ? 'resolved' : 'resolved';
  document.getElementById('rc-reply').value = item.admin_reply || '';

  const modal = document.getElementById('reply-complaint-modal');
  if (modal) modal.classList.add('open');
}

function closeReplyComplaintModal() {
  const modal = document.getElementById('reply-complaint-modal');
  if (modal) modal.classList.remove('open');
}

function submitReplyComplaint(event) {
  event.preventDefault();
  const complaintId = document.getElementById('rc-id').value;
  const form = document.getElementById('reply-complaint-form');
  if (!complaintId || !form) return;

  const submitBtn = document.getElementById('rc-submit-btn');
  if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Submitting...'; }

  const formData = new FormData(form);
  fetch(`/api/admin/complaints/${complaintId}/reply`, { method: 'POST', body: formData })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        showToast(data.message || 'Resolution sent to student!', 'success');
        closeReplyComplaintModal();
        loadComplaints();
        loadOverview();
      } else {
        alert(data.error || 'Failed to submit reply');
      }
    })
    .catch(err => alert('Network error: ' + err.message))
    .finally(() => {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = '✉️ Submit Resolution & Notify Student'; }
    });
}

// Initialise Dashboard
document.addEventListener('DOMContentLoaded', () => {
  loadOverview();
  loadAnalytics();
  loadCounters();
  loadStudents();
  loadEmployees();
  loadComplaints();

  // Polling fallback every 15s
  setInterval(() => {
    loadOverview();
    loadAnalytics();
  }, 15000);

  // Search Listeners
  const studentSearchInput = document.getElementById('student-search-input');
  if (studentSearchInput) {
    let debounceTimer;
    studentSearchInput.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(loadStudents, 250);
    });
  }

  const studentDeptSelect = document.getElementById('student-dept-select');
  if (studentDeptSelect) {
    studentDeptSelect.addEventListener('change', loadStudents);
  }

  const complaintsSearchInput = document.getElementById('complaints-search-input');
  if (complaintsSearchInput) {
    let debounceTimer;
    complaintsSearchInput.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(loadComplaints, 250);
    });
  }

  // Socket.IO real-time refresh
  if (typeof io !== 'undefined') {
    const socket = io();
    socket.on('connect', () => {
      socket.emit('join', { room: 'admin_global' });
    });
    socket.on('admin_refresh', () => {
      loadOverview();
      loadAnalytics();
      loadCounters();
      loadStudents();
      loadEmployees();
      loadComplaints();
    });
    socket.on('queue_update', () => {
      loadOverview();
      loadAnalytics();
      loadCounters();
    });
  }
});
