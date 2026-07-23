const el = {
  usernameLabel: document.getElementById("username-label"),
  logoutBtn: document.getElementById("logout-btn"),
  statPending: document.getElementById("stat-pending"),
  statManuals: document.getElementById("stat-manuals"),
  statUsers: document.getElementById("stat-users"),
  statPlans: document.getElementById("stat-plans"),
  statTotalQuestions: document.getElementById("stat-total-questions"),
  statTodayQuestions: document.getElementById("stat-today-questions"),
  pendingBadge: document.getElementById("pending-badge"),
  submissionsList: document.getElementById("submissions-list"),
  catalogList: document.getElementById("catalog-list"),
  usersList: document.getElementById("users-list"),
  usersBadge: document.getElementById("users-badge"),
  plansGrid: document.getElementById("plans-grid"),
  uploadForm: document.getElementById("upload-form"),
  brandInput: document.getElementById("brand-input"),
  modelInput: document.getElementById("model-input"),
  yearInput: document.getElementById("year-input"),
  fileInput: document.getElementById("file-input"),
  btnUpload: document.getElementById("btn-upload"),
  uploadStatus: document.getElementById("upload-status"),
  analyticsWeekBadge: document.getElementById("analytics-week-badge"),
  analyticsAvgBadge: document.getElementById("analytics-avg-badge"),
  questionsChart: document.getElementById("questions-chart"),
  chartEmpty: document.getElementById("chart-empty"),
  llmUsageChart: document.getElementById("llm-usage-chart"),
  topManualsList: document.getElementById("top-manuals-list"),
  topUsersList: document.getElementById("top-users-list"),
  recentQuestionsList: document.getElementById("recent-questions-list"),
};

let allPlans = [];
let allManuals = [];

async function api(path, options = {}) {
  const res = await fetch(path, { credentials: "same-origin", ...options });
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("unauthenticated");
  }
  if (res.status === 403) {
    alert("Acesso negado. Você não é um administrador.");
    window.location.href = "/";
    throw new Error("forbidden");
  }
  return res;
}

async function init() {
  const meRes = await api("/auth/me");
  const me = await meRes.json();
  if (!me.is_admin) {
    alert("Acesso restrito a administradores.");
    window.location.href = "/";
    return;
  }
  el.usernameLabel.textContent = me.username;

  el.logoutBtn.addEventListener("click", async () => {
    await api("/auth/logout", { method: "POST" });
    window.location.href = "/login";
  });

  el.uploadForm.addEventListener("submit", handleUpload);

  // Plan form
  const planForm = document.getElementById("plan-form");
  if (planForm) planForm.addEventListener("submit", handlePlanSubmit);

  await loadData();
}

async function loadData() {
  await Promise.all([loadPlans(), loadUsers(), loadSubmissions(), loadCatalog(), loadAnalytics()]);
}

// ─── Plans ───────────────────────────────────────────────────────────────────

async function loadPlans() {
  try {
    const res = await api("/api/admin/plans");
    allPlans = await res.json();
    if (el.statPlans) el.statPlans.textContent = allPlans.length;
    renderPlansGrid();
  } catch (e) {}
}

function renderPlansGrid() {
  if (!el.plansGrid) return;
  if (allPlans.length === 0) {
    el.plansGrid.innerHTML = '<p class="empty-text">Nenhum plano cadastrado. Clique em "+ Novo Plano" para criar.</p>';
    return;
  }
  el.plansGrid.innerHTML = allPlans.map(p => `
    <div class="admin-plan-card">
      <div class="plan-name">${escapeHtml(p.name)}</div>
      <div class="plan-price">R$ ${Number(p.price).toFixed(2).replace('.', ',')} <span>/mês</span></div>
      <div class="plan-desc">${escapeHtml(p.description || '')}${p.max_manuals ? ` · Máx. ${p.max_manuals} manual(is)` : ' · Acesso ilimitado'}</div>
      <div class="plan-actions">
        <button class="btn-action view" onclick="openEditPlanModal(${p.id})">Editar</button>
        <button class="btn-action delete" onclick="deletePlan(${p.id}, '${escapeHtml(p.name)}')">Excluir</button>
      </div>
    </div>
  `).join("");
}

