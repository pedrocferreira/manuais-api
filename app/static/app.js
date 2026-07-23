const state = {
  manuals: [],
  activeManual: null,
  activeTab: "ask", // "ask" | "search"
  currentUser: null,
};

const el = {
  manualList: document.getElementById("manual-list"),
  filterInput: document.getElementById("filter-input"),
  content: document.getElementById("content"),
  usernameLabel: document.getElementById("username-label"),
  logoutBtn: document.getElementById("logout-btn"),
  sidebar: document.getElementById("sidebar"),
  sidebarOverlay: document.getElementById("sidebar-overlay"),
  hamburgerBtn: document.getElementById("hamburger-btn"),
  sidebarCloseBtn: document.getElementById("sidebar-close-btn"),
  bottomNav: document.getElementById("bottom-nav"),
  historyBtn: document.getElementById("history-btn"),
  historyModal: document.getElementById("history-modal"),
  historyCloseBtn: document.getElementById("history-close-btn"),
  globalHistoryList: document.getElementById("global-history-list"),
  userAvatar: document.getElementById("user-avatar"),
  breadcrumbManual: document.getElementById("breadcrumb-manual"),
  topbarBreadcrumb: document.getElementById("topbar-breadcrumb"),
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
  state.currentUser = me;
  el.usernameLabel.textContent = me.username;
  if (el.userAvatar) el.userAvatar.textContent = (me.username || "?")[0].toUpperCase();

  if (me.is_admin) {
    const adminLink = document.getElementById("admin-panel-link");
    if (adminLink) adminLink.style.display = "inline-flex";
  }

  el.logoutBtn.addEventListener("click", async () => {
    await api("/auth/logout", { method: "POST" });
    window.location.href = "/login";
  });

  setupSuggestModal();
  setupHistoryModal();
  setupMobileNav();

  const manualsRes = await api("/manuals");
  state.manuals = await manualsRes.json();
  renderManualList();

  el.filterInput.addEventListener("input", renderManualList);

  // Plano Proprietário sem moto selecionada → mostrar modal
  if (!me.is_admin && me.plan && me.plan.max_manuals === 1 && !me.plan_manual_id) {
    showSelectManualModal();
  }

  // Banner de plano ativo
  if (!me.is_admin && me.plan) {
    showPlanBanner(me);
  }
}

function showPlanBanner(me) {
  const content = el.content;
  const bannerHtml = `
    <div class="plan-banner" id="plan-banner">
      📋 Plano <strong>${escapeHtml(me.plan.name)}</strong>
      ${me.plan.max_manuals === 1 && me.plan_manual_id ? ' — acesso à moto selecionada' : ''}
      ${me.plan.max_manuals !== 1 ? ' — acesso completo ao acervo' : ''}
    </div>
  `;
  // Inserir banner antes do conteúdo
  const existing = document.getElementById("plan-banner");
  if (!existing) {
    content.insertAdjacentHTML("afterbegin", bannerHtml);
  }
}

function showSelectManualModal() {
  const modal = document.getElementById("select-manual-modal");
  const grid = document.getElementById("select-manual-grid");
  if (!modal || !grid) return;

  // Buscar todos os manuais disponíveis
  api("/manuals").then(async (res) => {
    // Aqui precisa de um endpoint sem filtro de plano - temporariamente usa o mesmo
    const all = state.manuals.length > 0 ? state.manuals : await res.json();
    grid.innerHTML = all.map(m => `
      <button class="select-manual-item" onclick="selectManualForPlan('${m.id}')"
              data-id="${m.id}">
        <span class="moto-icon">🏍️</span>
        <div class="moto-info">
          <strong>${escapeHtml(m.brand)} ${escapeHtml(m.model)}</strong>
          <span>${escapeHtml(m.year)}</span>
        </div>
      </button>
    `).join("");
    modal.style.display = "flex";
  }).catch(() => {});
}

