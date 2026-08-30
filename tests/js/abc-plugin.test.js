import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "vitest";

import plugin, {
  ABC_DEFINITION,
} from "../../quality/tools/js/config/aqg-abc-plugin.mjs";
import abcConfig from "../../quality/tools/js/config/aqg-abc.config.mjs";

const require = createRequire(
  new URL("../../quality/tools/js/package.json", import.meta.url),
);
const { Linter } = require("eslint");
const tseslint = require("typescript-eslint");

function measurements(
  source,
  { filename = "sample.js", typescript = false } = {},
) {
  const linter = new Linter({ configType: "flat" });
  const languageOptions = {
    ecmaVersion: "latest",
    sourceType: "module",
    parserOptions: { ecmaFeatures: { jsx: true } },
  };
  if (typescript) languageOptions.parser = tseslint.parser;

  const messages = linter.verify(
    source,
    [
      {
        files: ["**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}"],
        plugins: { "aqg-abc": plugin },
        languageOptions,
        rules: { "aqg-abc/report": "warn" },
      },
    ],
    { filename },
  );

  const unexpected = messages.filter(
    (message) => message.ruleId !== "aqg-abc/report",
  );
  assert.deepEqual(unexpected, []);
  return messages.map((message) => {
    assert.equal(message.severity, 1);
    assert.match(message.message, /^AQG_ABC /);
    return JSON.parse(message.message.slice("AQG_ABC ".length));
  });
}

function byName(results, name) {
  const result = results.find((entry) => entry.function === name);
  assert.ok(result, `missing measurement for ${name}`);
  return result;
}

test("reports the versioned exact vector, magnitude, and location", () => {
  const [result] = measurements(`
function decide(input = 1) {
  let value = input;
  value += 1;
  if (value > 2 && input) value++;
  return helper(value) ? new Result(value) : null;
}
`);

  assert.equal(result.definition, ABC_DEFINITION);
  assert.equal(result.function, "decide");
  assert.equal(result.function_kind, "FunctionDeclaration");
  assert.deepEqual(result.vector, {
    assignments: 4,
    branches: 2,
    conditions: 3,
  });
  assert.equal(result.vector_text, "<4,2,3>");
  assert.equal(result.magnitude_squared, 29);
  assert.equal(result.magnitude, 5.385165);
  assert.deepEqual(result.location, {
    line: 2,
    column: 1,
    end_line: 7,
    end_column: 2,
  });
});

test("excludes nested function bodies from the outer function", () => {
  const results = measurements(`
function outer(source) {
  const inner = async (flag) => {
    let answer = await load(source);
    if (flag) answer++;
    return answer;
  };
  return inner(source);
}
`);

  assert.equal(results.length, 2);
  assert.deepEqual(byName(results, "outer").vector, {
    assignments: 1,
    branches: 1,
    conditions: 0,
  });
  const inner = byName(results, "inner");
  assert.equal(inner.async, true);
  assert.deepEqual(inner.vector, {
    assignments: 2,
    branches: 1,
    conditions: 1,
  });
});

test("counts arrow, async, generator, loop, switch, and logical-assignment semantics", () => {
  const results = measurements(`
const transform = async (items = []) => {
  for (const item of items) {
    item.ready &&= await prepare(item);
  }
};
function* choose(value) {
  while (value) {
    switch (value) {
      case 1: yield use(value); break;
      default: value--;
    }
  }
}
`);

  const transform = byName(results, "transform");
  assert.equal(transform.async, true);
  assert.deepEqual(transform.vector, {
    assignments: 2,
    branches: 1,
    conditions: 2,
  });

  const choose = byName(results, "choose");
  assert.equal(choose.generator, true);
  assert.deepEqual(choose.vector, {
    assignments: 1,
    branches: 2,
    conditions: 2,
  });
});

test("supports TypeScript and TSX syntax through typescript-eslint", () => {
  const results = measurements(
    `
type Props = { active?: boolean };
const View = ({ active = false }: Props): JSX.Element => {
  const label: string = active ? "on" : "off";
  return <span>{format(label)}</span>;
};
`,
    { filename: "view.tsx", typescript: true },
  );

  assert.deepEqual(byName(results, "View").vector, {
    assignments: 2,
    branches: 1,
    conditions: 1,
  });
});

test("emits zero vectors and exact integer magnitude boundaries", () => {
  const results = measurements(`
const empty = () => 1;
const boundary = () => {
  let value = 0;
  value++;
  value = 2;
  a(); b(); c(); d();
};
`);

  assert.deepEqual(byName(results, "empty").vector, {
    assignments: 0,
    branches: 0,
    conditions: 0,
  });
  const boundary = byName(results, "boundary");
  assert.deepEqual(boundary.vector, {
    assignments: 3,
    branches: 4,
    conditions: 0,
  });
  assert.equal(boundary.magnitude_squared, 25);
  assert.equal(boundary.magnitude, 5);
});

test("the shipped flat config parses JS, JSX, TS, and TSX", () => {
  const samples = [
    ["sample.js", "export function js(value) { return use(value); }"],
    ["sample.jsx", "export const Jsx = () => <div>{render()}</div>;"],
    [
      "sample.ts",
      "export function ts(value: number): number { return use(value); }",
    ],
    [
      "sample.tsx",
      "export const Tsx = (value: number): JSX.Element => <div>{use(value)}</div>;",
    ],
  ];

  for (const [filename, source] of samples) {
    const messages = new Linter({ configType: "flat" }).verify(
      source,
      abcConfig,
      {
        filename,
      },
    );
    assert.equal(messages.length, 1, filename);
    assert.equal(messages[0].ruleId, "aqg-abc/report", filename);
    assert.equal(messages[0].severity, 1, filename);
  }
});

test("is deterministic for repeated analysis", () => {
  const source = `const stable = (value) => value && execute(value);`;
  const first = measurements(source);
  const second = measurements(source);
  assert.deepEqual(second, first);
});