window.openNewPlanModal = function() {
  document.getElementById("plan-modal-title").textContent = "💳 Novo Plano";
  document.getElementById("plan-form-id").value = "";
  document.getElementById("plan-name").value = "";
  document.getElementById("plan-slug").value = "";
  document.getElementById("plan-price").value = "";
  document.getElementById("plan-max").value = "";
  document.getElementById("plan-desc").value = "";
  const st = document.getElementById("plan-status");
  st.className = "form-status";
  st.textContent = "";
  document.getElementById("plan-modal").style.display = "flex";
};

window.openEditPlanModal = function(id) {
  const plan = allPlans.find(p => p.id === id);
  if (!plan) return;
  document.getElementById("plan-modal-title").textContent = "✏️ Editar Plano";
  document.getElementById("plan-form-id").value = plan.id;
  document.getElementById("plan-name").value = plan.name;
  document.getElementById("plan-slug").value = plan.slug;
  document.getElementById("plan-price").value = plan.price;
  document.getElementById("plan-max").value = plan.max_manuals || "";
  document.getElementById("plan-desc").value = plan.description || "";
  const st = document.getElementById("plan-status");
  st.className = "form-status";
  st.textContent = "";
  document.getElementById("plan-modal").style.display = "flex";
};

window.closePlanModal = function() {
  document.getElementById("plan-modal").style.display = "none";
};

