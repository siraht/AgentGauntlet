let state = null;
let config = { actions_enabled: false, portfolio: false };
let selectedIndex = 0;
let autoRefresh = false;
let refreshTimer = null;
let lastDecisionAnnouncement = "";
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );
const setSafeHTML = (node, markup) => {
  // All dynamic values must pass through esc() before reaching this reviewed rendering boundary.
  node.innerHTML = markup; // AQG_REVIEWED_SECURITY
};
const human = (value) => String(value ?? "").replaceAll("_", " ");
const duration = (ms = 0) =>
  ms < 1000
    ? `${ms}ms`
    : ms < 60000
      ? `${(ms / 1000).toFixed(1)}s`
      : `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
const toast = (message) => {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove("show"), 3200);
};

async function fetchJSON(path, options) {
  const response = await fetch(path, { cache: "no-store", ...options });
  const payload = await response
    .json()
    .catch(() => ({ error: `${response.status} ${response.statusText}` }));
  if (!response.ok)
    throw new Error(
      payload.error || `${response.status} ${response.statusText}`,
    );
  return payload;
}
function project() {
  return (
    state?.projects?.[
      Math.min(selectedIndex, Math.max(0, (state?.projects?.length || 1) - 1))
    ] || {}
  );
}
function badge(status, label) {
  return `<span class="badge ${esc(status || "neutral")}">${esc(label || human(status || "neutral"))}</span>`;
}
function matrix(headers, rows, empty, caption = "Evidence table") {
  if (!rows.length) return `<div class="empty">${esc(empty)}</div>`;
  return `<div class="table-wrap"><table><caption class="visually-hidden">${esc(caption)}</caption><thead><tr>${headers.map((value) => `<th scope="col">${esc(value)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}
function findingCard(item) {
  const paths = (item.paths || [])
    .map((path) => `<li><code>${esc(path)}</code></li>`)
    .join("");
  return `<article class="finding ${esc(item.severity)}"><div class="finding-title"><span>${esc(String(item.severity || "info").toUpperCase())}</span><div><h3>${esc(item.title)}</h3><code>${esc(item.code || "")}</code></div></div><p>${esc(item.detail)}</p>${item.action ? `<div class="finding-action"><strong>Required action</strong><p>${esc(item.action)}</p></div>` : ""}${paths ? `<details><summary>${(item.paths || []).length} affected location(s)</summary><ul>${paths}</ul></details>` : ""}</article>`;
}
function portfolioBanner() {
  if (!state?.portfolio) return "";
  const projects = state.projects || [];
  const failed = projects.filter(
    (item) => item.latest && item.latest.status !== "pass",
  ).length;
  const green = projects.filter(
    (item) => item.latest?.status === "pass",
  ).length;
  const noRun = projects.filter((item) => !item.latest).length;
  return `<div class="portfolio-summary"><strong>${projects.length} repositories</strong><span>${green} green</span><span>${failed} failing</span><span>${noRun} without evidence</span></div><div class="project-picker">${projects
    .map((item, index) => {
      const name = item.project?.name || item.root || `Project ${index + 1}`;
      const status = item.error
        ? "configuration_error"
        : item.latest?.status || "neutral";
      return `<button class="project-chip ${index === selectedIndex ? "selected" : ""}" data-project-index="${index}"><span class="dot ${esc(status)}"></span><span>${esc(name)}</span><small>${esc(item.latest?.profile || "no evidence")}</small></button>`;
    })
    .join(
      "",
    )}</div><p>Portfolio mode is read-only. Select a repository to inspect stored evidence; execute checks from its own control surface.</p>`;
}
function actionStatus() {
  const entries = Object.entries(state?.actions || {});
  const running = entries.filter(([, value]) => value === "running");
  const banner = $("#action-banner");
  if (!entries.length) {
    banner.classList.add("hidden");
    return;
  }
  banner.classList.remove("hidden");
  banner.className = `action-banner ${running.length ? "running" : ""}`;
  setSafeHTML(
    banner,
    entries
      .map(
        ([name, value]) =>
          `<span><strong>${esc(name)}</strong> ${esc(human(value))}</span>`,
      )
      .join(""),
  );
}
function renderDecision(item) {
  const owner = item.owner_status || {};
  const decisions = owner.decisions || {};
  const merge = decisions.merge;
  if (merge) {
    const lead = merge.reasons?.[0];
    const status =
      merge.state === "blocked"
        ? "quality_failure"
        : merge.state === "ready_for_authoritative_check"
          ? "pass"
          : "review";
    const title =
      merge.state === "blocked"
        ? "Do not merge"
        : merge.state === "ready_for_authoritative_check"
          ? "Ready for the authoritative merge check"
          : "Merge is not proven";
    const detail =
      lead?.message ||
      "Local evidence cannot grant repository-hosted merge authority.";
    const node = $("#decision-strip");
    node.className = `decision-strip ${status}`;
    setSafeHTML(
      node,
      `<div><p class="eyebrow">Owner decision</p><strong>${esc(title)}</strong><span>${esc(detail)}</span>${lead?.action ? `<p class="decision-action"><b>Next:</b> ${esc(lead.action)}</p>` : ""}</div><div class="decision-meta"><span>${esc(human(item.risk?.selected_risk_profile || "risk unresolved"))}</span><span>${esc(human(owner.review_freshness?.state || "review unknown"))}</span></div>`,
    );
    const announcement = `${title}. ${detail}`;
    if (announcement !== lastDecisionAnnouncement) {
      $("#decision-announcement").textContent = announcement;
      lastDecisionAnnouncement = announcement;
    }
    return;
  }
  const latest = item.latest;
  const review = item.review;
  const risk = item.risk || {};
  const onboarding = item.onboarding?.current || {};
  const blockers = review?.summary?.blockers ?? 0;
  const prompts = review?.summary?.human_review ?? 0;
  const setupBlocked = (onboarding.summary?.blockers || 0) > 0;
  let status = "neutral",
    title = "No current decision",
    detail = "Generate deterministic evidence and a review packet.";
  if (setupBlocked) {
    status = "configuration_error";
    title = "Setup controls are incomplete";
    detail = `${onboarding.summary.blockers} onboarding blocker(s) must be resolved before guarded agent autonomy.`;
  } else if (blockers) {
    status = "quality_failure";
    title = "Change is blocked";
    detail = `${blockers} automated blocker(s) require correction and fresh evidence.`;
  } else if (prompts) {
    status = "review";
    title = "Human review required";
    detail = `${prompts} behavioral or approval decision(s) remain.`;
  } else if (latest?.status === "pass" && review) {
    status = "pass";
    title = "Current automated evidence is clear";
    detail = "Complete any risk-required human approval before release.";
  } else if (latest) {
    status = latest.status;
    title = `Latest ${latest.profile} run: ${human(latest.status)}`;
    detail = "Open Evidence to inspect the gate that prevented a current pass.";
  }
  const node = $("#decision-strip");
  node.className = `decision-strip ${status}`;
  setSafeHTML(
    node,
    `<div><p class="eyebrow">Current disposition</p><strong>${esc(title)}</strong><span>${esc(detail)}</span></div><div class="decision-meta"><span>${esc(human(risk.selected_risk_profile || "risk unresolved"))}</span><span>${esc(review?.summary?.evidence_status || "evidence unknown")}</span></div>`,
  );
}
function decisionCard(name, decision = {}) {
  const reason = decision.reasons?.[0];
  const semantic =
    decision.state === "allowed" ||
    decision.state === "ready_for_authoritative_check"
      ? "pass"
      : decision.state === "blocked"
        ? "quality_failure"
        : "neutral";
  const symbol =
    semantic === "pass" ? "✓" : semantic === "quality_failure" ? "!" : "?";
  return `<article class="decision-card ${semantic}"><div class="decision-card-head"><span class="decision-symbol" aria-hidden="true">${symbol}</span><div><p>${esc(name)}</p><strong>${esc(human(decision.state || "not proven"))}</strong></div></div><p>${esc(reason?.message || "No trusted decision evidence is available.")}</p><small>${reason?.action ? `<b>Next:</b> ${esc(reason.action)}` : "No next action recorded."}</small></article>`;
}
function renderOwnerOverview(item) {
  const owner = item.owner_status || {};
  const decisions = owner.decisions || {};
  setSafeHTML(
    $("#owner-decision-deck"),
    ["develop", "merge", "release"]
      .map((name) => decisionCard(name, decisions[name]))
      .join(""),
  );
  setSafeHTML(
    $("#evidence-ledger"),
    matrix(
      ["Profile", "Freshness", "Manifest", "Run"],
      (owner.evidence || []).map(
        (value) =>
          `<tr><td><code>${esc(value.profile)}</code></td><td>${badge(value.state)}</td><td>${esc(value.manifest_verified ? "verified" : "not verified")}</td><td><code>${esc(value.run_id || "—")}</code></td></tr>`,
      ),
      "No required profile evidence is resolved.",
      "Required evidence freshness",
    ),
  );
  const retro = owner.retrospective || {};
  const counts = [
    [
      "Inherited debt",
      retro.inherited_debt || 0,
      "Reported, not a current regression",
    ],
    [
      "New regressions",
      (retro.regressions || 0) + (retro.new_debt || 0),
      "Blocks until resolved",
    ],
    [
      "Missing evidence",
      retro.missing_evidence || 0,
      "Unknown is never a pass",
    ],
    [
      "Infrastructure errors",
      retro.infrastructure_errors || 0,
      "Measurement unusable",
    ],
    [
      "Unknown product intent",
      retro.unknown_product_intent || 0,
      "Requires an owner decision",
    ],
  ];
  setSafeHTML(
    $("#debt-summary"),
    `<div class="ledger-list">${counts
      .map(
        ([label, count, detail]) =>
          `<div><span>${esc(label)}</span><strong>${esc(count)}</strong><small>${esc(detail)}</small></div>`,
      )
      .join("")}</div>`,
  );
  const council = owner.council || { state: "not_configured" };
  setSafeHTML(
    $("#council-summary"),
    council.state === "not_configured"
      ? `<div class="empty"><strong>No council evidence configured.</strong><p>Deterministic checks and required human authorities are unchanged. Agent consensus is not being assumed.</p></div>`
      : `<div class="council-result"><strong>${esc(human(council.state))}</strong><span>${esc(council.members?.length || 0)} member result(s)</span><span>${esc(council.dissent?.length || 0)} dissent item(s)</span></div>`,
  );
}
function renderOverview(item) {
  const p = item.project || {};
  const latest = item.latest;
  const review = item.review;
  const risk = item.risk || {};
  const onboarding = item.onboarding?.current || {};
  const blockers = review?.summary?.blockers ?? 0;
  const prompts = review?.summary?.human_review ?? 0;
  const warnings = review?.summary?.warnings ?? 0;
  const actionRunning = Object.values(state.actions || {}).some(
    (value) => value === "running",
  );
  const metrics = [
    [
      "Latest status",
      latest?.status || "No run",
      latest
        ? `${latest.profile} · ${duration(latest.duration_ms)}`
        : "No deterministic profile evidence",
    ],
    [
      "Risk profile",
      risk.selected_risk_profile || "Unresolved",
      `minimum ${risk.minimum_risk_profile || "unknown"}`,
    ],
    [
      "Review blockers",
      blockers,
      blockers
        ? "Must be resolved"
        : `${prompts} human prompt(s) · ${warnings} warning(s)`,
    ],
    [
      "Approvals",
      item.approvals?.errors?.length ? "Pending" : "Current",
      `${item.approvals?.required?.length || 0} required`,
    ],
    [
      "Onboarding",
      onboarding.summary?.ready_for_guarded_use ? "Ready" : "Blocked",
      `${onboarding.summary?.blockers || 0} blocker(s)`,
    ],
    [
      "Evidence runs",
      item.runs?.length || 0,
      actionRunning
        ? "A check is running"
        : latest?.revision?.slice(0, 12) || "No revision",
    ],
  ];
  setSafeHTML(
    $("#metrics"),
    metrics
      .map(
        ([label, value, small]) =>
          `<article class="metric"><label>${esc(label)}</label><strong>${esc(human(value))}</strong><small>${esc(small)}</small></article>`,
      )
      .join(""),
  );
  renderOwnerOverview(item);
  $("#latest-badge").className = `badge ${latest?.status || "neutral"}`;
  $("#latest-badge").textContent = human(latest?.status || "No run");
  $("#risk-badge").className =
    `badge ${item.risk_errors?.length ? "configuration_error" : "review"}`;
  $("#risk-badge").textContent = human(
    risk.selected_risk_profile || "Unresolved",
  );
  setSafeHTML(
    $("#risk-overview"),
    `<div class="risk-callout"><strong>${esc(human(risk.selected_risk_profile || "Unresolved"))}</strong><span>deterministic minimum ${esc(human(risk.minimum_risk_profile || "unknown"))}</span></div><div class="chip-row">${(risk.required_execution_profiles || []).map((name) => `<span class="chip">${esc(name)}</span>`).join("") || '<span class="muted">No required profiles resolved.</span>'}</div><dl class="compact"><div><dt>Evidence</dt><dd>${esc(review?.summary?.evidence_status || "not generated")}</dd></div><div><dt>Approvals</dt><dd>${esc(review?.summary?.approval_status || human(item.approvals?.errors?.length ? "missing_or_stale" : "current"))}</dd></div></dl>`,
  );
  $("#gate-map").classList.toggle("empty", !latest?.gates?.length);
  setSafeHTML(
    $("#gate-map"),
    latest?.gates?.length
      ? latest.gates
          .map(
            (g) =>
              `<div class="gate"><div><span class="dot ${esc(g.status)}"></span><strong>${esc(g.name)}</strong></div><small>${esc(human(g.status))} · ${duration(g.duration_ms)}</small></div>`,
          )
          .join("")
      : "No evidence yet.",
  );
  const findings = review?.findings || [];
  setSafeHTML(
    $("#review-preview"),
    findings.slice(0, 4).map(findingCard).join("") ||
      '<div class="empty">Generate a review packet to classify the current diff.</div>',
  );
  setSafeHTML(
    $("#adapter-grid"),
    Object.entries(p.stacks || {})
      .map(
        ([name, enabled]) =>
          `<div class="adapter ${enabled ? "enabled" : "disabled"}"><span class="dot ${enabled ? "pass" : "neutral"}"></span><div><strong>${esc(name)}</strong><small>${enabled ? "detected and managed" : "not detected"}</small></div></div>`,
      )
      .join(""),
  );
}
function renderRuns(item) {
  const latest = item.latest;
  setSafeHTML(
    $("#history-table"),
    matrix(
      [
        "Run",
        "Profile",
        "Status",
        "Duration",
        "Revision",
        "Change fingerprint",
      ],
      (item.runs || []).map(
        (r) =>
          `<tr><td><code>${esc(r.run_id)}</code></td><td>${esc(r.profile)}</td><td>${badge(r.status)}</td><td>${duration(r.duration_ms)}</td><td><code>${esc((r.revision || "").slice(0, 12))}</code></td><td><code>${esc((r.change_fingerprint || "").slice(0, 12))}</code></td></tr>`,
      ),
      "No runs recorded.",
    ),
  );
  setSafeHTML(
    $("#gates-table"),
    matrix(
      ["Gate", "Status", "Duration", "Exit"],
      (latest?.gates || []).map(
        (g) =>
          `<tr><td><strong>${esc(g.name)}</strong></td><td>${badge(g.status)}</td><td>${duration(g.duration_ms)}</td><td><code>${esc(g.exit_code)}</code></td></tr>`,
      ),
      "No gate evidence.",
    ),
  );
}
function renderReview(item) {
  const review = item.review;
  const findings = review?.findings || [];
  setSafeHTML(
    $("#review-full"),
    findings.map(findingCard).join("") ||
      '<div class="empty">No stored review packet. Generate one after the final change.</div>',
  );
  setSafeHTML(
    $("#evidence-matrix"),
    matrix(
      ["Profile", "Status", "Run"],
      (review?.evidence || []).map(
        (value) =>
          `<tr><td><code>${esc(value.profile)}</code></td><td>${badge(value.status, value.status === "current_pass" ? "current pass" : human(value.status))}</td><td><code>${esc(value.run_id || "—")}</code></td></tr>`,
      ),
      "No profile evidence matrix.",
    ),
  );
  const approvals = review?.approvals || item.approvals || {};
  setSafeHTML(
    $("#approval-matrix"),
    matrix(
      ["Approval", "Status", "Detail"],
      (approvals.required || []).map((kind) => {
        const result = approvals.results?.[kind] || {};
        const errors = result.errors || [];
        return `<tr><td><code>${esc(kind)}</code></td><td>${badge(errors.length ? "missing_or_stale" : "current")}</td><td>${esc(errors.slice(0, 2).join("; ") || "fingerprints match current review surface")}</td></tr>`;
      }),
      "No approval record is required at this profile.",
    ),
  );
}
function renderSetup(item) {
  const bundle = item.onboarding || {};
  const onboarding = bundle.current || {};
  const summary = onboarding.summary || {};
  $("#onboarding-badge").className =
    `badge ${summary.blockers ? "configuration_error" : bundle.stale ? "review" : "pass"}`;
  $("#onboarding-badge").textContent = summary.blockers
    ? `${summary.blockers} blocker(s)`
    : bundle.stale
      ? "stale"
      : "ready";
  setSafeHTML(
    $("#setup-stages"),
    (onboarding.stages || [])
      .map(
        (stage, index) =>
          `<div class="stage ${esc(stage.status)}"><div class="stage-index">${String(index + 1).padStart(2, "0")}</div><div><strong>${esc(stage.title)}</strong><small>${esc(human(stage.status))}</small><code>${esc(stage.command)}</code></div></div>`,
      )
      .join("") || '<div class="empty">No onboarding plan generated.</div>',
  );
  const next = onboarding.next_action || {};
  setSafeHTML(
    $("#next-action"),
    `<div class="next-card ${esc(next.severity || "info")}"><span>${esc(String(next.severity || "info").toUpperCase())}</span><h3>${esc(next.message || "No action resolved")}</h3><code>${esc(next.next_step || "")}</code>${bundle.stale ? "<p>Stored onboarding state is stale. Run <code>qg onboarding refresh</code>.</p>" : ""}</div>`,
  );
  setSafeHTML(
    $("#onboarding-gaps"),
    (onboarding.gaps || [])
      .map(
        (gap) =>
          `<article class="gap ${esc(gap.severity)}"><div><span>${esc(String(gap.severity).toUpperCase())}</span><strong>${esc(gap.message)}</strong></div><code>${esc(gap.code)}</code><p>${esc(gap.next_step)}</p></article>`,
      )
      .join("") || '<div class="empty">No generated setup gap remains.</div>',
  );
}
function renderPolicy(item) {
  $("#config-json").textContent = JSON.stringify(
    {
      project: item.project,
      profiles: item.profiles,
      risk_profiles: item.risk_profiles,
      risk: item.risk,
      gate_applicability: item.project?.gates,
      onboarding_fingerprint: item.onboarding?.current?.state_fingerprint,
    },
    null,
    2,
  );
}
function render() {
  const item = project();
  if (item.error) {
    $("#project-name").textContent = "Repository unavailable";
    $("#project-root").textContent = item.root || "";
    setSafeHTML(
      $("#decision-strip"),
      `<strong>Configuration error</strong><span>${esc(item.error)}</span>`,
    );
    return;
  }
  const p = item.project || {};
  $("#project-name").textContent =
    p.name ||
    (state.portfolio ? "Portfolio quality control" : "Quality control");
  $("#project-root").textContent = state.portfolio
    ? `${state.projects.length} registered projects · ${item.root || ""}`
    : item.root || "";
  $("#portfolio-banner").classList.toggle("hidden", !state.portfolio);
  if (state.portfolio) setSafeHTML($("#portfolio-banner"), portfolioBanner());
  $("#mode-label").textContent = state.portfolio
    ? "portfolio read-only"
    : config.actions_enabled
      ? "actions enabled"
      : "read-only";
  renderDecision(item);
  renderOverview(item);
  renderRuns(item);
  renderReview(item);
  renderSetup(item);
  renderPolicy(item);
  actionStatus();
  const busy = Object.values(state.actions || {}).some(
    (value) => value === "running",
  );
  $("#run-profile").disabled =
    !config.actions_enabled || state.portfolio || busy;
  $("#generate-review").disabled =
    !config.actions_enabled || state.portfolio || busy;
  $("#regenerate-review").disabled =
    !config.actions_enabled || state.portfolio || busy;
  $$("[data-project-index]").forEach((button) =>
    button.addEventListener("click", () => {
      selectedIndex = Number(button.dataset.projectIndex || 0);
      render();
    }),
  );
}
async function load() {
  try {
    [state, config] = await Promise.all([
      fetchJSON("/api/status"),
      fetchJSON("/api/config"),
    ]);
    selectedIndex = Math.min(
      selectedIndex,
      Math.max(0, (state.projects?.length || 1) - 1),
    );
    $("#connection").textContent = "Live";
    render();
  } catch (error) {
    $("#connection").textContent = "Disconnected";
    toast(error.message);
  }
}
function token() {
  let value = sessionStorage.getItem("aqg-action-token");
  if (!value) {
    value =
      prompt(
        "Paste the ephemeral AQG action token printed by the dashboard process",
      ) || "";
    if (value) sessionStorage.setItem("aqg-action-token", value);
  }
  return value;
}
async function action(path, body = {}) {
  const value = token();
  if (!value) return;
  try {
    await fetchJSON(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-AQG-Token": value },
      body: JSON.stringify(body),
    });
    toast("Action accepted");
    setTimeout(load, 700);
  } catch (error) {
    if (/token/i.test(error.message))
      sessionStorage.removeItem("aqg-action-token");
    toast(error.message);
  }
}
function openView(name) {
  $$(".nav").forEach((node) => {
    node.classList.remove("active");
    node.setAttribute("aria-selected", "false");
    node.tabIndex = -1;
  });
  $$(".view").forEach((node) => {
    node.classList.remove("active");
    node.hidden = true;
  });
  const nav = $(`.nav[data-view="${name}"]`);
  const view = $(`#view-${name}`);
  if (nav && view) {
    nav.classList.add("active");
    nav.setAttribute("aria-selected", "true");
    nav.tabIndex = 0;
    view.classList.add("active");
    view.hidden = false;
    document.title = `${nav.textContent.trim()} · AQG Control Surface`;
  }
}
$$(".nav").forEach((button) =>
  button.addEventListener("click", () => openView(button.dataset.view)),
);
$(".rail nav").addEventListener("keydown", (event) => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const tabs = $$(".nav");
  const current = tabs.indexOf(document.activeElement);
  let next =
    event.key === "Home"
      ? 0
      : event.key === "End"
        ? tabs.length - 1
        : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) %
          tabs.length;
  event.preventDefault();
  tabs[next].focus();
  openView(tabs[next].dataset.view);
});
$$("[data-jump]").forEach((button) =>
  button.addEventListener("click", () => openView(button.dataset.jump)),
);
$("#refresh").addEventListener("click", load);
$("#auto-refresh").addEventListener("click", (event) => {
  autoRefresh = !autoRefresh;
  event.currentTarget.setAttribute("aria-pressed", String(autoRefresh));
  event.currentTarget.textContent = `Auto refresh: ${autoRefresh ? "on" : "off"}`;
  clearInterval(refreshTimer);
  refreshTimer = autoRefresh ? setInterval(load, 10000) : null;
});
$("#run-profile").addEventListener("click", () =>
  action("/api/actions/check", { profile: $("#profile-select").value }),
);
$("#generate-review").addEventListener("click", () =>
  action("/api/actions/review"),
);
$("#regenerate-review").addEventListener("click", () =>
  action("/api/actions/review"),
);
load();
