import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const projectRoot = process.cwd();
const dashboardScript = fs.readFileSync(
  path.join(projectRoot, "src", "aqg", "static", "app.js"),
  "utf8",
);

function dashboardModel() {
  const wiringMarker = '$$(".nav").forEach((button) =>';
  const modelSource = dashboardScript.slice(
    0,
    dashboardScript.indexOf(wiringMarker),
  );
  const context = {};
  vm.runInNewContext(
    `${modelSource}
globalThis.__aqgDashboardModel = {
  esc,
  human,
  duration,
  badge,
  matrix,
  findingCard,
  ownerDecisionPresentation,
  decisionStripMarkup,
  ownerDecisionDetail,
  ownerDecisionAction,
  legacyDecision,
  decisionSemantic,
  decisionCard,
  retrospectiveCounts,
  councilEmptyMarkup,
  latestMetric,
  riskMetric,
  reviewMetric,
  approvalMetric,
  onboardingMetric,
  riskCalloutMarkup,
  executionProfilesMarkup,
  riskEvidenceMarkup
};`,
    context,
  );
  return context.__aqgDashboardModel;
}

test("the dashboard exposes the unified control surfaces", () => {
  const html = fs.readFileSync(
    path.join(projectRoot, "src", "aqg", "static", "index.html"),
    "utf8",
  );
  const script = fs.readFileSync(
    path.join(projectRoot, "src", "aqg", "static", "app.js"),
    "utf8",
  );

  expect(html).toContain("Required proof");
  expect(html).toContain("Attention queue");
  expect(script).toContain("/api/status");
  expect(script).toContain("/api/config");
  expect(script).toContain("setSafeHTML");
  expect(script).toContain("AQG_REVIEWED_SECURITY");
  expect(script.match(/\.innerHTML\s*=/g)).toHaveLength(1);
});

test("the owner view exposes honest decisions and accessible navigation", () => {
  // Feature-Spec: AgentQualityGauntlet.OwnerStatus AQG-OWNER-001 AQG-OWNER-002
  const html = fs.readFileSync(
    path.join(projectRoot, "src", "aqg", "static", "index.html"),
    "utf8",
  );
  const script = fs.readFileSync(
    path.join(projectRoot, "src", "aqg", "static", "app.js"),
    "utf8",
  );

  expect(html).toContain('class="skip-link"');
  expect(html).toContain('role="tablist"');
  expect(html).toContain('id="owner-decision-deck"');
  expect(html).toContain("Agent advisory — not an approval");
  const decisionPositions = ["develop", "merge", "release"].map((decision) =>
    script.indexOf(`"${decision}"`),
  );
  expect(decisionPositions.every((position) => position >= 0)).toBe(true);
  expect(decisionPositions).toEqual(
    [...decisionPositions].sort((a, b) => a - b),
  );
  expect(script).toContain("No council evidence configured.");
  expect(script).toContain(
    "Agent advisory — not an approval or release authority.",
  );
  expect(script).toContain("Council evidence is stale.");
  expect(script).toContain("Auto refresh:");
});

test("dashboard text helpers escape untrusted content and format boundaries", () => {
  const { esc, human, duration, badge } = dashboardModel();

  expect(esc(`<script x="'">&`)).toBe(
    "&lt;script x=&quot;&#39;&quot;&gt;&amp;",
  );
  expect(esc(null)).toBe("");
  expect(human("missing_or_stale")).toBe("missing or stale");
  expect(
    [0, 999, 1000, 59999, 60000, 125000].map((value) => duration(value)),
  ).toEqual(["0ms", "999ms", "1.0s", "60.0s", "1m 0s", "2m 5s"]);
  expect(badge("quality_failure", `<unsafe>`)).toBe(
    '<span class="badge quality_failure">&lt;unsafe&gt;</span>',
  );
  expect(badge()).toBe('<span class="badge neutral">neutral</span>');
});

test("dashboard table and finding markup preserve semantics without injection", () => {
  const { matrix, findingCard } = dashboardModel();

  expect(matrix([], [], `<none>`)).toBe(
    '<div class="empty">&lt;none&gt;</div>',
  );
  expect(
    matrix(
      ["Name", `<Status>`],
      ["<tr><td>safe row</td></tr>"],
      "unused",
      `Evidence "table"`,
    ),
  ).toBe(
    '<div class="table-wrap"><table><caption class="visually-hidden">Evidence &quot;table&quot;</caption><thead><tr><th scope="col">Name</th><th scope="col">&lt;Status&gt;</th></tr></thead><tbody><tr><td>safe row</td></tr></tbody></table></div>',
  );
  const finding = findingCard({
    severity: "blocker",
    title: `<script>alert(1)</script>`,
    code: "AQG-X",
    detail: `bad & worse`,
    action: `fix "now"`,
    paths: ["src/<unsafe>.js"],
  });
  expect(finding).not.toContain("<script>");
  expect(finding).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
  expect(finding).toContain("bad &amp; worse");
  expect(finding).toContain("fix &quot;now&quot;");
  expect(finding).toContain("<summary>1 affected location(s)</summary>");
  expect(finding).toContain("<code>src/&lt;unsafe&gt;.js</code>");
});

