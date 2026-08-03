import assert from "node:assert/strict";
import { test } from "node:test";

import { createResumePlan, isValidSessionId } from "../resume";

const VALID_ID = "019fc513-7044-7281-979d-6660f0ee8acd";

test("resume plan keeps executable, arguments, and cwd separate", () => {
  assert.deepEqual(createResumePlan(VALID_ID, "/work/project"), {
    executable: "codex",
    args: ["resume", VALID_ID],
    cwd: "/work/project",
  });
});

test("resume plan accepts uppercase hexadecimal session IDs", () => {
  assert.equal(isValidSessionId(VALID_ID.toUpperCase()), true);
});

test("resume plan rejects shell syntax, paths, blanks, and malformed IDs", () => {
  for (const invalid of ["", "   ", `${VALID_ID};whoami`, `../${VALID_ID}`, "not-an-id"]) {
    assert.equal(isValidSessionId(invalid), false);
    assert.throws(() => createResumePlan(invalid, "/work/project"), /Invalid Codex session ID/u);
  }
});