async function handlePlanSubmit(e) {
  e.preventDefault();
  const id = document.getElementById("plan-form-id").value;
  const body = {
    name: document.getElementById("plan-name").value.trim(),
    slug: document.getElementById("plan-slug").value.trim(),
    price: parseFloat(document.getElementById("plan-price").value),
    max_manuals: document.getElementById("plan-max").value ? parseInt(document.getElementById("plan-max").value) : null,
    description: document.getElementById("plan-desc").value.trim() || null,
  };
  const btn = document.getElementById("plan-submit-btn");
  const st = document.getElementById("plan-status");
  btn.disabled = true;
  st.className = "form-status loading";
  st.textContent = "Salvando...";

  try {
    const url = id ? `/api/admin/plans/${id}` : "/api/admin/plans";
    const method = id ? "PUT" : "POST";
    const res = await api(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    st.className = "form-status success";
    st.textContent = "Plano salvo com sucesso!";
    setTimeout(() => closePlanModal(), 1200);
    await loadPlans();
  } catch (err) {
    st.className = "form-status error";
    st.textContent = "Erro ao salvar plano.";
  } finally {
    btn.disabled = false;
  }
}

window.deletePlan = async function(id, name) {
  if (!confirm(`Tem certeza que deseja excluir o plano "${name}"?`)) return;
  try {
    await api(`/api/admin/plans/${id}`, { method: "DELETE" });
    await loadPlans();
  } catch (err) {
    alert("Erro ao excluir plano.");
  }
};

// ─── Users ───────────────────────────────────────────────────────────────────

async function loadUsers() {
  try {
    const res = await api("/api/admin/users");
    const users = await res.json();
    if (el.statUsers) el.statUsers.textContent = users.length;
    if (el.usersBadge) el.usersBadge.textContent = `${users.length} usuário(s)`;

    if (!el.usersList) return;
    if (users.length === 0) {
      el.usersList.innerHTML = '<p class="empty-text">Nenhum usuário cadastrado.</p>';
      return;
    }

    let html = `
      <table class="admin-table">
        <thead><tr>
          <th>Usuário</th><th>Tipo</th><th>Plano Atual</th><th>Moto (Proprietário)</th><th>Criado em</th><th>Ações</th>
        </tr></thead><tbody>
    `;

    for (const u of users) {
      const planBadgeClass = u.plan_slug === "owner" ? "plan-owner" : u.plan_slug === "mechanic" ? "plan-mechanic" : "plan-none";
      const planLabel = u.plan_name ? `<span class="user-plan-badge ${planBadgeClass}">${escapeHtml(u.plan_name)}</span>` : '<span class="user-plan-badge plan-none">Sem plano</span>';
      const motoLabel = u.manual_brand ? `${escapeHtml(u.manual_brand)} ${escapeHtml(u.manual_model || '')}` : '-';
      const dateStr = u.created_at ? new Date(u.created_at).toLocaleDateString("pt-BR") : '-';
      const typeLabel = u.is_admin ? '⚙️ Admin' : '👤 Usuário';

      html += `
        <tr>
          <td><strong>${escapeHtml(u.username)}</strong></td>
          <td>${typeLabel}</td>
          <td>${planLabel}</td>
          <td>${motoLabel}</td>
          <td>${dateStr}</td>
          <td>
            ${!u.is_admin ? `<button class="btn-action approve" onclick="openUserPlanModal(${u.id}, '${escapeHtml(u.username)}', ${u.plan_id || 'null'})">Atribuir Plano</button>` : '<span class="dim">-</span>'}
          </td>
        </tr>
      `;
    }
    html += "</tbody></table>";
    el.usersList.innerHTML = html;
  } catch (e) {}
}

window.openUserPlanModal = function(userId, username, currentPlanId) {
  const modal = document.getElementById("user-plan-modal");
  const body = document.getElementById("user-plan-modal-body");
  if (!modal || !body) return;

  const planOptions = allPlans.map(p => `
    <option value="${p.id}" ${p.id === currentPlanId ? 'selected' : ''}>${escapeHtml(p.name)} — R$ ${Number(p.price).toFixed(2).replace('.',',')}</option>
  `).join("");

  const manualOptions = allManuals.map(m => `
    <option value="${m.id}">${escapeHtml(m.brand)} ${escapeHtml(m.model)} (${escapeHtml(m.year)})</option>
  `).join("");

  body.innerHTML = `
    <p style="color:var(--text-dim);margin-bottom:16px;">Usuário: <strong style="color:var(--text)">${escapeHtml(username)}</strong></p>
    <div class="form-group">
      <label>Plano</label>
      <select id="modal-plan-select" style="width:100%;padding:10px 14px;border-radius:10px;border:1px solid var(--border);background:rgba(0,0,0,0.3);color:var(--text);font-family:inherit;font-size:0.95rem;">
        <option value="">— Sem plano —</option>
        ${planOptions}
      </select>
    </div>
    <div class="form-group" id="modal-manual-group" style="display:none;">
      <label>Moto para o plano Proprietário</label>
      <select id="modal-manual-select" style="width:100%;padding:10px 14px;border-radius:10px;border:1px solid var(--border);background:rgba(0,0,0,0.3);color:var(--text);font-family:inherit;font-size:0.95rem;">
        <option value="">— Selecionar depois —</option>
        ${manualOptions}
      </select>
    </div>
    <div id="user-plan-status" class="form-status"></div>
    <div class="modal-actions">
      <button class="btn-secondary" onclick="closeUserPlanModal()">Cancelar</button>
      <button class="btn-primary" onclick="saveUserPlan(${userId})">Salvar</button>
    </div>
  `;

  // Mostrar select de moto quando plano owner é selecionado
  const planSelect = document.getElementById("modal-plan-select");
  const manualGroup = document.getElementById("modal-manual-group");
  planSelect.addEventListener("change", () => {
    const selected = allPlans.find(p => p.id === parseInt(planSelect.value));
    manualGroup.style.display = (selected && selected.max_manuals === 1) ? "block" : "none";
  });
  // Trigger on load
  planSelect.dispatchEvent(new Event("change"));

  modal.style.display = "flex";
};

window.closeUserPlanModal = function() {
  document.getElementById("user-plan-modal").style.display = "none";
};

window.saveUserPlan = async function(userId) {
  const planId = document.getElementById("modal-plan-select").value;
  const manualId = document.getElementById("modal-manual-select")?.value;
  const st = document.getElementById("user-plan-status");

  st.className = "form-status loading";
  st.textContent = "Salvando...";

  try {
    const res = await api(`/api/admin/users/${userId}/set-plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        plan_id: planId ? parseInt(planId) : null,
        plan_manual_id: manualId || null,
      }),
    });
    const data = await res.json();
    st.className = "form-status success";
    st.textContent = "Plano atualizado!";
    setTimeout(() => closeUserPlanModal(), 1000);
    await loadUsers();
  } catch (err) {
    st.className = "form-status error";
    st.textContent = "Erro ao salvar.";
  }
};

// ─── Submissions ──────────────────────────────────────────────────────────────

async function loadSubmissions() {
  const res = await api("/api/admin/submissions");
  const submissions = await res.json();
  
  const pending = submissions.filter(s => s.status === "pending");
  el.statPending.textContent = pending.length;
  el.pendingBadge.textContent = `${pending.length} pendente(s)`;

  if (submissions.length === 0) {
    el.submissionsList.innerHTML = '<p class="empty-text">Nenhuma solicitação de usuário encontrada.</p>';
    return;
  }

  let html = `
    <table class="admin-table">
      <thead>
        <tr>
          <th>Marca / Modelo</th>
          <th>Ano</th>
          <th>Arquivo</th>
          <th>Enviado por</th>
          <th>Data</th>
          <th>Status</th>
          <th>Ações</th>
        </tr>
      </thead>
      <tbody>
  `;

  for (const s of submissions) {
    const statusClass = s.status === "approved" ? "status-approved" : s.status === "rejected" ? "status-rejected" : "status-pending";
    const statusText = s.status === "approved" ? "Aprovado" : s.status === "rejected" ? "Rejeitado" : "Pendente";
    const dateStr = new Date(s.submitted_at).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });

    html += `
      <tr>
        <td><strong>${escapeHtml(s.brand)}</strong> ${escapeHtml(s.model)}</td>
        <td>${escapeHtml(s.year)}</td>
        <td><span class="file-name" title="${escapeHtml(s.original_filename)}">📄 ${escapeHtml(s.original_filename)}</span></td>
        <td>${escapeHtml(s.username)}</td>
        <td>${dateStr}</td>
        <td><span class="badge-status ${statusClass}">${statusText}</span></td>
        <td>
          ${s.status === "pending" ? `
            <button class="btn-action approve" onclick="approveSubmission(${s.id})">Aprovar & Indexar</button>
            <button class="btn-action reject" onclick="rejectSubmission(${s.id})">Rejeitar</button>
          ` : `<span class="dim">-</span>`}
        </td>
      </tr>
    `;
  }

  html += `</tbody></table>`;
  el.submissionsList.innerHTML = html;
}

// ─── Catalog ─────────────────────────────────────────────────────────────────

async function loadCatalog() {
  const res = await api("/manuals");
  allManuals = await res.json();
  
  el.statManuals.textContent = allManuals.length;

  if (allManuals.length === 0) {
    el.catalogList.innerHTML = '<p class="empty-text">Nenhum manual cadastrado no acervo.</p>';
    return;
  }

  let html = `
    <table class="admin-table">
      <thead>
        <tr>
          <th>Marca / Modelo</th>
          <th>Ano</th>
          <th>Páginas</th>
          <th>Indexado</th>
          <th>Idioma</th>
          <th>Ações</th>
        </tr>
      </thead>
      <tbody>
  `;

  for (const m of allManuals) {
    html += `
      <tr>
        <td><strong>${escapeHtml(m.brand)}</strong> ${escapeHtml(m.model)}</td>
        <td>${escapeHtml(m.year)}</td>
        <td>${m.pages} pág(s)</td>
        <td>${m.searchable ? '✅ Sim (Pesquisável)' : '⚠️ Escaneado'}</td>
        <td>${m.language ? m.language.toUpperCase() : '-'}</td>
        <td>
          <a href="/manuals/${m.id}/pdf" target="_blank" class="btn-action view">Ver PDF</a>
          <button class="btn-action delete" onclick="deleteManual('${m.id}', '${escapeHtml(m.brand)} ${escapeHtml(m.model)}')">Excluir</button>
        </td>
      </tr>
    `;
  }

  html += `</tbody></table>`;
  el.catalogList.innerHTML = html;
}

// ─── Actions ─────────────────────────────────────────────────────────────────

window.approveSubmission = async function(id) {
  if (!confirm("Deseja aprovar e indexar este manual no acervo?")) return;
  try {
    const res = await api(`/api/admin/submissions/${id}/approve`, { method: "POST" });
    const data = await res.json();
    alert(data.message || "Manual aprovado com sucesso!");
    await loadData();
  } catch (err) {
    alert("Erro ao aprovar manual: " + err.message);
  }
};

window.rejectSubmission = async function(id) {
  const reason = prompt("Motivo da rejeição (opcional):");
  if (reason === null) return;

  try {
    const res = await api(`/api/admin/submissions/${id}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    });
    const data = await res.json();
    alert(data.message || "Submissão rejeitada.");
    await loadData();
  } catch (err) {
    alert("Erro ao rejeitar: " + err.message);
  }
};

