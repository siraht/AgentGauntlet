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
function ownerDecisionPresentation(state) {
  const presentations = {
    works: { status: "pass", title: "Functional checks passed" },
    not_tested: { status: "review", title: "Not tested" },
    broken: { status: "quality_failure", title: "Functional defect found" },
    unusable: { status: "configuration_error", title: "Evidence unusable" },
    human_decision_needed: {
      status: "review",
      title: "Human decision needed",
    },
    blocked: { status: "quality_failure", title: "Do not merge" },
    ready_for_authoritative_check: {
      status: "pass",
      title: "Ready for the authoritative merge check",
    },
  };
  return (
    presentations[state] || { status: "review", title: "Merge is not proven" }
  );
}
function decisionStripMarkup(label, title, detail, meta, action = "") {
  const metaMarkup = meta.map((value) => `<span>${esc(value)}</span>`).join("");
  return `<div><p class="eyebrow">${esc(label)}</p><strong>${esc(title)}</strong><span>${esc(detail)}</span>${action}</div><div class="decision-meta">${metaMarkup}</div>`;
}
function announceDecision(title, detail) {
  const announcement = `${title}. ${detail}`;
  if (announcement === lastDecisionAnnouncement) return;
  $("#decision-announcement").textContent = announcement;
  lastDecisionAnnouncement = announcement;
}
function ownerDecisionDetail(lead) {
  return (
    lead?.message ||
    "Local evidence cannot grant repository-hosted merge authority."
  );
}
function ownerDecisionAction(lead) {
  if (!lead?.action) return "";
  return `<p class="decision-action"><b>Next:</b> ${esc(lead.action)}</p>`;
}
function renderOwnerDecision(item, merge) {
  const owner = item.owner_status || {};
  const lead = (merge.reasons || [])[0];
  const presentation = ownerDecisionPresentation(
    merge.functional_state || merge.state,
  );
  const detail = ownerDecisionDetail(lead);
  const action = ownerDecisionAction(lead);
  const meta = [
    human(item.risk?.selected_risk_profile || "risk unresolved"),
    human(owner.review_freshness?.state || "review unknown"),
  ];
  const node = $("#decision-strip");
  node.className = `decision-strip ${presentation.status}`;
  setSafeHTML(
    node,
    decisionStripMarkup(
      "Owner decision",
      presentation.title,
      detail,
      meta,
      action,
    ),
  );
  announceDecision(presentation.title, detail);
}
function legacyReviewContext(item) {
  const review = item.review;
  const risk = item.risk || {};
  const blockers = review?.summary?.blockers ?? 0;
  const prompts = review?.summary?.human_review ?? 0;
  return { review, risk, blockers, prompts };
}
function legacyOnboardingContext(item) {
  const onboarding = item.onboarding?.current || {};
  const setupBlocked = (onboarding.summary?.blockers || 0) > 0;
  return { onboarding, setupBlocked };
}
function legacyDecisionContext(item) {
  return {
    latest: item.latest,
    ...legacyReviewContext(item),
    ...legacyOnboardingContext(item),
  };
}
function legacySetupDecision(context) {
  if (!context.setupBlocked) return null;
  return {
    status: "configuration_error",
    title: "Setup controls are incomplete",
    detail: `${context.onboarding.summary.blockers} onboarding blocker(s) must be resolved before guarded agent autonomy.`,
    risk: context.risk,
    review: context.review,
  };
}
function legacyReviewDecision(context) {
  if (context.blockers)
    return {
      status: "quality_failure",
      title: "Change is blocked",
      detail: `${context.blockers} automated blocker(s) require correction and fresh evidence.`,
      risk: context.risk,
      review: context.review,
    };
  if (context.prompts)
    return {
      status: "review",
      title: "Human review required",
      detail: `${context.prompts} behavioral or approval decision(s) remain.`,
      risk: context.risk,
      review: context.review,
    };
  return null;
}
function legacyEvidenceDecision(context) {
  const { latest, review, risk } = context;
  if (latest?.status === "pass" && review)
    return {
      status: "pass",
      title: "Current automated evidence is clear",
      detail: "Complete any risk-required human approval before release.",
      risk,
      review,
    };
  if (latest)
    return {
      status: latest.status,
      title: `Latest ${latest.profile} run: ${human(latest.status)}`,
      detail:
        "Open Evidence to inspect the gate that prevented a current pass.",
      risk,
      review,
    };
  return {
    status: "neutral",
    title: "No current decision",
    detail: "Generate deterministic evidence and a review packet.",
    risk,
    review,
  };
}
function legacyDecision(item) {
  const context = legacyDecisionContext(item);
  return (
    legacySetupDecision(context) ||
    legacyReviewDecision(context) ||
    legacyEvidenceDecision(context)
  );
}
function renderLegacyDecision(item) {
  const decision = legacyDecision(item);
  const node = $("#decision-strip");
  node.className = `decision-strip ${decision.status}`;
  const meta = [
    human(decision.risk.selected_risk_profile || "risk unresolved"),
    decision.review?.summary?.evidence_status || "evidence unknown",
  ];
  setSafeHTML(
    node,
    decisionStripMarkup(
      "Current disposition",
      decision.title,
      decision.detail,
      meta,
    ),
  );
}
function renderDecision(item) {
  const merge = item.owner_status?.decisions?.merge;
  if (merge) return renderOwnerDecision(item, merge);
  renderLegacyDecision(item);
}
function decisionSemantic(state) {
  if (state === "works") return "pass";
  if (state === "broken") return "quality_failure";
  if (state === "unusable") return "configuration_error";
  if (state === "human_decision_needed") return "review";
  if (state === "not_tested") return "neutral";
  if (["allowed", "ready_for_authoritative_check"].includes(state))
    return "pass";
  if (state === "blocked") return "quality_failure";
  return "neutral";
}
function decisionCard(name, decision = {}) {
  const reason = decision.reasons?.[0];
  const displayedState = decision.functional_state || decision.state;
  const semantic = decisionSemantic(displayedState);
  const symbols = {
    pass: "✓",
    quality_failure: "!",
    configuration_error: "×",
    review: "•",
    neutral: "?",
  };
  const symbol = symbols[semantic];
  return `<article class="decision-card ${semantic}"><div class="decision-card-head"><span class="decision-symbol" aria-hidden="true">${symbol}</span><div><p>${esc(name)}</p><strong>${esc(human(displayedState || "not tested"))}</strong></div></div><p>${esc(reason?.message || "No functional problem is reported by current evidence.")}</p><small>${reason?.action ? `<b>Next:</b> ${esc(reason.action)}` : "No next action recorded."}</small></article>`;
}
function renderDecisionDeck(owner) {
  const decisions = owner.decisions || {};
  setSafeHTML(
    $("#owner-decision-deck"),
    ["develop", "merge", "release"]
      .map((name) => decisionCard(name, decisions[name]))
      .join(""),
  );
}
function renderEvidenceLedger(owner) {
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
}
function retrospectiveCounts(retro) {
  return [
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
}
function renderDebtSummary(owner) {
  const counts = retrospectiveCounts(owner.retrospective || {});
  setSafeHTML(
    $("#debt-summary"),
    `<div class="ledger-list">${counts
      .map(
        ([label, count, detail]) =>
          `<div><span>${esc(label)}</span><strong>${esc(count)}</strong><small>${esc(detail)}</small></div>`,
      )
      .join("")}</div>`,
  );
}
function councilEmptyMarkup(state) {
  const messages = {
    not_configured:
      "<strong>No council evidence configured.</strong><p>Deterministic checks and required human authorities are unchanged. Agent consensus is not being assumed.</p>",
    stale:
      "<strong>Council evidence is stale.</strong><p>It reviewed a different candidate or policy surface and cannot describe this change.</p>",
    invalid:
      "<strong>Council evidence is invalid.</strong><p>The immutable record could not be verified. Treat the review as unavailable.</p>",
  };
  return messages[state];
}
function renderCouncilSummary(owner) {
  const council = owner.council || { state: "not_configured" };
  const councilDetail = councilEmptyMarkup(council.state);
  setSafeHTML(
    $("#council-summary"),
    councilDetail
      ? `<div class="empty">${councilDetail}</div>`
      : `<div class="council-result"><strong>${esc(human(council.status || council.state))}</strong><span>${esc(council.members?.length || 0)} valid ballot(s) from ${esc(council.provider_groups?.length || 0)} independent provider group(s)</span><span>${council.dissent?.present ? "Provider dissent is present" : "No provider dissent recorded"}</span><small>Agent advisory — not an approval or release authority.</small></div>`,
  );
}
function renderOwnerOverview(item) {
  const owner = item.owner_status || {};
  renderDecisionDeck(owner);
  renderEvidenceLedger(owner);
  renderDebtSummary(owner);
  renderCouncilSummary(owner);
}
function latestMetric(item) {
  const latest = item.latest;
  const detail = latest
    ? `${latest.profile} · ${duration(latest.duration_ms)}`
    : "No deterministic profile evidence";
  return ["Latest status", latest?.status || "No run", detail];
}
function riskMetric(item) {
  const risk = item.risk || {};
  return [
    "Risk profile",
    risk.selected_risk_profile || "Unresolved",
    `minimum ${risk.minimum_risk_profile || "unknown"}`,
  ];
}
function reviewMetric(item) {
  const summary = item.review?.summary || {};
  const blockers = summary.blockers ?? 0;
  const detail = blockers
    ? "Must be resolved"
    : `${summary.human_review ?? 0} human prompt(s) · ${summary.warnings ?? 0} warning(s)`;
  return ["Review blockers", blockers, detail];
}
function approvalMetric(item) {
  const approvals = item.approvals || {};
  return [
    "Reserved authority",
    approvals.errors?.length
      ? "Pending"
      : approvals.required?.length
        ? "Current"
        : "Not required",
    `${approvals.required?.length || 0} required`,
  ];
}
function onboardingMetric(item) {
  const summary = item.onboarding?.current?.summary || {};
  return [
    "Onboarding",
    summary.ready_for_guarded_use ? "Ready" : "Blocked",
    `${summary.blockers || 0} blocker(s)`,
  ];
}
function evidenceRunMetric(item) {
  const latest = item.latest;
  const actionRunning = Object.values(state.actions || {}).some(
    (value) => value === "running",
  );
  const detail = actionRunning
    ? "A check is running"
    : latest?.revision?.slice(0, 12) || "No revision";
  return ["Evidence runs", item.runs?.length || 0, detail];
}
function overviewMetrics(item) {
  return [
    latestMetric(item),
    riskMetric(item),
    reviewMetric(item),
    approvalMetric(item),
    onboardingMetric(item),
    evidenceRunMetric(item),
  ];
}
function renderMetrics(item) {
  setSafeHTML(
    $("#metrics"),
    overviewMetrics(item)
      .map(
        ([label, value, small]) =>
          `<article class="metric"><label>${esc(label)}</label><strong>${esc(human(value))}</strong><small>${esc(small)}</small></article>`,
      )
      .join(""),
  );
}
function renderOverviewBadges(item) {
  const latest = item.latest;
  const risk = item.risk || {};
  $("#latest-badge").className = `badge ${latest?.status || "neutral"}`;
  $("#latest-badge").textContent = human(latest?.status || "No run");
  $("#risk-badge").className =
    `badge ${item.risk_errors?.length ? "configuration_error" : "review"}`;
  $("#risk-badge").textContent = human(
    risk.selected_risk_profile || "Unresolved",
  );
}
function riskCalloutMarkup(risk) {
  const selected = risk.selected_risk_profile || "Unresolved";
  const minimum = risk.minimum_risk_profile || "unknown";
  return `<div class="risk-callout"><strong>${esc(human(selected))}</strong><span>deterministic minimum ${esc(human(minimum))}</span></div>`;
}
function executionProfilesMarkup(risk) {
  const profiles = risk.required_execution_profiles || [];
  const chips = profiles
    .map((name) => `<span class="chip">${esc(name)}</span>`)
    .join("");
  return `<div class="chip-row">${chips || '<span class="muted">No required profiles resolved.</span>'}</div>`;
}
function riskEvidenceMarkup(item) {
  const summary = item.review?.summary || {};
  const approvals = item.approvals || {};
  const evidence = summary.evidence_status || "not generated";
  const approval =
    summary.approval_status ||
    human(approvals.errors?.length ? "missing_or_stale" : "current");
  return `<dl class="compact"><div><dt>Evidence</dt><dd>${esc(evidence)}</dd></div><div><dt>Approvals</dt><dd>${esc(approval)}</dd></div></dl>`;
}
function renderRiskOverview(item) {
  const risk = item.risk || {};
  setSafeHTML(
    $("#risk-overview"),
    `${riskCalloutMarkup(risk)}${executionProfilesMarkup(risk)}${riskEvidenceMarkup(item)}`,
  );
}
function renderGateMap(item) {
  const latest = item.latest;
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
}
function renderReviewPreview(item) {
  const findings = item.review?.findings || [];
  setSafeHTML(
    $("#review-preview"),
    findings.slice(0, 4).map(findingCard).join("") ||
      '<div class="empty">Generate a review packet to classify the current diff.</div>',
  );
}
function renderAdapterGrid(item) {
  const stacks = item.project?.stacks || {};
  setSafeHTML(
    $("#adapter-grid"),
    Object.entries(stacks)
      .map(
        ([name, enabled]) =>
          `<div class="adapter ${enabled ? "enabled" : "disabled"}"><span class="dot ${enabled ? "pass" : "neutral"}"></span><div><strong>${esc(name)}</strong><small>${enabled ? "detected and managed" : "not detected"}</small></div></div>`,
      )
      .join(""),
  );
}
function renderOverview(item) {
  renderMetrics(item);
  renderOwnerOverview(item);
  renderOverviewBadges(item);
  renderRiskOverview(item);
  renderGateMap(item);
  renderReviewPreview(item);
  renderAdapterGrid(item);
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
function renderOnboardingBadge(bundle, onboarding) {
  const summary = onboarding.summary || {};
  $("#onboarding-badge").className =
    `badge ${summary.blockers ? "configuration_error" : bundle.stale ? "review" : "pass"}`;
  $("#onboarding-badge").textContent = summary.blockers
    ? `${summary.blockers} blocker(s)`
    : bundle.stale
      ? "stale"
      : "ready";
}
function renderSetupStages(onboarding) {
  setSafeHTML(
    $("#setup-stages"),
    (onboarding.stages || [])
      .map(
        (stage, index) =>
          `<div class="stage ${esc(stage.status)}"><div class="stage-index">${String(index + 1).padStart(2, "0")}</div><div><strong>${esc(stage.title)}</strong><small>${esc(human(stage.status))}</small><code>${esc(stage.command)}</code></div></div>`,
      )
      .join("") || '<div class="empty">No onboarding plan generated.</div>',
  );
}
function renderNextAction(bundle, onboarding) {
  const next = onboarding.next_action || {};
  setSafeHTML(
    $("#next-action"),
    `<div class="next-card ${esc(next.severity || "info")}"><span>${esc(String(next.severity || "info").toUpperCase())}</span><h3>${esc(next.message || "No action resolved")}</h3><code>${esc(next.next_step || "")}</code>${bundle.stale ? "<p>Stored onboarding state is stale. Run <code>qg onboarding refresh</code>.</p>" : ""}</div>`,
  );
}
function renderOnboardingGaps(onboarding) {
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
function renderSetup(item) {
  const bundle = item.onboarding || {};
  const onboarding = bundle.current || {};
  renderOnboardingBadge(bundle, onboarding);
  renderSetupStages(onboarding);
  renderNextAction(bundle, onboarding);
  renderOnboardingGaps(onboarding);
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
function renderUnavailable(item) {
  if (!item.error) return false;
  $("#project-name").textContent = "Repository unavailable";
  $("#project-root").textContent = item.root || "";
  setSafeHTML(
    $("#decision-strip"),
    `<strong>Configuration error</strong><span>${esc(item.error)}</span>`,
  );
  return true;
}
function renderProjectHeader(item) {
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
}
function renderProjectPanels(item) {
  renderDecision(item);
  renderOverview(item);
  renderRuns(item);
  renderReview(item);
  renderSetup(item);
  renderPolicy(item);
  actionStatus();
}
function renderActionAvailability() {
  const busy = Object.values(state.actions || {}).some(
    (value) => value === "running",
  );
  const disabled = !config.actions_enabled || state.portfolio || busy;
  $("#run-profile").disabled = disabled;
  $("#generate-review").disabled = disabled;
  $("#regenerate-review").disabled = disabled;
}
function bindPortfolioSelection() {
  $$("[data-project-index]").forEach((button) =>
    button.addEventListener("click", () => {
      selectedIndex = Number(button.dataset.projectIndex || 0);
      render();
    }),
  );
}
function render() {
  const item = project();
  if (renderUnavailable(item)) return;
  renderProjectHeader(item);
  renderProjectPanels(item);
  renderActionAvailability();
  bindPortfolioSelection();
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
// AQG_DASHBOARD_WIRING_START
$$(".nav").forEach((button) =>
  button.addEventListener("click", () => openView(button.dataset.view)),
);
$(".rail nav").addEventListener("keydown", (event) => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const tabs = $$(".nav");
  const current = tabs.indexOf(document.activeElement);
  const next =
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
