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