window.selectManualForPlan = async function(manualId) {
  try {
    const res = await api("/auth/select-manual", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ manual_id: manualId }),
    });
    const data = await res.json();
    if (data.ok) {
      document.getElementById("select-manual-modal").style.display = "none";
      // Recarregar manuais com filtro do plano
      const manualsRes = await api("/manuals");
      state.manuals = await manualsRes.json();
      renderManualList();
      // Atualizar user
      const meRes = await api("/auth/me");
      state.currentUser = await meRes.json();
    }
  } catch (err) {}
};

function setupMobileNav() {
  // Hamburger open
  if (el.hamburgerBtn) {
    el.hamburgerBtn.addEventListener("click", openSidebarMobile);
  }
  // Overlay close
  if (el.sidebarOverlay) {
    el.sidebarOverlay.addEventListener("click", closeSidebarMobile);
  }
  // X button close
  if (el.sidebarCloseBtn) {
    el.sidebarCloseBtn.addEventListener("click", closeSidebarMobile);
  }
  // Bottom nav tabs
  if (el.bottomNav) {
    el.bottomNav.querySelectorAll(".bottom-nav-btn[data-tab]").forEach(btn => {
      btn.addEventListener("click", () => {
        if (!state.activeManual) return;
        state.activeTab = btn.dataset.tab;
        renderContent();
        updateBottomNav(btn.dataset.tab);
      });
    });
  }
  // Detectar mobile e mostrar bottom nav
  checkMobileLayout();
  window.addEventListener("resize", checkMobileLayout);
}

function checkMobileLayout() {
  const isMobile = window.innerWidth <= 768;
  if (el.bottomNav) {
    el.bottomNav.style.display = isMobile ? "flex" : "none";
  }
}

window.openSidebarMobile = function() {
  if (el.sidebar) el.sidebar.classList.add("open");
  if (el.sidebarOverlay) el.sidebarOverlay.classList.add("active");
  document.body.style.overflow = "hidden";
};

function closeSidebarMobile() {
  if (el.sidebar) el.sidebar.classList.remove("open");
  if (el.sidebarOverlay) el.sidebarOverlay.classList.remove("active");
  document.body.style.overflow = "";
}

function updateBottomNav(tab) {
  if (!el.bottomNav) return;
  el.bottomNav.querySelectorAll(".bottom-nav-btn").forEach(btn => {
    const isActive = btn.dataset.tab === tab;
    btn.classList.toggle("active", isActive);
  });
}

function setupSuggestModal() {
  const modal = document.getElementById("suggest-modal");
  const openBtn = document.getElementById("suggest-manual-btn");
  const closeBtn = document.getElementById("modal-close-btn");
  const cancelBtn = document.getElementById("modal-cancel-btn");
  const form = document.getElementById("suggest-form");
  const statusEl = document.getElementById("suggest-status");

  if (!modal || !openBtn) return;

  const openModal = () => { modal.style.display = "flex"; };
  const closeModal = () => {
    modal.style.display = "none";
    form.reset();
    statusEl.className = "form-status";
    statusEl.textContent = "";
  };

  openBtn.addEventListener("click", openModal);
  closeBtn.addEventListener("click", closeModal);
  cancelBtn.addEventListener("click", closeModal);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = document.getElementById("suggest-file").files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("brand", document.getElementById("suggest-brand").value.trim());
    formData.append("model", document.getElementById("suggest-model").value.trim());
    formData.append("year", document.getElementById("suggest-year").value.trim());
    formData.append("file", file);

    const submitBtn = document.getElementById("suggest-submit-btn");
    submitBtn.disabled = true;
    statusEl.className = "form-status loading";
    statusEl.textContent = "Enviando arquivo...";

    try {
      const res = await api("/submissions", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      statusEl.className = "form-status success";
      statusEl.textContent = data.message || "Manual enviado para análise!";
      setTimeout(() => closeModal(), 2000);
    } catch (err) {
      statusEl.className = "form-status error";
      statusEl.textContent = "Erro ao enviar: " + err.message;
    } finally {
      submitBtn.disabled = false;
    }
  });
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
  updateBottomNav("ask");
  closeSidebarMobile(); // fecha drawer no mobile
}

