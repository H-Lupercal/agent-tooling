# Codex History Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and package a user-installable VS Code extension that searches local Codex sessions, opens safe transcript editor tabs, and resumes sessions in editor-area terminals.

**Architecture:** Pure TypeScript modules own Codex-home resolution, JSONL discovery/parsing, workspace filtering, safe HTML rendering, and resume planning. A thin VS Code adapter composes those modules into a Quick Pick, webview transcript, file refresh watcher, and terminal action. Local JSONL files are the only data source and no transcript data leaves the machine.

**Tech Stack:** TypeScript, Node.js filesystem/readline/test APIs, VS Code Extension API, ESLint, `@vscode/vsce`.

---

## File map

- `package.json`: extension manifest, commands, settings, and build/test/package scripts.
- `tsconfig.json`: strict CommonJS extension compilation.
- `eslint.config.mjs`: type-aware lint configuration.
- `.gitignore`, `.vscodeignore`: source-control and VSIX packaging boundaries.
- `src/model.ts`: normalized session and transcript types.
- `src/codex-home.ts`: deterministic Codex home resolution.
- `src/discovery.ts`: recursive JSONL discovery and bounded summary loading.
- `src/parser.ts`: defensive JSONL metadata/message parsing.
- `src/history.ts`: current-workspace filtering and sorting.
- `src/render.ts`: escaped transcript webview document generation.
- `src/resume.ts`: session-ID validation and resume launch planning.
- `src/extension.ts`: VS Code command, picker, panel, watcher, and terminal adapter.
- `src/test/*.test.ts`: unit coverage for all pure behavior.
- `README.md`: build, package, install, usage, privacy, and limitations.
- `LICENSE`: MIT license for local and reusable distribution.

### Task 1: Scaffold the extension and verification commands

**Files:**
- Create: `package.json`
- Create: `tsconfig.json`
- Create: `eslint.config.mjs`
- Create: `.gitignore`
- Create: `.vscodeignore`
- Create: `src/model.ts`

- [ ] **Step 1: Add the extension manifest and scripts**

Create a manifest with `main: ./out/extension.js`, VS Code engine `^1.96.0`, the
command `codexHistory.openConversation`, and setting `codexHistory.codexHome`.
Use these scripts:

```json
{
  "scripts": {
    "clean": "node -e \"require('node:fs').rmSync('out',{recursive:true,force:true})\"",
    "compile": "tsc -p tsconfig.json",
    "typecheck": "tsc -p tsconfig.json --noEmit",
    "lint": "eslint src",
    "test": "npm run clean && npm run compile && node --test out/test/*.test.js",
    "check": "npm run typecheck && npm run lint && npm test",
    "package": "npm run check && vsce package --no-dependencies"
  }
}
```

- [ ] **Step 2: Add strict compiler and lint configuration**

Compile `src/**/*.ts` to `out/` with strict mode, CommonJS modules, ES2022 target,
source maps, Node types, and VS Code types. Configure ESLint with
`typescript-eslint` recommended type-checked rules.

- [ ] **Step 3: Add shared types**

```ts
export interface SessionSummary {
  filePath: string;
  sessionId: string;
  cwd?: string;
  title: string;
  createdAt?: string;
  updatedAtMs: number;
  skippedRecords: number;
}

export interface TranscriptMessage {
  role: "user" | "assistant";
  text: string;
  timestamp?: string;
}

export interface ParsedSession extends SessionSummary {
  messages: TranscriptMessage[];
}
```

- [ ] **Step 4: Install development dependencies**

Run: `npm install`

Expected: lockfile created with zero runtime dependencies and the TypeScript,
VS Code types, ESLint, and VSIX packaging tools installed as dev dependencies.

### Task 2: Resolve Codex home and discover session files

**Files:**
- Create: `src/test/codex-home.test.ts`
- Create: `src/test/discovery.test.ts`
- Create: `src/codex-home.ts`
- Create: `src/discovery.ts`

- [ ] **Step 1: Write failing Codex-home tests**

Cover an explicit configured path, `CODEX_HOME`, and `<home>/.codex` fallback:

