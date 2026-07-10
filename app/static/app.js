const state = {
  manuals: [],
  activeManual: null,
  activeTab: "ask", // "ask" | "search"
};

const el = {
  manualList: document.getElementById("manual-list"),
  filterInput: document.getElementById("filter-input"),
  content: document.getElementById("content"),
  usernameLabel: document.getElementById("username-label"),
  logoutBtn: document.getElementById("logout-btn"),
};

async function api(path, options = {}) {
  const res = await fetch(path, { credentials: "same-origin", ...options });
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("unauthenticated");
  }
  return res;
}

async function init() {
  const meRes = await api("/auth/me");
  const me = await meRes.json();
  el.usernameLabel.textContent = me.username;

  el.logoutBtn.addEventListener("click", async () => {
    await api("/auth/logout", { method: "POST" });
    window.location.href = "/login";
  });

  const manualsRes = await api("/manuals");
  state.manuals = await manualsRes.json();
  renderManualList();

  el.filterInput.addEventListener("input", renderManualList);
}

function renderManualList() {
  const filter = el.filterInput.value.trim().toLowerCase();
  const groups = {};
  for (const m of state.manuals) {
    const haystack = `${m.brand} ${m.model} ${m.year}`.toLowerCase();
    if (filter && !haystack.includes(filter)) continue;
    (groups[m.brand] ||= []).push(m);
  }

  el.manualList.innerHTML = "";
  const brands = Object.keys(groups).sort();
  if (brands.length === 0) {
    el.manualList.innerHTML = '<p style="color:var(--text-dim);font-size:0.85rem;">Nenhuma moto encontrada.</p>';
    return;
  }

  for (const brand of brands) {
    const group = document.createElement("div");
    group.className = "brand-group";
    const h3 = document.createElement("h3");
    h3.textContent = brand;
    group.appendChild(h3);

    for (const m of groups[brand]) {
      const item = document.createElement("div");
      item.className = "manual-item" + (state.activeManual?.id === m.id ? " active" : "");
      item.innerHTML = `
        <span>${m.model} <span style="color:var(--text-dim)">${m.year}</span></span>
        <span class="badge ${m.searchable ? "ok" : "warn"}">${m.searchable ? "OK" : "OCR pendente"}</span>
      `;
      item.addEventListener("click", () => selectManual(m.id));
      group.appendChild(item);
    }
    el.manualList.appendChild(group);
  }
}

async function selectManual(id) {
  const res = await api(`/manuals/${id}`);
  state.activeManual = await res.json();
  state.activeTab = "ask";
  renderManualList();
  renderContent();
}

function renderContent() {
  const m = state.activeManual;
  if (!m) {
    el.content.innerHTML = '<div class="empty-state">Selecione uma moto na lista ao lado.</div>';
    return;
  }

  el.content.innerHTML = `
    <div class="manual-header">
      <h2>${m.brand} ${m.model}</h2>
      <div class="meta">${m.year} · ${m.pages} páginas ${m.language ? "· manual em " + (m.language === "pt" ? "português" : "inglês") : ""}</div>
    </div>

    ${!m.searchable ? `<div class="notice warn">Este manual é escaneado e ainda não foi processado com OCR. Busca e perguntas ficarão disponíveis assim que o texto for extraído.</div>` : ""}

    <div class="tabs">
      <button data-tab="ask" class="${state.activeTab === "ask" ? "active" : ""}">Perguntar</button>
      <button data-tab="search" class="${state.activeTab === "search" ? "active" : ""}">Buscar no manual</button>
    </div>

    <div id="tab-body"></div>
  `;

  el.content.querySelectorAll(".tabs button").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.activeTab = btn.dataset.tab;
      renderContent();
    });
  });

  const disabled = !m.searchable;
  const tabBody = document.getElementById("tab-body");

  if (state.activeTab === "ask") {
    tabBody.innerHTML = `
      <div class="ask-row">
        <textarea id="ask-input" placeholder="Ex.: qual o torque do parafuso de dreno de óleo?" ${disabled ? "disabled" : ""}></textarea>
        <button class="primary" id="ask-btn" ${disabled ? "disabled" : ""}>Perguntar</button>
      </div>
      <div id="ask-result"></div>
    `;
    document.getElementById("ask-btn").addEventListener("click", () => runAsk(m.id));
    document.getElementById("ask-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) runAsk(m.id);
    });
  } else {
    tabBody.innerHTML = `
      <div class="ask-row">
        <input type="search" id="search-input" placeholder="Ex.: torque parafuso dreno óleo" ${disabled ? "disabled" : ""} style="flex:1" />
        <button class="primary" id="search-btn" ${disabled ? "disabled" : ""}>Buscar</button>
      </div>
      <div id="search-result"></div>
    `;
    document.getElementById("search-btn").addEventListener("click", () => runSearch(m.id));
    document.getElementById("search-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") runSearch(m.id);
    });
  }
}

async function runAsk(manualId) {
  const input = document.getElementById("ask-input");
  const question = input.value.trim();
  if (!question) return;
  const resultBox = document.getElementById("ask-result");
  const btn = document.getElementById("ask-btn");
  btn.disabled = true;
  resultBox.innerHTML = '<div class="notice info"><span class="spinner"></span>Consultando o manual...</div>';

  try {
    const res = await api(`/manuals/${manualId}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const data = await res.json();
    let html = "";
    if (data.message) {
      html += `<div class="notice ${data.mode === "search" ? "info" : "warn"}">${escapeHtml(data.message)}</div>`;
    }
    if (data.answer) {
      html += `<div class="answer-box">${escapeHtml(data.answer)}</div>`;
    }
    html += renderReferences(data.references || []);
    resultBox.innerHTML = html;
  } catch (err) {
    if (err.message !== "unauthenticated") {
      resultBox.innerHTML = '<div class="notice warn">Erro ao consultar o manual. Tente novamente.</div>';
    }
  } finally {
    btn.disabled = false;
  }
}

async function runSearch(manualId) {
  const input = document.getElementById("search-input");
  const q = input.value.trim();
  if (q.length < 2) return;
  const resultBox = document.getElementById("search-result");
  const btn = document.getElementById("search-btn");
  btn.disabled = true;
  resultBox.innerHTML = '<div class="notice info"><span class="spinner"></span>Buscando...</div>';

  try {
    const res = await api(`/manuals/${manualId}/search?q=${encodeURIComponent(q)}`);
    const data = await res.json();
    resultBox.innerHTML = renderReferences(data.results || []);
  } catch (err) {
    if (err.message !== "unauthenticated") {
      resultBox.innerHTML = '<div class="notice warn">Erro ao buscar. Tente novamente.</div>';
    }
  } finally {
    btn.disabled = false;
  }
}

function renderReferences(refs) {
  if (refs.length === 0) {
    return '<div class="notice info">Nenhuma página relevante encontrada.</div>';
  }
  const cards = refs
    .map(
      (r) => `
    <div class="ref-card ${r.cited ? "cited" : ""}">
      <div class="ref-top">
        <span class="page-tag">Página ${r.page}${r.cited ? " · citada na resposta" : ""}</span>
        <a class="open-pdf" href="${r.pdf_url}" target="_blank" rel="noopener">Abrir PDF →</a>
      </div>
      <div class="snippet">${escapeHtml(r.snippet || "")}</div>
    </div>
  `
    )
    .join("");
  return `<div class="ref-list">${cards}</div>`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

init();