test("owner and legacy decisions fail closed across every disposition", () => {
  const {
    ownerDecisionPresentation,
    ownerDecisionDetail,
    ownerDecisionAction,
    legacyDecision,
    decisionSemantic,
  } = dashboardModel();

  expect(ownerDecisionPresentation("blocked")).toEqual({
    status: "quality_failure",
    title: "Do not merge",
  });
  expect(ownerDecisionPresentation("ready_for_authoritative_check")).toEqual({
    status: "pass",
    title: "Ready for the authoritative merge check",
  });
  expect(ownerDecisionPresentation("unknown")).toEqual({
    status: "review",
    title: "Merge is not proven",
  });
  expect(ownerDecisionDetail()).toBe(
    "Local evidence cannot grant repository-hosted merge authority.",
  );
  expect(ownerDecisionAction()).toBe("");
  expect(ownerDecisionAction({ action: `<review>` })).toBe(
    '<p class="decision-action"><b>Next:</b> &lt;review&gt;</p>',
  );

  expect(
    legacyDecision({
      onboarding: { current: { summary: { blockers: 2 } } },
      risk: { selected_risk_profile: "high_assurance" },
    }),
  ).toMatchObject({
    status: "configuration_error",
    title: "Setup controls are incomplete",
  });
  expect(
    legacyDecision({ review: { summary: { blockers: 1, human_review: 0 } } }),
  ).toMatchObject({ status: "quality_failure", title: "Change is blocked" });
  expect(
    legacyDecision({ review: { summary: { blockers: 0, human_review: 3 } } }),
  ).toMatchObject({ status: "review", title: "Human review required" });
  expect(
    legacyDecision({
      latest: { status: "pass", profile: "fast" },
      review: { summary: {} },
    }),
  ).toMatchObject({
    status: "pass",
    title: "Current automated evidence is clear",
  });
  expect(
    legacyDecision({ latest: { status: "quality_failure", profile: "deep" } }),
  ).toMatchObject({
    status: "quality_failure",
    title: "Latest deep run: quality failure",
  });
  expect(legacyDecision({})).toMatchObject({
    status: "neutral",
    title: "No current decision",
  });
  expect(
    ["allowed", "ready_for_authoritative_check", "blocked", "unknown"].map(
      decisionSemantic,
    ),
  ).toEqual(["pass", "pass", "quality_failure", "neutral"]);
});

test("retrospective and council summaries keep unknowns visible", () => {
  const { retrospectiveCounts, councilEmptyMarkup } = dashboardModel();

  expect(
    retrospectiveCounts({
      inherited_debt: 4,
      regressions: 2,
      new_debt: 3,
      missing_evidence: 5,
      infrastructure_errors: 6,
      unknown_product_intent: 7,
    }),
  ).toEqual([
    ["Inherited debt", 4, "Reported, not a current regression"],
    ["New regressions", 5, "Blocks until resolved"],
    ["Missing evidence", 5, "Unknown is never a pass"],
    ["Infrastructure errors", 6, "Measurement unusable"],
    ["Unknown product intent", 7, "Requires an owner decision"],
  ]);
  expect(retrospectiveCounts({}).map((row) => row[1])).toEqual([0, 0, 0, 0, 0]);
  expect(councilEmptyMarkup("not_configured")).toContain(
    "Agent consensus is not being assumed.",
  );
  expect(councilEmptyMarkup("stale")).toContain("different candidate");
  expect(councilEmptyMarkup("invalid")).toContain("immutable record");
  expect(councilEmptyMarkup("current")).toBeUndefined();
});

test("dashboard metrics distinguish evidence, risk, review, and approval state", () => {
  const {
    latestMetric,
    riskMetric,
    reviewMetric,
    approvalMetric,
    onboardingMetric,
    riskCalloutMarkup,
    executionProfilesMarkup,
    riskEvidenceMarkup,
  } = dashboardModel();
  const item = {
    latest: { status: "pass", profile: "fast", duration_ms: 1250 },
    risk: {
      selected_risk_profile: "high_assurance",
      minimum_risk_profile: "standard",
      required_execution_profiles: ["deep", `<release>`],
    },
    review: {
      summary: {
        blockers: 0,
        human_review: 2,
        warnings: 1,
        evidence_status: "current",
      },
    },
    approvals: { required: ["manual-qa"], errors: ["missing"] },
    onboarding: {
      current: { summary: { ready_for_guarded_use: false, blockers: 3 } },
    },
  };

  expect(latestMetric(item)).toEqual(["Latest status", "pass", "fast · 1.3s"]);
  expect(riskMetric(item)).toEqual([
    "Risk profile",
    "high_assurance",
    "minimum standard",
  ]);
  expect(reviewMetric(item)).toEqual([
    "Review blockers",
    0,
    "2 human prompt(s) · 1 warning(s)",
  ]);
  expect(approvalMetric(item)).toEqual(["Approvals", "Pending", "1 required"]);
  expect(onboardingMetric(item)).toEqual([
    "Onboarding",
    "Blocked",
    "3 blocker(s)",
  ]);
  expect(riskCalloutMarkup(item.risk)).toContain("high assurance");
  expect(executionProfilesMarkup(item.risk)).toContain("&lt;release&gt;");
  expect(riskEvidenceMarkup(item)).toContain("<dd>current</dd>");
  expect(riskEvidenceMarkup(item)).toContain("<dd>missing or stale</dd>");
});