function renderContent() {
  const m = state.activeManual;
  if (!m) {
    // Update breadcrumb
    if (el.topbarBreadcrumb) el.topbarBreadcrumb.style.display = "none";
    el.content.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">🏍️</div>
        <h3>Bem-vindo ao Acervo</h3>
        <p>Selecione uma moto na lista para consultar o manual técnico completo.</p>
      </div>`;
    return;
  }

  // Update breadcrumb
  if (el.topbarBreadcrumb && el.breadcrumbManual) {
    el.breadcrumbManual.textContent = `${m.brand} ${m.model} ${m.year}`;
    el.topbarBreadcrumb.style.display = "flex";
  }

  el.content.innerHTML = `
    <div class="manual-header">
      <h2>${escapeHtml(m.brand)} ${escapeHtml(m.model)}</h2>
      <div class="meta">
        <span>📅 ${escapeHtml(m.year)}</span>
        <span>📄 ${m.pages} páginas</span>
        ${m.language ? `<span>${m.language === "pt" ? "🇧🇷 Português" : "🇺🇸 English"}</span>` : ""}
      </div>
    </div>

    ${!m.searchable ? `<div class="notice warn">Este manual é escaneado e ainda não foi processado com OCR. Busca e perguntas ficarão disponíveis assim que o texto for extraído.</div>` : ""}

    <div class="tabs">
      <button data-tab="ask" class="${state.activeTab === "ask" ? "active" : ""}">Perguntar</button>
      <button data-tab="search" class="${state.activeTab === "search" ? "active" : ""}">Buscar no manual</button>
      <button data-tab="history" class="${state.activeTab === "history" ? "active" : ""}">Histórico</button>
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
    const voiceSupported = !!(window.SpeechRecognition || window.webkitSpeechRecognition);
    const micTitle = voiceSupported ? 'Perguntar por voz' : 'Voz não suportada neste navegador';
    tabBody.innerHTML = `
      <div class="ask-section">
        <div class="ask-input-bar" id="ask-input-bar">
          <textarea
            id="ask-input"
            rows="1"
            placeholder="Escreva a sua pergunta ou use o microfone…"
            ${disabled ? "disabled" : ""}
          ></textarea>
          <div class="ask-bar-actions">
            <button class="btn-mic" id="mic-btn"
              title="${micTitle}"
              ${(!voiceSupported || disabled) ? 'disabled' : ''}
              aria-label="Gravar pergunta por voz">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"></path>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
                <line x1="12" y1="19" x2="12" y2="22"></line>
              </svg>
            </button>
            <button class="btn-send" id="ask-btn"
              ${disabled ? "disabled" : ""}
              aria-label="Enviar pergunta">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="22" y1="2" x2="11" y2="13"></line>
                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
              </svg>
            </button>
          </div>
        </div>
        <div id="voice-status" class="voice-status-bar hidden" role="status" aria-live="polite"></div>
        <div id="ask-result"></div>
      </div>
    `;
    document.getElementById("ask-btn").addEventListener("click", () => runAsk(m.id));
    const askTa = document.getElementById("ask-input");
    // Auto-grow textarea
    function autoGrow() {
      askTa.style.height = "auto";
      askTa.style.height = Math.min(askTa.scrollHeight, 160) + "px";
    }
    askTa.addEventListener("input", autoGrow);
    askTa.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) runAsk(m.id);
    });
    if (voiceSupported && !disabled) {
      setupVoiceInput(m.id);
    }
  } else if (state.activeTab === "search") {
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
  } else if (state.activeTab === "history") {
    tabBody.innerHTML = `
      <div id="history-tab-result">
        <div class="notice info"><span class="spinner"></span>Carregando histórico...</div>
      </div>
    `;
    loadHistoryTab(m.id);
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

// ── Voice Input ──────────────────────────────────────────────────────────────
function setupVoiceInput(manualId) {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) return;

  const micBtn     = document.getElementById("mic-btn");
  const askInput   = document.getElementById("ask-input");
  const voiceSt    = document.getElementById("voice-status");
  if (!micBtn || !askInput) return;

  let recognition = null;
  let isRecording = false;

  function setStatus(msg, dot = false) {
    if (!voiceSt) return;
    if (!msg) {
      voiceSt.classList.add("hidden");
      voiceSt.innerHTML = "";
      return;
    }
    voiceSt.classList.remove("hidden");
    voiceSt.innerHTML = dot
      ? `<span class="voice-dot"></span>${msg}`
      : msg;
  }

  function startRecording() {
    if (isRecording) { stopRecording(); return; }

    if (!window.isSecureContext && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
      setStatus("❌ O microfone requer conexão segura (HTTPS) para funcionar no celular.");
      return;
    }

    recognition = new SpeechRecognition();
    recognition.lang = "pt-BR";
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    recognition.continuous = false;

    recognition.onstart = () => {
      isRecording = true;
      micBtn.classList.add("recording");
      const bar = document.getElementById("ask-input-bar");
      if (bar) bar.classList.add("is-listening");
      micBtn.title = "Parar gravação — clique para parar";
      askInput.placeholder = "🎤 Ouvindo… fale agora";
      setStatus("A ouvir…", true);
    };

    recognition.onresult = (e) => {
      let interim = "";
      let final   = "";
      for (const result of e.results) {
        if (result.isFinal) final   += result[0].transcript;
        else               interim += result[0].transcript;
      }
      if (final) {
        askInput.value = final.trim();
        setStatus("✅ Pronto! Revise e clique em Perguntar.");
      } else if (interim) {
        setStatus(`💬 "${interim}"`, true);
      }
    };

    recognition.onerror = (e) => {
      let msg = `❌ Erro: ${e.error}`;
      if (e.error === "not-allowed") {
        msg = window.isSecureContext 
            ? "❌ Permissão de microfone negada."
            : "❌ Microfone bloqueado (HTTPS é obrigatório no celular).";
      } else if (e.error === "no-speech") {
        msg = "⚠️ Nenhuma fala detectada. Tente novamente.";
      } else if (e.error === "audio-capture") {
        msg = "❌ Microfone não encontrado.";
      } else if (e.error === "network") {
        msg = "❌ Erro de rede no reconhecimento de voz.";
      }
      setStatus(msg);
      stopRecording(false);
    };

    recognition.onend = () => {
      stopRecording(false);
    };

    try {
      recognition.start();
    } catch (err) {
      if (!window.isSecureContext) {
        setStatus("❌ O microfone requer conexão segura (HTTPS) no celular.");
      } else {
        setStatus("❌ Não foi possível iniciar o microfone.");
      }
    }
  }

  function stopRecording(abort = true) {
    isRecording = false;
    micBtn.classList.remove("recording");
    const bar = document.getElementById("ask-input-bar");
    if (bar) bar.classList.remove("is-listening");
    micBtn.title = "Perguntar por voz";
    askInput.placeholder = "Escreva a sua pergunta ou use o microfone…";
    if (abort && recognition) {
      try { recognition.stop(); } catch (_) {}
    }
    recognition = null;
    // Limpar status após 4 s se não houver texto útil
    setTimeout(() => {
      const st = document.getElementById("voice-status");
      if (st && !st.classList.contains("hidden") && !st.textContent.includes("Pronto")) {
        setStatus("");
      }
    }, 4000);
  }

  micBtn.addEventListener("click", () => startRecording());

  // Atalho de teclado: Alt+M dispara o microfone quando o foco está na área de perguntas
  askInput.addEventListener("keydown", (e) => {
    if (e.altKey && e.key.toLowerCase() === "m") {
      e.preventDefault();
      startRecording();
    }
  });
}

