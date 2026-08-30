export const ABC_DEFINITION = "aqg-javascript-abc-v1";

/*
 * AQG JavaScript/TypeScript ABC v1 is deliberately language-specific:
 *
 * A (assignments)
 *   - an initialized variable declarator
 *   - an assignment expression
 *   - an update expression
 *   - an assignment pattern (including default parameters)
 *
 * B (branches)
 *   - a call, constructor call, dynamic import, or yield expression
 *
 * C (conditions)
 *   - if, conditional, while, do/while, for, for/in, or for/of
 *   - each non-default switch case
 *   - each &&, ||, or ?? logical expression
 *   - each &&=, ||=, or ??= logical assignment
 *
 * Nested function bodies are excluded from their enclosing function. Counts
 * are exact non-negative integers. The magnitude is derived from the exact
 * squared magnitude and rounded to six decimal places only for presentation.
 */

const LOGICAL_ASSIGNMENTS = new Set(["&&=", "||=", "??="]);
const LOGICAL_EXPRESSIONS = new Set(["&&", "||", "??"]);
const PARENT_NAME = {
  VariableDeclarator: (parent) => printableTarget(parent.id),
  AssignmentExpression: (parent) => printableTarget(parent.left),
  Property: (parent) => printableTarget(parent.key),
  MethodDefinition: (parent) => printableTarget(parent.key),
  PropertyDefinition: (parent) => printableTarget(parent.key),
};

function printableName(node) {
  const declaredName = node.id && node.id.name;
  if (declaredName) return declaredName;

  const resolver = node.parent && PARENT_NAME[node.parent.type];
  if (resolver) return resolver(node.parent);

  const line = node.loc?.start.line ?? 0;
  const column = (node.loc?.start.column ?? -1) + 1;
  return `<anonymous@${line}:${column}>`;
}

function printableTarget(node) {
  if (!node) return "<anonymous>";
  if (node.type === "Identifier" || node.type === "PrivateIdentifier") {
    return node.name;
  }
  if (node.type === "Literal") return String(node.value);
  if (node.type === "MemberExpression") {
    const object = printableTarget(node.object);
    const property = printableTarget(node.property);
    return node.computed ? `${object}[${property}]` : `${object}.${property}`;
  }
  return "<anonymous>";
}

function locationOf(node) {
  return {
    line: node.loc?.start.line ?? 0,
    column: (node.loc?.start.column ?? -1) + 1,
    end_line: node.loc?.end.line ?? 0,
    end_column: (node.loc?.end.column ?? -1) + 1,
  };
}

function measurement(frame) {
  const { assignments, branches, conditions } = frame;
  const magnitudeSquared =
    assignments * assignments + branches * branches + conditions * conditions;
  return {
    definition: ABC_DEFINITION,
    function: printableName(frame.node),
    function_kind: frame.node.type,
    async: Boolean(frame.node.async),
    generator: Boolean(frame.node.generator),
    vector: {
      assignments,
      branches,
      conditions,
    },
    vector_text: `<${assignments},${branches},${conditions}>`,
    magnitude_squared: magnitudeSquared,
    magnitude: Number(Math.sqrt(magnitudeSquared).toFixed(6)),
    location: locationOf(frame.node),
  };
}

function assignmentListeners(increment) {
  return {
    VariableDeclarator(node) {
      if (node.init) increment("assignments");
    },
    AssignmentExpression(node) {
      increment("assignments");
      if (LOGICAL_ASSIGNMENTS.has(node.operator)) increment("conditions");
    },
    UpdateExpression() {
      increment("assignments");
    },
    AssignmentPattern() {
      increment("assignments");
    },
  };
}

function branchListeners(increment) {
  return {
    CallExpression() {
      increment("branches");
    },
    NewExpression() {
      increment("branches");
    },
    ImportExpression() {
      increment("branches");
    },
    YieldExpression() {
      increment("branches");
    },
  };
}

function conditionListeners(increment) {
  const condition = () => increment("conditions");
  return {
    IfStatement: condition,
    ConditionalExpression: condition,
    WhileStatement: condition,
    DoWhileStatement: condition,
    ForStatement: condition,
    ForInStatement: condition,
    ForOfStatement: condition,
    SwitchCase(node) {
      if (node.test) condition();
    },
    LogicalExpression(node) {
      if (LOGICAL_EXPRESSIONS.has(node.operator)) condition();
    },
  };
}

function functionListeners(enterFunction, exitFunction) {
  return {
    FunctionDeclaration: enterFunction,
    "FunctionDeclaration:exit": exitFunction,
    FunctionExpression: enterFunction,
    "FunctionExpression:exit": exitFunction,
    ArrowFunctionExpression: enterFunction,
    "ArrowFunctionExpression:exit": exitFunction,
  };
}

function createRule(context) {
  const frames = [];

  function current() {
    return frames.at(-1);
  }

  function increment(dimension) {
    const frame = current();
    if (frame) frame[dimension] += 1;
  }

  function enterFunction(node) {
    frames.push({ node, assignments: 0, branches: 0, conditions: 0 });
  }

  function exitFunction(node) {
    const frame = frames.pop();
    if (!frame || frame.node !== node) {
      throw new Error("AQG ABC function traversal stack became inconsistent");
    }
    context.report({
      node,
      messageId: "measurement",
      data: { measurement: JSON.stringify(measurement(frame)) },
    });
  }

  return {
    ...assignmentListeners(increment),
    ...branchListeners(increment),
    ...conditionListeners(increment),
    ...functionListeners(enterFunction, exitFunction),
  };
}

export const reportRule = {
  meta: {
    type: "suggestion",
    docs: {
      description: `Emit deterministic per-function ${ABC_DEFINITION} measurements`,
    },
    schema: [],
    messages: {
      measurement: "AQG_ABC {{measurement}}",
    },
  },
  create: createRule,
};

export default {
  meta: { name: "aqg-abc", version: "1.0.0" },
  rules: { report: reportRule },
};
