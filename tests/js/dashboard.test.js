import fs from "node:fs";
import path from "node:path";

const projectRoot = process.cwd();

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