window.deleteManual = async function(id, name) {
  if (!confirm(`Tem certeza que deseja excluir o manual '${name}' do acervo? Esta ação não pode ser desfeita.`)) return;
  try {
    const res = await api(`/api/admin/manuals/${id}`, { method: "DELETE" });
    const data = await res.json();
    alert(data.message || "Manual excluído.");
    await loadData();
  } catch (err) {
    alert("Erro ao excluir manual: " + err.message);
  }
};

async function handleUpload(e) {
  e.preventDefault();
  const file = el.fileInput.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("brand", el.brandInput.value.trim());
  formData.append("model", el.modelInput.value.trim());
  formData.append("year", el.yearInput.value.trim());
  formData.append("file", file);

  el.btnUpload.disabled = true;
  el.uploadStatus.className = "form-status loading";
  el.uploadStatus.textContent = "Processando e indexando PDF (isso pode levar alguns segundos)...";

  try {
    const res = await api("/api/admin/manuals", {
      method: "POST",
      body: formData,
    });
    const data = await res.json();
    el.uploadStatus.className = "form-status success";
    el.uploadStatus.textContent = data.message || "Manual cadastrado e indexado com sucesso!";
    el.uploadForm.reset();
    await loadCatalog();
  } catch (err) {
    el.uploadStatus.className = "form-status error";
    el.uploadStatus.textContent = "Erro ao enviar manual: " + err.message;
  } finally {
    el.btnUpload.disabled = false;
  }
}

