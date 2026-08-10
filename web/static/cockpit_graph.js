/*
 * Кокпит 4b — граф-вид «смысловая модель» Career Match.
 *
 * Радиальный SVG-граф без внешних библиотек: центр = кандидат × вакансия,
 * три домена (сильные стороны / переносимые компетенции / риски), листья —
 * пункты LLM-анализа. Клик по узлу — карточка справа. Три линзы:
 *   1 Соответствие — вся картина;
 *   2 Подготовка   — фокус на рисках (каждый риск = ожидаемый вопрос «?»);
 *   3 Отклик       — фокус на сильных сторонах (фактура для письма).
 * Горячие клавиши: 1/2/3 — линзы, G — граф⇄классика, Esc — закрыть карточку.
 * Данные приходят из шаблона через window.COCKPIT_DATA.
 */
(function () {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const W = 1280, H = 800, CX = W / 2, CY = H / 2 - 14;
  const HUB_R = 235;          // расстояние центр → хаб домена
  const LEAF_R = 195;         // расстояние хаб → лист
  const PANEL_KEY = "cockpitPanelW";
  const LENS_KEY = "cockpitLens";

  let data = null;
  let selected = null;        // выбранный узел {domain, index}
  let lens = "match";
  let built = false;

  // ── helpers ─────────────────────────────────────────────────────────────

  function el(name, attrs, parent) {
    const node = document.createElementNS(NS, name);
    for (const k in attrs) node.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(node);
    return node;
  }

  // «В УРАЛХИМ (2018–2023) — …» → «УРАЛХИМ · 2018–2023», иначе первые слова.
  // Обрезка — только по границе слова, без висячей пунктуации на конце.
  function shortLabel(text) {
    const m = text.match(/^В\s+([^(]{2,40})\s*\(([^)]{2,20})\)/);
    if (m) return m[1].trim().replace(/[«»]/g, "") + " · " + m[2].trim();
    const words = text.trim().split(/\s+/);
    let out = "";
    for (const w of words) {
      const next = out ? out + " " + w : w;
      if (next.length > 42) break;
      out = next;
    }
    if (!out) out = text.slice(0, 40);
    out = out.replace(/[,;:.(«\-–—]+$/, "");
    return out.length < text.trim().length ? out + "…" : out;
  }

  // перенос подписи узла на строки ≤ 20 символов, максимум 3 строки
  function wrapLabel(label) {
    const words = label.split(/\s+/);
    const lines = [];
    let cur = "";
    for (const w of words) {
      if ((cur + " " + w).trim().length > 20 && cur) { lines.push(cur); cur = w; }
      else cur = (cur + " " + w).trim();
      if (lines.length === 3) break;
    }
    if (cur && lines.length < 3) lines.push(cur);
    return lines;
  }

  function polar(cx, cy, r, deg) {
    const a = (deg - 90) * Math.PI / 180;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  }

  // ── построение графа ────────────────────────────────────────────────────

  function build() {
    if (built) return;
    data = window.COCKPIT_DATA;
    if (!data) return;
    built = true;

    const svg = document.getElementById("cockpitSvg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const gEdges = el("g", { class: "cg-edges" }, svg);
    const gNodes = el("g", { class: "cg-nodes" }, svg);

    // хабы доменов: вверх / влево-вниз / вправо-вниз
    const hubAngles = { strengths: 0, competencies: 240, risks: 120 };

    data.domains.forEach((domain) => {
      const [hx, hy] = polar(CX, CY, HUB_R, hubAngles[domain.key]);
      domain._x = hx; domain._y = hy;

      el("line", {
        x1: CX, y1: CY, x2: hx, y2: hy,
        class: `cg-edge cg-${domain.key}`,
      }, gEdges);

      // листья веером наружу от центра через хаб; при 4+ листьях соседи
      // чередуются по радиусу («шахматка»), чтобы подписи не наезжали
      const n = domain.items.length;
      const spread = Math.min(168, 42 * Math.max(n - 1, 1));
      domain.items.forEach((item, i) => {
        const angle = hubAngles[domain.key] +
          (n === 1 ? 0 : -spread / 2 + (spread / (n - 1)) * i);
        const r = LEAF_R - (n > 3 && i % 2 ? 32 : 0);
        const [lx, ly] = polar(hx, hy, r, angle);
        item._x = lx; item._y = ly;

        el("line", {
          x1: hx, y1: hy, x2: lx, y2: ly,
          class: `cg-edge cg-leaf-edge cg-${domain.key}`,
          "data-domain": domain.key,
        }, gEdges);

        const g = el("g", {
          class: `cg-node cg-leaf cg-${domain.key}`,
          "data-domain": domain.key, "data-index": i,
          transform: `translate(${lx},${ly})`, tabindex: 0,
          role: "button", "aria-label": item.text.slice(0, 80),
        }, gNodes);
        el("circle", { r: 34, class: "cg-leaf-circle" }, g);
        el("text", { class: "cg-q-badge", y: -38, "text-anchor": "middle" }, g)
          .textContent = "?";
        const label = el("text", {
          class: "cg-leaf-label", y: 46, "text-anchor": "middle",
        }, g);
        wrapLabel(shortLabel(item.text)).forEach((line, li) => {
          el("tspan", { x: 0, dy: li === 0 ? 0 : 13 }, label).textContent = line;
        });
        g.addEventListener("click", () => selectNode(domain.key, i));
        g.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") selectNode(domain.key, i);
        });
      });

      // хаб
      const hub = el("g", {
        class: `cg-node cg-hub cg-${domain.key}`,
        transform: `translate(${hx},${hy})`,
      }, gNodes);
      el("circle", { r: 46, class: "cg-hub-circle" }, hub);
      const hubText = el("text", { class: "cg-hub-label", "text-anchor": "middle", y: -2 }, hub);
      wrapLabel(domain.label).forEach((line, li) => {
        el("tspan", { x: 0, dy: li === 0 ? 0 : 14 }, hubText).textContent = line;
      });
      el("text", { class: "cg-hub-count", "text-anchor": "middle", y: 26 }, hub)
        .textContent = domain.items.length;
    });

    // центр: кольцо скора
    const center = el("g", { class: "cg-node cg-center", transform: `translate(${CX},${CY})` }, gNodes);
    el("circle", { r: 74, class: "cg-center-bg" }, center);
    const ring = el("circle", {
      r: 66, class: `cg-center-ring cg-ring-${data.scoreColor}`,
      "stroke-dasharray": `${(data.score / 100) * 2 * Math.PI * 66} ${2 * Math.PI * 66}`,
      transform: "rotate(-90)",
    }, center);
    ring.getBBox; // no-op, keeps linters quiet
    el("text", { class: "cg-center-score", "text-anchor": "middle", y: 2 }, center)
      .textContent = data.score;
    el("text", { class: "cg-center-sub", "text-anchor": "middle", y: 24 }, center)
      .textContent = "vs " + data.kw + " kw";
    el("text", { class: "cg-center-title", "text-anchor": "middle", y: 100 }, center)
      .textContent = "кандидат × вакансия";

    restorePanelWidth();
    setLens(localStorage.getItem(LENS_KEY) || "match");
  }

  // ── линзы ───────────────────────────────────────────────────────────────

  function setLens(name) {
    lens = name;
    localStorage.setItem(LENS_KEY, name);
    const view = document.getElementById("graphView");
    view.classList.remove("lens-match", "lens-prep", "lens-letter");
    view.classList.add("lens-" + name);
    document.querySelectorAll(".cg-lens-btn").forEach((b) =>
      b.classList.toggle("active", b.dataset.lens === name));
    if (!selected) renderDefaultPanel();
  }

  // ── карточка узла / панель ──────────────────────────────────────────────

  function selectNode(domainKey, index) {
    selected = { domain: domainKey, index };
    document.querySelectorAll(".cg-leaf").forEach((n) =>
      n.classList.toggle("selected",
        n.dataset.domain === domainKey && +n.dataset.index === index));
    const domain = data.domains.find((d) => d.key === domainKey);
    const item = domain.items[index];
    const panel = document.getElementById("cgPanelBody");
    const title = { strengths: "💪 Сильная сторона", competencies: "↔ Переносимая компетенция", risks: "⚠️ Риск / пробел" }[domainKey];
    let html = `<div class="cg-card-tag cg-tag-${domainKey}">${title}</div>
                <p class="cg-card-text">${esc(item.text)}</p>`;
    if (domainKey === "risks") {
      html += `<div class="cg-card-hint">На интервью это — почти гарантированный вопрос.
               Отработай ответ заранее: страница «Подготовка» строит заготовки по каждому
               утверждению резюме, а спарринг Purple Team даёт отточенные формулировки.</div>`;
    } else if (lens === "letter") {
      html += `<div class="cg-card-hint">Кандидат в буллет письма: сожми до одной строки
               с цифрой и привяжи к требованию вакансии.</div>`;
    }
    panel.innerHTML = html;
  }

  function renderDefaultPanel() {
    const panel = document.getElementById("cgPanelBody");
    if (lens === "prep") {
      const qs = (data.hrQuestions || []).map((q) => `<li>${esc(q)}</li>`).join("");
      panel.innerHTML = `<div class="cg-card-tag cg-tag-risks">Линза «Подготовка»</div>
        <p class="cg-card-text">Риски подсвечены — каждый из них читай как будущий вопрос
        интервьюера. Кликни узел, чтобы раскрыть.</p>
        ${qs ? `<div class="cg-card-hint"><strong>Вопросы, которые стоит задать HR:</strong><ul>${qs}</ul></div>` : ""}`;
    } else if (lens === "letter") {
      panel.innerHTML = `<div class="cg-card-tag cg-tag-strengths">Линза «Отклик»</div>
        <p class="cg-card-text">Остались только сильные стороны — фактура для письма.
        Выбирай 2–3 узла с цифрами, зеркалящие главные требования вакансии, — это и есть
        буллеты блока «почему я».</p>`;
    } else {
      panel.innerHTML = `<div class="cg-card-tag">Смысловая модель</div>
        <p class="cg-card-text">Карта соответствия: центр — общий матч, три домена —
        сильные стороны, переносимые компетенции, риски. Кликни любой узел.</p>
        <div class="cg-card-hint">Линзы: <kbd>1</kbd> Соответствие · <kbd>2</kbd> Подготовка ·
        <kbd>3</kbd> Отклик · <kbd>G</kbd> граф⇄классика · <kbd>Esc</kbd> сброс</div>`;
    }
  }

  function clearSelection() {
    selected = null;
    document.querySelectorAll(".cg-leaf.selected").forEach((n) => n.classList.remove("selected"));
    renderDefaultPanel();
  }

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // ── перетаскиваемая граница панели ──────────────────────────────────────

  function restorePanelWidth() {
    const saved = localStorage.getItem(PANEL_KEY);
    if (saved) document.getElementById("cgPanel").style.width = saved + "px";
  }

  function initDivider() {
    const divider = document.getElementById("cgDivider");
    const panel = document.getElementById("cgPanel");
    let dragging = false;
    divider.addEventListener("mousedown", (e) => { dragging = true; e.preventDefault(); });
    window.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      const w = Math.min(640, Math.max(260, window.innerWidth - e.clientX));
      panel.style.width = w + "px";
      localStorage.setItem(PANEL_KEY, w);
    });
    window.addEventListener("mouseup", () => { dragging = false; });
  }

  // ── публичный интерфейс и клавиши ───────────────────────────────────────

  window.cockpitGraph = {
    activate() { build(); },
    setLens,
  };

  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    const inGraph = document.body.classList.contains("match-mode-graph");
    if (e.key.toLowerCase() === "g" || e.key.toLowerCase() === "п") {
      window.setMode(inGraph ? "interview" : "graph");
    } else if (inGraph && ["1", "2", "3"].includes(e.key)) {
      setLens({ 1: "match", 2: "prep", 3: "letter" }[e.key]);
    } else if (inGraph && e.key === "Escape") {
      clearSelection();
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    initDivider();
    document.querySelectorAll(".cg-lens-btn").forEach((b) =>
      b.addEventListener("click", () => setLens(b.dataset.lens)));
  });
})();
