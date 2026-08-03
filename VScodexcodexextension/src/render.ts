import type { ParsedSession, TranscriptMessage } from "./model";

export function renderTranscriptHtml(session: ParsedSession, nonce: string): string {
  const safeNonce = escapeHtml(nonce);
  const policy = escapeHtml(
    `default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}'`,
  );
  const warning =
    session.skippedRecords > 0
      ? `<p class="warning">${session.skippedRecords} unsupported or malformed ${session.skippedRecords === 1 ? "record was" : "records were"} skipped.</p>`
      : "";
  const messages =
    session.messages.length > 0
      ? session.messages.map(renderMessage).join("\n")
      : '<p class="empty">No user or assistant messages were found in this session.</p>';

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="${policy}">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${escapeHtml(session.title)}</title>
  <style nonce="${safeNonce}">
    :root { color-scheme: light dark; }
    body { color: var(--vscode-foreground); background: var(--vscode-editor-background); font-family: var(--vscode-font-family); margin: 0 auto; max-width: 920px; padding: 24px; }
    header { border-bottom: 1px solid var(--vscode-panel-border); margin-bottom: 24px; padding-bottom: 18px; }
    h1 { font-size: 1.45rem; line-height: 1.3; margin: 0 0 10px; }
    .metadata { color: var(--vscode-descriptionForeground); font-size: 0.9rem; overflow-wrap: anywhere; }
    button { background: var(--vscode-button-background); border: 0; color: var(--vscode-button-foreground); cursor: pointer; margin-top: 16px; padding: 8px 14px; }
    button:hover { background: var(--vscode-button-hoverBackground); }
    .warning { background: var(--vscode-inputValidation-warningBackground); border: 1px solid var(--vscode-inputValidation-warningBorder); padding: 10px; }
    .message { border: 1px solid var(--vscode-panel-border); border-radius: 6px; margin: 0 0 16px; overflow: hidden; }
    .message h2 { background: var(--vscode-sideBar-background); font-size: 0.85rem; letter-spacing: 0.03em; margin: 0; padding: 8px 12px; text-transform: uppercase; }
    .message pre { font: inherit; line-height: 1.55; margin: 0; overflow-wrap: anywhere; padding: 14px; white-space: pre-wrap; }
    .empty { color: var(--vscode-descriptionForeground); }
  </style>
</head>
<body>
  <header>
    <h1>${escapeHtml(session.title)}</h1>
    <div class="metadata">${escapeHtml(session.cwd ?? "Unknown working directory")}</div>
    <button id="resume" type="button">Resume Conversation</button>
  </header>
  ${warning}
  <main>${messages}</main>
  <script nonce="${safeNonce}">
    const vscode = acquireVsCodeApi();
    document.getElementById("resume").addEventListener("click", () => vscode.postMessage({ type: "resume" }));
  </script>
</body>
</html>`;
}

function renderMessage(message: TranscriptMessage): string {
  const label = message.role === "user" ? "You" : "Codex";
  return `<section class="message ${message.role}"><h2>${label}</h2><pre>${escapeHtml(message.text)}</pre></section>`;
}

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/gu, (character) => {
    switch (character) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      case "'":
        return "&#39;";
      default:
        return character;
    }
  });
}
