# Codex History Viewer

Codex History Viewer is a local-only VS Code extension for opening saved Codex
conversations in editor tabs and resuming them in editor-area terminals.

## Features

- Search previous Codex conversations by Codex-generated title, repository, date, or session ID.
- Default to conversations from the current workspace.
- Toggle between the current workspace and all repositories.
- Open readable, read-only transcripts in editor tabs.
- Refresh an open transcript when its local session file changes.
- Resume a conversation with the official Codex CLI.

## Install from source

Requirements:

- Node.js 20 or newer.
- VS Code 1.96 or a compatible editor.
- The `codex` CLI on `PATH` for the resume action.

Build and package the extension:

```bash
npm install
npm run package
```

This creates `codex-history-viewer-0.1.0.vsix`. In VS Code, run
**Extensions: Install from VSIX...** and select that file. The extension is
installed for the current editor profile and is available from every repository.

Installing the VSIX is a separate manual step; building the project does not
modify an existing VS Code installation.

## Use

1. Open the Command Palette.
2. Run **Codex History: Open Conversation**.
3. Search or select a conversation.
4. Use the globe/folder button to switch between the current workspace and all
   repositories.
5. Select a result to open its transcript in an editor tab.
6. Select **Resume Conversation** to open `codex resume <session-id>` in an
   editor-area terminal.

When the saved working directory no longer exists, the extension asks whether
to resume in the current workspace.

## Configuration

The extension resolves Codex history in this order:

1. `codexHistory.codexHome` in VS Code settings.
2. The `CODEX_HOME` environment variable.
3. `~/.codex`.

`codexHistory.codexHome` must be an absolute path.

## Privacy and security

- There are no network requests, credentials, telemetry, or runtime npm
  dependencies.
- Session files are read only after you invoke the history command.
- Transcripts show normalized user and assistant messages only.
- System/developer instructions, reasoning, token events, approvals, tool inputs,
  and tool outputs are not rendered.
- Transcript text is HTML-escaped and displayed under a restrictive Content
  Security Policy.
- Session IDs are validated before a resume command is sent to the terminal.

## Development

```bash
npm run typecheck
npm run lint
npm test
npm run check
npm run package
```

The tests use Node's built-in test runner. Compiled extension files are written
to `out/`.

## Limitations

Codex's on-disk JSONL format can evolve. The parser handles the current event and
response message formats defensively, skips malformed or unsupported records,
and reports skipped-record counts without displaying their raw contents. When a
session has no entry in Codex's local thread index, its first user message is used
as the fallback title.