```ts
assert.equal(resolveCodexHome("/configured", {}, "/home/u"), "/configured");
assert.equal(resolveCodexHome(undefined, { CODEX_HOME: "/env" }, "/home/u"), "/env");
assert.equal(resolveCodexHome(undefined, {}, "/home/u"), "/home/u/.codex");
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `npm test -- --test-name-pattern="Codex home"`

Expected: FAIL because `resolveCodexHome` is not implemented.

- [ ] **Step 3: Implement minimal Codex-home resolution**

```ts
export function resolveCodexHome(
  configured: string | undefined,
  env: NodeJS.ProcessEnv,
  homeDir: string,
): string {
  return path.resolve(configured?.trim() || env.CODEX_HOME?.trim() || path.join(homeDir, ".codex"));
}
```

- [ ] **Step 4: Verify GREEN**

Run: `npm test -- --test-name-pattern="Codex home"`

Expected: all matching tests PASS.

- [ ] **Step 5: Write failing recursive-discovery tests**

Create temporary `sessions/YYYY/MM/DD` trees containing JSONL and unrelated files.
Assert `discoverSessionFiles()` returns only `.jsonl` files in newest-mtime-first
order and returns an empty array for a missing sessions directory.

- [ ] **Step 6: Run discovery tests and verify RED**

Run: `npm test -- --test-name-pattern="discovery"`

Expected: FAIL because `discoverSessionFiles` is missing.

- [ ] **Step 7: Implement recursive discovery**

Use `fs.promises.readdir(path, { withFileTypes: true })`, ignore unreadable
subdirectories, `stat` JSONL files, and sort by `mtimeMs` descending.

- [ ] **Step 8: Verify GREEN**

Run: `npm test -- --test-name-pattern="discovery"`

Expected: matching tests PASS.

### Task 3: Parse summaries and transcripts defensively

**Files:**
- Create: `src/test/parser.test.ts`
- Create: `src/parser.ts`
- Modify: `src/discovery.ts`

- [ ] **Step 1: Write failing metadata and transcript tests**

Use temporary JSONL fixtures containing `session_meta`, `event_msg.user_message`,
`event_msg.agent_message`, duplicate `response_item.message` records, a malformed
line, reasoning, and tool records. Assert:

```ts
assert.equal(parsed.sessionId, "019fc513-7044-7281-979d-6660f0ee8acd");
assert.equal(parsed.cwd, "/work/project");
assert.equal(parsed.title, "Explain this project");
assert.deepEqual(parsed.messages.map(({ role, text }) => ({ role, text })), [
  { role: "user", text: "Explain this project" },
  { role: "assistant", text: "Here is the overview." },
]);
assert.equal(parsed.skippedRecords, 1);
```

- [ ] **Step 2: Run parser tests and verify RED**

Run: `npm test -- --test-name-pattern="parser"`

Expected: FAIL because parser exports are missing.

- [ ] **Step 3: Implement record normalization**

Implement guards for unknown JSON values. Prefer `event_msg` user/agent records;
fall back to `response_item` messages only when no primary event messages exist.
Extract text content from strings or `input_text`/`output_text` content items.
Ignore all other record types. Count JSON parse failures but do not retain raw
malformed content.

- [ ] **Step 4: Implement title and summary parsing**

Derive the picker title from the first user message, collapse whitespace, and
truncate to 80 characters. Read file timestamps with `stat`. Add a bounded
`loadSessionSummaries(filePaths, concurrency = 8)` helper so scanning hundreds of
sessions does not open every file simultaneously.

- [ ] **Step 5: Verify GREEN**

Run: `npm test -- --test-name-pattern="parser"`

Expected: matching tests PASS with malformed records safely skipped.

### Task 4: Filter history by workspace

**Files:**
- Create: `src/test/history.test.ts`
- Create: `src/history.ts`

- [ ] **Step 1: Write failing workspace-filter tests**

Cover exact roots, nested session directories, sibling-prefix false positives,
multiple workspace folders, missing cwd values, and newest-first sorting.

- [ ] **Step 2: Verify RED**

Run: `npm test -- --test-name-pattern="workspace history"`

Expected: FAIL because `isSessionInWorkspace` and `sortSessionSummaries` are absent.

- [ ] **Step 3: Implement path-safe filtering and sorting**

Resolve both paths and accept a session when
`relative(root, cwd)` is empty or neither absolute nor prefixed by `..` plus a
separator. Sort current-workspace sessions before other sessions, then by
`updatedAtMs` descending.

- [ ] **Step 4: Verify GREEN**

Run: `npm test -- --test-name-pattern="workspace history"`

Expected: matching tests PASS.

### Task 5: Render a safe transcript document

**Files:**
- Create: `src/test/render.test.ts`
- Create: `src/render.ts`

- [ ] **Step 1: Write failing escaping and privacy tests**

Assert the renderer escapes `<script>`, `&`, quotes, and transcript text; includes
only normalized user/assistant messages; emits a nonce-scoped CSP; displays the
saved cwd and skipped-record warning; and includes one resume button.

- [ ] **Step 2: Verify RED**

Run: `npm test -- --test-name-pattern="transcript HTML"`

Expected: FAIL because `renderTranscriptHtml` is absent.

- [ ] **Step 3: Implement the renderer**

Generate a complete HTML document with:

```html
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src 'nonce-...'; script-src 'nonce-...'">
```

Render messages as semantic sections with `white-space: pre-wrap`; use a small
nonce-bearing script that posts `{ type: "resume" }` to VS Code. Do not render
Markdown as raw HTML and do not add external resources.

- [ ] **Step 4: Verify GREEN**

Run: `npm test -- --test-name-pattern="transcript HTML"`

Expected: matching tests PASS.

### Task 6: Plan safe resume operations

**Files:**
- Create: `src/test/resume.test.ts`
- Create: `src/resume.ts`

- [ ] **Step 1: Write failing validation tests**

Accept canonical UUID-like Codex IDs and reject spaces, shell operators, empty
strings, and path characters. Assert `createResumePlan()` returns the fixed
executable `codex`, arguments `['resume', sessionId]`, and the selected cwd as a
separate value.

- [ ] **Step 2: Verify RED**

Run: `npm test -- --test-name-pattern="resume plan"`

Expected: FAIL because resume helpers are absent.

- [ ] **Step 3: Implement validation and planning**

```ts
const SESSION_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function createResumePlan(sessionId: string, cwd: string): ResumePlan {
  if (!SESSION_ID.test(sessionId)) throw new Error("Invalid Codex session ID");
  return { executable: "codex", args: ["resume", sessionId], cwd };
}
```

- [ ] **Step 4: Verify GREEN**

Run: `npm test -- --test-name-pattern="resume plan"`

Expected: matching tests PASS.

### Task 7: Integrate the VS Code picker, editor tab, and terminal

**Files:**
- Create: `src/extension.ts`
- Modify: `package.json`

- [ ] **Step 1: Implement the history picker**

Register `codexHistory.openConversation`, resolve the configured Codex home,
discover and parse summaries, and use `createQuickPick`. Add a toggle button for
`Current workspace` versus `All repositories`; set item `label`, `description`,
and `detail` from title, date, and cwd. Show counts for unreadable session files
without displaying their contents.

- [ ] **Step 2: Implement transcript editor tabs**

Create one `WebviewPanel` per session ID and reveal an existing panel when the
same conversation is selected again. Parse the selected file, render its HTML,
and install `fs.watch` on that file. Debounce refreshes and dispose the watcher
when the panel closes.

- [ ] **Step 3: Implement resume in an editor-area terminal**

On the webview resume message, validate the session ID, choose the saved cwd when
it exists, or prompt to use the first current workspace folder when it does not.
Create the terminal with:

```ts
const terminal = vscode.window.createTerminal({
  name: `Codex: ${summary.title}`,
  cwd,
  location: vscode.TerminalLocation.Editor,
});
terminal.show();
terminal.sendText([plan.executable, ...plan.args].join(" "), true);
```

The only interpolated value is the previously validated session ID.

- [ ] **Step 4: Compile and inspect diagnostics**

Run: `npm run typecheck && npm run lint`

Expected: both commands exit 0 with no diagnostics.

### Task 8: Document, package, and verify the extension

**Files:**
- Create: `README.md`
- Create: `LICENSE`
- Modify: `.vscodeignore`
- Modify: `package.json`

- [ ] **Step 1: Write installation and usage documentation**

Document `npm install`, `npm test`, `npm run package`, installation via
`Extensions: Install from VSIX...`, the `Codex History: Open Conversation`
command, workspace/all-repositories toggle, transcript privacy exclusions,
`codexHistory.codexHome`, and the fact that resume requires the Codex CLI on PATH.

- [ ] **Step 2: Run the full verification gate**

Run: `npm run check`

Expected: typecheck, lint, and all Node tests exit 0 with zero failures.

- [ ] **Step 3: Package the VSIX**

Run: `npm run package`

Expected: `codex-history-command-0.1.0.vsix` is created and `vsce` exits 0.

- [ ] **Step 4: Inspect packaged contents**

Run: `npx vsce ls --tree`

Expected: the package contains `package.json`, `README.md`, `LICENSE`, and compiled
`out/` files; it excludes TypeScript sources, tests, local session data,
`node_modules`, design documents, and unrelated repository files.

- [ ] **Step 5: Run repository-level contract test if root metadata changed**

No root metadata is planned. If any root file changes, run:

```bash
codex-conductor/.venv/bin/python -m pytest tests/test_release_contract.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit only the extension directory**

```bash
git add codex-history-command
git commit -m "feat: add local Codex history viewer extension"
```

Do not stage or modify unrelated monorepo files.
