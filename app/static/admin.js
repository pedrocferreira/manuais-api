const el = {
  usernameLabel: document.getElementById("username-label"),
  logoutBtn: document.getElementById("logout-btn"),
  statPending: document.getElementById("stat-pending"),
  statManuals: document.getElementById("stat-manuals"),
  pendingBadge: document.getElementById("pending-badge"),
  submissionsList: document.getElementById("submissions-list"),
  catalogList: document.getElementById("catalog-list"),
  uploadForm: document.getElementById("upload-form"),
  brandInput: document.getElementById("brand-input"),
  modelInput: document.getElementById("model-input"),
  yearInput: document.getElementById("year-input"),
  fileInput: document.getElementById("file-input"),
  btnUpload: document.getElementById("btn-upload"),
  uploadStatus: document.getElementById("upload-status"),
};

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

  await loadData();
}

async function loadData() {
  await Promise.all([loadSubmissions(), loadCatalog()]);
}

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

async function loadCatalog() {
  const res = await api("/manuals");
  const manuals = await res.json();
  
  el.statManuals.textContent = manuals.length;

  if (manuals.length === 0) {
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

  for (const m of manuals) {
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
  if (reason === null) return; // cancelado pelo usuario

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
