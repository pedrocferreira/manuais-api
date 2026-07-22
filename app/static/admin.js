const el = {
  usernameLabel: document.getElementById("username-label"),
  logoutBtn: document.getElementById("logout-btn"),
  statPending: document.getElementById("stat-pending"),
  statManuals: document.getElementById("stat-manuals"),
  statUsers: document.getElementById("stat-users"),
  statPlans: document.getElementById("stat-plans"),
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
  await Promise.all([loadPlans(), loadUsers(), loadSubmissions(), loadCatalog()]);
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

function escapeHtml(str) {
  return String(str || '').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

document.addEventListener("DOMContentLoaded", init);
