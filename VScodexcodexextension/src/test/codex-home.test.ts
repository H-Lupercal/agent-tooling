import assert from "node:assert/strict";
import { test } from "node:test";

import { resolveCodexHome } from "../codex-home";

test("Codex home prefers an explicit configured path", () => {
  assert.equal(resolveCodexHome("/configured", {}, "/home/user"), "/configured");
});

test("Codex home falls back to CODEX_HOME", () => {
  assert.equal(
    resolveCodexHome(undefined, { CODEX_HOME: "/from-env" }, "/home/user"),
    "/from-env",
  );
});

test("Codex home defaults to the home directory dot-codex folder", () => {
  assert.equal(resolveCodexHome(undefined, {}, "/home/user"), "/home/user/.codex");
});

test("Codex home ignores blank configured and environment values", () => {
  assert.equal(
    resolveCodexHome("  ", { CODEX_HOME: "  " }, "/home/user"),
    "/home/user/.codex",
  );
});