// ─── Analytics ────────────────────────────────────────────────────────────────

async function loadAnalytics() {
  try {
    const res = await api("/api/admin/analytics");
    const data = await res.json();
    renderAnalytics(data);
  } catch (e) {
    console.warn("Analytics load failed", e);
  }
}

function renderAnalytics(data) {
  // Stat cards
  if (el.statTotalQuestions) el.statTotalQuestions.textContent = data.total_questions;
  if (el.statTodayQuestions) el.statTodayQuestions.textContent = data.questions_today;

  // Badges
  if (el.analyticsWeekBadge) {
    const diff = data.questions_last_week > 0
      ? Math.round(((data.questions_this_week - data.questions_last_week) / data.questions_last_week) * 100)
      : (data.questions_this_week > 0 ? 100 : 0);
    const arrow = diff > 0 ? "↑" : diff < 0 ? "↓" : "→";
    el.analyticsWeekBadge.textContent = `Esta semana: ${data.questions_this_week} (${arrow}${Math.abs(diff)}%)`;
  }
  if (el.analyticsAvgBadge) {
    el.analyticsAvgBadge.textContent = `Média pág/pergunta: ${data.avg_pages_per_question}`;
  }

  // Chart
  renderBarChart(data.questions_by_day);

  // LLM usage
  renderLLMUsage(data.llm_usage);

  // Rankings
  renderRanking(el.topManualsList, data.top_manuals.map(m => ({
    name: `${m.brand} ${m.model}`,
    count: m.count,
  })));
  renderRanking(el.topUsersList, data.top_users.map(u => ({
    name: u.username,
    count: u.count,
  })));

  // Recent questions
  renderRecentQuestions(data.recent_questions);
}

