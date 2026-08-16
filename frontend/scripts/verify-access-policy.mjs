import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

import ts from "typescript";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(scriptDirectory, "..");
const appRoot = path.join(frontendRoot, "app");
const policyPath = path.join(frontendRoot, "lib", "access-policy.ts");

function collectPageRoutes(directory) {
  const routes = [];

  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      routes.push(...collectPageRoutes(entryPath));
      continue;
    }
    if (entry.name !== "page.tsx") continue;

    const relativeDirectory = path.relative(appRoot, path.dirname(entryPath));
    const segments = relativeDirectory
      .split(path.sep)
      .filter(Boolean)
      .filter((segment) => !segment.startsWith("(") && !segment.startsWith("@"));

    assert.equal(
      segments.some((segment) => segment.startsWith("[")),
      false,
      `Dynamic page ${entryPath} needs an explicit representative-path rule in this gate.`,
    );
    routes.push(segments.length === 0 ? "/" : `/${segments.join("/")}`);
  }

  return routes;
}

function loadPolicyModule() {
  const source = fs.readFileSync(policyPath, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: policyPath,
    reportDiagnostics: true,
  });

  const errors = (compiled.diagnostics || []).filter(
    (diagnostic) => diagnostic.category === ts.DiagnosticCategory.Error,
  );
  assert.deepEqual(errors, [], "access-policy.ts must transpile without errors");

  const policyModule = { exports: {} };
  vm.runInNewContext(compiled.outputText, {
    exports: policyModule.exports,
    module: policyModule,
  }, { filename: policyPath });
  return policyModule.exports;
}

const pageRoutes = [...new Set(collectPageRoutes(appRoot))].sort();
const accessPolicy = loadPolicyModule();
const policies = Array.from(accessPolicy.routeAccessPolicies);
const policyHrefs = policies.map((policy) => policy.href);
const publicRoutes = pageRoutes.filter((route) => accessPolicy.isPublicPath(route));
const protectedRoutes = pageRoutes.filter((route) => !accessPolicy.isPublicPath(route));

assert.equal(pageRoutes.length, 46, "Route inventory changed; review and update the access contract.");
assert.deepEqual(
  publicRoutes,
  ["/accept-invitation", "/forgot-password", "/login", "/reset-password"],
  "The public-page allowlist changed; perform an explicit authentication-boundary review.",
);
assert.equal(new Set(policyHrefs).size, policyHrefs.length, "Policy hrefs must be unique.");
assert.equal(
  new Set([...policyHrefs, ...publicRoutes]).size,
  policyHrefs.length + publicRoutes.length,
  "A route cannot be both public and protected.",
);

for (const route of protectedRoutes) {
  const matched = accessPolicy.routePolicyForPath(route);
  assert.ok(matched, `Protected page ${route} is missing from the route access policy.`);
  assert.equal(matched.href, route, `Protected page ${route} must have an explicit policy entry.`);
}

for (const href of policyHrefs) {
  assert.ok(pageRoutes.includes(href), `Policy ${href} does not correspond to an application page.`);
}

for (const route of publicRoutes) {
  assert.equal(
    accessPolicy.routePolicyForPath(route),
    null,
    `Public page ${route} must not also resolve to a protected policy.`,
  );
}

for (const policy of policies) {
  assert.ok(policy.label.trim(), `Policy ${policy.href} must have a navigation/audit label.`);
  assert.ok(policy.roles.length > 0, `Policy ${policy.href} must have at least one default role.`);
  assert.equal(
    new Set(policy.roles).size,
    policy.roles.length,
    `Policy ${policy.href} contains duplicate roles.`,
  );
  if (policy.platformOnly) {
    assert.deepEqual(
      Array.from(policy.roles),
      ["admin"],
      `Platform-only policy ${policy.href} must remain admin-role scoped.`,
    );
  }
}

const context = (role, permissions = null, isPlatformAdmin = false) => ({
  role,
  permissions,
  isPlatformAdmin,
});

const criticalAccessCases = [
  ["engineer team work-order visibility", "/work-orders", context("engineer"), true],
  ["engineer inventory-ledger denial", "/inventory-ledger", context("engineer"), false],
  ["warehouse inventory access", "/inventory", context("warehouse"), true],
  ["warehouse work-order denial", "/work-orders", context("warehouse"), false],
  ["assistant profile access", "/profile", context("assistant"), true],
  ["assistant dashboard denial", "/", context("assistant"), false],
  ["manager employee default", "/employees", context("manager"), true],
  ["manager explicit employee denial", "/employees", context("manager", []), false],
  ["delegated employee permission", "/employees", context("engineer", ["users.read"]), true],
  ["manager backup denial", "/backups", context("manager"), false],
  ["organization-admin backup access", "/backups", context("admin"), true],
  ["tenant-admin platform denial", "/platform", context("admin"), false],
  ["platform-admin customer access", "/platform", context("admin", null, true), true],
];

for (const [name, route, access, expected] of criticalAccessCases) {
  assert.equal(accessPolicy.canAccessPath(route, access), expected, name);
}

for (const role of ["engineer", "warehouse", "manager", "admin", "assistant"]) {
  assert.equal(
    accessPolicy.canAccessPath("/definitely-not-a-real-page", context(role)),
    false,
    `Unknown pages must fail closed for ${role}.`,
  );
}

assert.equal(accessPolicy.routePolicyForPath("/work-orders/123").href, "/work-orders");
assert.equal(accessPolicy.routePolicyForPath("/platform/operations/history").href, "/platform/operations");
assert.equal(accessPolicy.routePolicyForPath("/platform/unknown"), null);
assert.equal(accessPolicy.isPublicPath("/login/"), true);
assert.equal(accessPolicy.isPublicPath("/login/extra"), false);

assert.equal(accessPolicy.homeRouteForRole("engineer"), "/today");
assert.equal(accessPolicy.homeRouteForRole("warehouse"), "/inventory");
assert.equal(accessPolicy.homeRouteForRole("assistant"), "/profile");
assert.equal(accessPolicy.homeRouteForRole("manager"), "/");
assert.equal(accessPolicy.homeRouteForRole("admin"), "/");

process.stdout.write(
  `Access policy contract passed: ${pageRoutes.length} pages, ${protectedRoutes.length} protected, ${publicRoutes.length} public.\n`,
);