// ── History ──────────────────────────────────────────────────────────────────

function setupHistoryModal() {
  if (!el.historyBtn || !el.historyModal || !el.historyCloseBtn) return;

  const openModal = () => {
    el.historyModal.style.display = "flex";
    loadGlobalHistory();
  };
  const closeModal = () => {
    el.historyModal.style.display = "none";
  };

  el.historyBtn.addEventListener("click", openModal);
  el.historyCloseBtn.addEventListener("click", closeModal);
  el.historyModal.addEventListener("click", (e) => {
    if (e.target === el.historyModal) closeModal();
  });
}

async function loadGlobalHistory() {
  if (!el.globalHistoryList) return;
  el.globalHistoryList.innerHTML = '<div class="notice info"><span class="spinner"></span>Carregando...</div>';
  try {
    const res = await api("/api/history?limit=30");
    const data = await res.json();
    renderHistoryItems(data, el.globalHistoryList, true);
  } catch (err) {
    el.globalHistoryList.innerHTML = '<div class="notice warn">Erro ao carregar histórico.</div>';
  }
}

async function loadHistoryTab(manualId) {
  const container = document.getElementById("history-tab-result");
  if (!container) return;
  try {
    const res = await api(`/api/history?manual_id=${manualId}&limit=30`);
    const data = await res.json();
    renderHistoryItems(data, container, false);
  } catch (err) {
    container.innerHTML = '<div class="notice warn">Erro ao carregar histórico.</div>';
  }
}

