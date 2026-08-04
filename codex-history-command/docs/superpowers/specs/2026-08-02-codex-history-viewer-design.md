# Codex History Viewer Design

## Purpose

Build a local-only VS Code-compatible extension that lets a user find previous
Codex conversations, read them in editor tabs, and resume a selected conversation
through the supported Codex CLI. The extension is installed once at the user
level and works from any repository or an empty editor window.

## User experience

The extension contributes a `Codex History: Open Conversation` command. Running
the command opens a searchable picker of locally saved Codex sessions. When a
workspace is open, sessions whose saved working directory belongs to that
workspace appear first and the initial filter is `Current workspace`. The user
can switch to `All repositories` without leaving the picker.

Each result shows the conversation title, saved repository or working directory,
and last-updated date. Selecting a result opens a rendered, read-only transcript
in an editor tab. The transcript header includes a `Resume Conversation` button.
Activating it creates a terminal in the editor area and runs
`codex resume <session-id>` from the session's saved working directory. If that
directory no longer exists, the extension offers to use the current workspace.

## Architecture

The extension consists of four independently testable components:

1. **Session discovery** recursively finds JSONL files under the configured Codex
   home directory, defaulting to `$CODEX_HOME` when set and `~/.codex` otherwise.
2. **Session parser** reads records defensively, extracts stable metadata, and
   produces a normalized transcript containing user and assistant messages.
3. **History picker** filters and sorts sessions, prioritizing the current
   workspace while retaining an all-repositories mode.
4. **Transcript panel** renders escaped local content in a VS Code webview and
   sends the selected session identifier to the extension host for resumption.

The extension uses no network access and no OpenAI credentials. It reads local
session files only after the user invokes its command.

## Session parsing

Codex sessions are stored as JSONL under `<codex-home>/sessions/YYYY/MM/DD/`.
The parser uses `session_meta` for the session ID, timestamps, and working
directory. It accepts user and assistant text from the currently observed event
and response record shapes, deduplicating equivalent messages when both shapes
are present.

The default transcript excludes system and developer instructions, encrypted or
plain reasoning, token accounting, approval events, tool inputs, and tool
outputs. Unknown or malformed records are skipped and counted. A non-blocking
warning in the transcript reports skipped records without exposing their raw
contents.

The display title is derived from the first meaningful user message and truncated
for picker display. Sessions without a user message use `Untitled conversation`.

## Security and privacy

- All processing remains on the user's machine.
- Webview content is HTML-escaped and protected by a restrictive content security
  policy.
- Resume commands use VS Code terminal APIs rather than shell interpolation.
- Session identifiers are validated before use.
- The extension never renders hidden instructions, reasoning, or tool payloads.
- No telemetry, remote requests, or transcript indexing outside memory is added.

## Error handling

- Missing session directory: show a clear message with the resolved path.
- Unreadable file: exclude it from the picker and report the number skipped.
- Partially corrupt JSONL: render valid messages and show a skipped-record count.
- Missing Codex executable: the editor terminal displays the shell's normal
  command-not-found error without the extension masking it.
- Deleted saved working directory: offer the current workspace or cancel.
- File changes while a transcript is open: refresh the panel from disk.

## Packaging and compatibility

The project produces a `.vsix` installed through `Extensions: Install from
VSIX...`. The extension is installed globally for the current editor profile, so
it is available in every repository. It targets current VS Code and compatible
editors that support the required extension, webview, Quick Pick, and terminal
APIs.

The repository includes build, test, package, and install instructions. The
extension has no runtime npm dependencies and uses a small internal transcript
renderer to minimize supply-chain exposure.

## Testing and acceptance criteria

Automated tests cover:

- Codex home resolution.
- Recursive session discovery and ordering.
- Metadata and title extraction.
- User/assistant message extraction and deduplication.
- Malformed and unknown record handling.
- Workspace filtering.
- HTML escaping and content security policy generation.
- Session ID validation and resume launch configuration.

The extension is accepted when:

1. One user-level installation exposes the command in multiple repositories.
2. The picker defaults to the current workspace and can search all repositories.
3. Selecting a conversation opens its readable transcript in an editor tab.
4. Hidden instructions, reasoning, and tool payloads are absent from the view.
5. Resume opens an editor-area terminal for the correct session and directory.
6. Tests, type checking, linting, extension build, and VSIX packaging pass.