// ─── Bar Chart (Canvas) ──────────────────────────────────────────────────────

function renderBarChart(dayData) {
  const canvas = el.questionsChart;
  const emptyMsg = el.chartEmpty;
  if (!canvas) return;

  if (!dayData || dayData.length === 0) {
    canvas.style.display = "none";
    if (emptyMsg) emptyMsg.style.display = "block";
    return;
  }
  canvas.style.display = "block";
  if (emptyMsg) emptyMsg.style.display = "none";

  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  const W = rect.width;
  const H = 220;
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width = W + "px";
  canvas.style.height = H + "px";
  ctx.scale(dpr, dpr);

  // Fill last 30 days
  const filled = fillLast30Days(dayData);
  const maxVal = Math.max(...filled.map(d => d.count), 1);

  const padL = 40, padR = 12, padT = 16, padB = 32;
  const chartW = W - padL - padR;
  const chartH = H - padT - padB;
  const barW = Math.max((chartW / filled.length) - 3, 2);
  const gap = (chartW - barW * filled.length) / (filled.length - 1 || 1);

  ctx.clearRect(0, 0, W, H);

  // Grid lines
  ctx.strokeStyle = "rgba(255,255,255,0.06)";
  ctx.lineWidth = 1;
  const gridSteps = 4;
  for (let i = 0; i <= gridSteps; i++) {
    const y = padT + (chartH / gridSteps) * i;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(W - padR, y);
    ctx.stroke();

    // Labels
    const val = Math.round(maxVal - (maxVal / gridSteps) * i);
    ctx.fillStyle = "rgba(255,255,255,0.35)";
    ctx.font = "11px Outfit, sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(val, padL - 6, y + 4);
  }

  // Bars
  filled.forEach((d, i) => {
    const x = padL + i * (barW + gap);
    const h = (d.count / maxVal) * chartH;
    const y = padT + chartH - h;

    // Gradient
    const grad = ctx.createLinearGradient(x, y, x, padT + chartH);
    grad.addColorStop(0, "#ff7a1a");
    grad.addColorStop(1, "#e65c00");
    ctx.fillStyle = d.count > 0 ? grad : "rgba(255,255,255,0.04)";

    // Rounded rect
    const r = Math.min(barW / 2, 4);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + barW - r, y);
    ctx.quadraticCurveTo(x + barW, y, x + barW, y + r);
    ctx.lineTo(x + barW, padT + chartH);
    ctx.lineTo(x, padT + chartH);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.fill();

    // Date labels (every 5th day)
    if (i % 5 === 0 || i === filled.length - 1) {
      ctx.fillStyle = "rgba(255,255,255,0.35)";
      ctx.font = "10px Outfit, sans-serif";
      ctx.textAlign = "center";
      const label = d.date.slice(5); // MM-DD
      ctx.fillText(label, x + barW / 2, H - 8);
    }
  });
}

function fillLast30Days(dayData) {
  const map = {};
  dayData.forEach(d => { map[d.date] = d.count; });

  const result = [];
  const now = new Date();
  for (let i = 29; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    result.push({ date: key, count: map[key] || 0 });
  }
  return result;
}

// ─── LLM Usage ───────────────────────────────────────────────────────────────