function renderHistoryItems(items, container, isGlobal) {
  if (!items || items.length === 0) {
    container.innerHTML = '<p class="empty-state">Nenhuma pergunta encontrada no histórico.</p>';
    return;
  }

  const modeClass = (mode) => {
    if (mode?.includes("groq")) return "mode-groq";
    if (mode?.includes("gemini")) return "mode-gemini";
    if (mode === "search") return "mode-search";
    if (mode === "quota") return "mode-quota";
    return "mode-error";
  };

  const html = items.map(q => {
    const dateStr = q.created_at
      ? new Date(q.created_at + "Z").toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
      : "-";
    
    return `
      <div class="history-item">
        <div class="history-question">${escapeHtml(q.question)}</div>
        <div class="history-meta">
          ${isGlobal && q.manual_brand ? `<span class="h-tag">🏍️ ${escapeHtml(q.manual_brand)} ${escapeHtml(q.manual_model || "")}</span>` : ""}
          <span class="h-tag">🕐 ${dateStr}</span>
          <span class="h-mode-badge ${modeClass(q.response_mode)}">${q.response_mode?.replace("llm-", "") || "?"}</span>
        </div>
        <div class="history-actions">
          <button class="btn-secondary btn-small" onclick="showCachedAnswer(this)" data-payload="${escapeHtml(JSON.stringify(q))}">
            Ver resposta
          </button>
        </div>
      </div>
    `;
  }).join("");
  
  container.innerHTML = `<div class="history-list">${html}</div>`;
}

window.showCachedAnswer = async function(btnEl) {
  const qStr = btnEl.getAttribute("data-payload");
  if (!qStr) return;
  const q = JSON.parse(qStr);

  if (!q.answer) {
    // Falta o cache no banco (pesquisas antigas) - fall back for re-asking
    alert("Esta pesquisa é antiga e não possui resposta salva. Por favor, pesquise novamente.");
    return;
  }

  // Se estiver no modal global, fecha
  if (el.historyModal) el.historyModal.style.display = "none";
  
  // Troca pro manual certo se não estiver nele
  if (!state.activeManual || state.activeManual.id !== q.manual_id) {
    const res = await api(`/manuals/${q.manual_id}`);
    state.activeManual = await res.json();
  }
  
  // Muda para a aba ask e renderiza
  state.activeTab = "ask";
  renderManualList();
  renderContent();
  updateBottomNav("ask");
  closeSidebarMobile();
  
  setTimeout(() => {
    const input = document.getElementById("ask-input");
    if (input) {
      input.value = q.question;
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 160) + "px";
    }

    const resultBox = document.getElementById("ask-result");
    if (resultBox) {
      // Reconstroi o HTML da resposta e referencias
      const data = {
        answer: q.answer,
        manual_id: q.manual_id,
      };
      
      let html = "";
      html += renderAnswerHtml(data);
      html += renderReferences(q.references || []);
      resultBox.innerHTML = html;
      
      // Remove the lead class from previous requests if needed, but it's handled by renderAnswerHtml
    }
  }, 100);
};

init();

