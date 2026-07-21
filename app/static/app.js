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
      html += renderAnswerHtml(data);
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

function renderAnswerHtml(data) {
  let text = data.answer || "";

  // Remove a linha "PAGINAS: ..." caso tenha escapado do backend
  text = text.replace(/\n*\*{0,2}\s*PAGINAS\s*:[\d,\s]+\*{0,2}\s*$/i, "").trimEnd();

  // Converte referencias brutas de pagina para links markdown:
  // Suporta: [p. 119], [p. 119, 294], [p. 119, p. 294, p. 295],
  //          [pág. 44], [pp. 44, 119], [p 119], etc.
  // Estrategia: qualquer colchete que comece com prefixo de pagina E contenha numeros.
  text = text.replace(/\[\s*(?:p[aá]g(?:inas?)?|pp?)[\.\s]*([\d][\d\s,\.p]*?)\s*\](?!\()/gi, (match) => {
    const pages = match.match(/\d+/g) || [];
    if (pages.length === 0) return match;
    return pages.map(p => `[pág. ${p}](/manuals/${data.manual_id}/pdf#page=${p})`).join(" ");
  });

  let html = marked.parse(text, { breaks: true });
  html = sanitizeHtml(html);

  // Destaca visualmente o primeiro paragrafo (resposta direta)
  const t = document.createElement("template");
  t.innerHTML = html;
  const firstP = t.content.querySelector("p");
  if (firstP) firstP.classList.add("answer-lead");

  // Garante que links do PDF abram em nova aba com estilo de badge
  t.content.querySelectorAll("a").forEach(a => {
    if (a.getAttribute("href")?.includes("/pdf#page=")) {
      a.classList.add("pdf-link");
    }
    a.setAttribute("target", "_blank");
    a.setAttribute("rel", "noopener");
  });

  return `<div class="answer-box md">${t.innerHTML}</div>`;
}

// Remove qualquer HTML perigoso que venha no markdown (a resposta vem de um LLM)
function sanitizeHtml(html) {
  const t = document.createElement("template");
  t.innerHTML = html;
  t.content.querySelectorAll("script, style, iframe, object, embed, link, form").forEach((n) => n.remove());
  t.content.querySelectorAll("*").forEach((n) => {
    for (const attr of [...n.attributes]) {
      const name = attr.name.toLowerCase();
      const val = attr.value.trim().toLowerCase();
      if (name.startsWith("on") || ((name === "href" || name === "src") && val.startsWith("javascript:"))) {
        n.removeAttribute(attr.name);
      }
    }
  });
  return t.innerHTML;
}

function renderReferences(refs) {
  if (refs.length === 0) {
    return '<div class="notice info">Nenhuma página relevante encontrada.</div>';
  }
  const cards = refs
    .map(
      (r) => `
    <div class="ref-card ${r.cited ? "cited" : ""}">
      ${r.image_url ? `
      <div class="ref-thumb" data-image="${r.image_url}" data-page="${r.page}" title="Ampliar página ${r.page}">
        <img src="${r.image_url}" loading="lazy" alt="Página ${r.page} do manual" />
      </div>` : ""}
      <div class="ref-body">
        <div class="ref-top">
          <span class="page-tag">Página ${r.page}${r.cited ? " · citada na resposta" : ""}</span>
          <a class="open-pdf" href="${r.pdf_url}" target="_blank" rel="noopener">Abrir PDF →</a>
        </div>
        <div class="snippet">${escapeHtml(r.snippet || "")}</div>
      </div>
    </div>
  `
    )
    .join("");
  return `<div class="ref-list">${cards}</div>`;
}

// Lightbox: clique na miniatura abre a página inteira por cima da tela
document.addEventListener("click", (e) => {
  const thumb = e.target.closest(".ref-thumb, .cite");
  if (thumb) {
    openLightbox(thumb.dataset.image, thumb.dataset.page);
    return;
  }
  if (e.target.closest(".lightbox")) closeLightbox();
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeLightbox();
});

function openLightbox(src, page) {
  closeLightbox();
  const box = document.createElement("div");
  box.className = "lightbox";
  box.innerHTML = `
    <div class="lightbox-inner">
      <div class="lightbox-bar">Página ${page} — clique para fechar (Esc)</div>
      <img src="${src}" alt="Página ${page} do manual" />
    </div>`;
  document.body.appendChild(box);
}

function closeLightbox() {
  document.querySelector(".lightbox")?.remove();
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

init();