function renderLLMUsage(usage) {
  if (!el.llmUsageChart) return;
  const entries = Object.entries(usage || {});
  if (entries.length === 0) {
    el.llmUsageChart.innerHTML = '<p class="empty-text">Nenhum dado disponível.</p>';
    return;
  }

  const total = entries.reduce((s, [, v]) => s + v, 0);
  const colorMap = {
    "llm-groq": "#34d399",
    "llm-gemini": "#60a5fa",
    "search": "#fbbf24",
    "quota": "#ef4444",
    "error": "#f87171",
  };
  const labelMap = {
    "llm-groq": "Groq (LLM)",
    "llm-gemini": "Gemini (LLM)",
    "search": "Busca Simples",
    "quota": "Cota Excedida",
    "error": "Erro",
  };

  let html = entries.map(([mode, count]) => {
    const pct = total > 0 ? ((count / total) * 100).toFixed(1) : 0;
    const color = colorMap[mode] || "#9ca3af";
    const label = labelMap[mode] || mode;
    return `
      <div class="llm-item">
        <div class="llm-item-header">
          <span class="llm-item-label"><span class="llm-item-dot" style="background:${color}"></span>${escapeHtml(label)}</span>
          <span class="llm-item-count">${count} (${pct}%)</span>
        </div>
        <div class="llm-item-bar">
          <div class="llm-item-bar-fill" style="width:${pct}%;background:${color}"></div>
        </div>
      </div>
    `;
  }).join("");

  html += `<div class="llm-total">Total: ${total} consultas</div>`;
  el.llmUsageChart.innerHTML = html;
}

// ─── Ranking ─────────────────────────────────────────────────────────────────

function renderRanking(container, items) {
  if (!container) return;
  if (!items || items.length === 0) {
    container.innerHTML = '<p class="empty-text">Nenhum dado disponível.</p>';
    return;
  }

  const maxCount = items[0].count;
  container.innerHTML = items.map((item, i) => {
    const posClass = i === 0 ? "gold" : i === 1 ? "silver" : i === 2 ? "bronze" : "";
    const pct = maxCount > 0 ? ((item.count / maxCount) * 100).toFixed(0) : 0;
    return `
      <div class="ranking-item">
        <div class="ranking-position ${posClass}">${i + 1}</div>
        <div class="ranking-info">
          <div class="ranking-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
          <div class="ranking-bar-wrap">
            <div class="ranking-bar-fill" style="width:${pct}%"></div>
          </div>
        </div>
        <div class="ranking-count">${item.count}</div>
      </div>
    `;
  }).join("");
}

// ─── Recent Questions ────────────────────────────────────────────────────────

function renderRecentQuestions(questions) {
  if (!el.recentQuestionsList) return;
  if (!questions || questions.length === 0) {
    el.recentQuestionsList.innerHTML = '<p class="empty-text">Nenhuma pergunta registrada.</p>';
    return;
  }

  const modeClass = (mode) => {
    if (mode?.includes("groq")) return "rq-mode-groq";
    if (mode?.includes("gemini")) return "rq-mode-gemini";
    if (mode === "search") return "rq-mode-search";
    if (mode === "quota") return "rq-mode-quota";
    return "rq-mode-error";
  };
  const modeLabel = (mode) => {
    if (mode?.includes("groq")) return "Groq";
    if (mode?.includes("gemini")) return "Gemini";
    if (mode === "search") return "Busca";
    if (mode === "quota") return "Cota";
    return mode || "?";
  };

  el.recentQuestionsList.innerHTML = questions.map(q => {
    const dateStr = q.created_at
      ? new Date(q.created_at + "Z").toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
      : "-";
    return `
      <div class="rq-item">
        <div class="rq-question">${escapeHtml(q.question)}</div>
        <div class="rq-meta">
          <span class="rq-meta-tag">👤 ${escapeHtml(q.username || "anônimo")}</span>
          <span class="rq-meta-tag">🏍️ ${escapeHtml((q.manual_brand || "") + " " + (q.manual_model || ""))}</span>
          <span class="rq-meta-tag">📄 ${q.pages_used || 0} pág</span>
          <span class="rq-mode-badge ${modeClass(q.response_mode)}">${modeLabel(q.response_mode)}</span>
          <span class="rq-meta-tag">🕐 ${dateStr}</span>
        </div>
      </div>
    `;
  }).join("");
}

function escapeHtml(str) {
  return String(str || '').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

document.addEventListener("DOMContentLoaded", init);
