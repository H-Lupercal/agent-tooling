import { randomBytes } from "node:crypto";
import { watch, type FSWatcher } from "node:fs";
import { stat } from "node:fs/promises";
import os from "node:os";

import * as vscode from "vscode";

import { resolveCodexHome } from "./codex-home";
import { discoverSessionFiles } from "./discovery";
import { isSessionInWorkspace, sortSessionSummaries } from "./history";
import type { ParsedSession, SessionSummary } from "./model";
import { loadSessionSummaries, parseSessionFile } from "./parser";
import { renderTranscriptHtml } from "./render";
import { createResumePlan } from "./resume";
import { loadThreadTitles } from "./thread-index";

const openPanels = new Map<string, vscode.WebviewPanel>();

interface HistoryItem extends vscode.QuickPickItem {
  summary: SessionSummary;
}

export function activate(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("codexHistory.openConversation", async () => {
      await openConversationPicker();
    }),
  );
}

export function deactivate(): void {
  for (const panel of openPanels.values()) {
    panel.dispose();
  }
  openPanels.clear();
}

async function openConversationPicker(): Promise<void> {
  const picker = vscode.window.createQuickPick<HistoryItem>();
  picker.title = "Codex History";
  picker.placeholder = "Loading local Codex conversations…";
  picker.busy = true;
  picker.matchOnDescription = true;
  picker.matchOnDetail = true;
  picker.show();

  try {
    const configuredHome = vscode.workspace
      .getConfiguration("codexHistory")
      .get<string>("codexHome");
    const codexHome = resolveCodexHome(configuredHome, process.env, os.homedir());
    const filePaths = await discoverSessionFiles(codexHome);
    if (filePaths.length === 0) {
      picker.dispose();
      void vscode.window.showInformationMessage(
        `No Codex sessions were found under ${codexHome}.`,
      );
      return;
    }

    const threadTitles = await loadThreadTitles(codexHome);
    const summaries = sortSessionSummaries(
      await loadSessionSummaries(filePaths, 8, threadTitles),
      workspaceRoots(),
    );
    if (summaries.length === 0) {
      picker.dispose();
      void vscode.window.showWarningMessage(
        `Codex session files were found under ${codexHome}, but none could be read.`,
      );
      return;
    }

    const failedCount = filePaths.length - summaries.length;
    let currentOnly = workspaceRoots().length > 0;

    const refreshItems = (): void => {
      const roots = workspaceRoots();
      const visible = currentOnly
        ? summaries.filter((summary) => isSessionInWorkspace(summary, roots))
        : summaries;
      picker.items = visible.map(toHistoryItem);
      const omittedSuffix = failedCount > 0 ? ` • ${failedCount} unreadable omitted` : "";
      picker.title = currentOnly
        ? `Codex History — Current workspace (${visible.length})`
        : `Codex History — All repositories (${visible.length})`;
      picker.title += omittedSuffix;
      picker.placeholder =
        currentOnly && visible.length === 0
          ? "No conversations for this workspace. Select the globe button to search all repositories."
          : "Search by title, repository, date, or session ID";
      picker.buttons = [
        {
          iconPath: new vscode.ThemeIcon(currentOnly ? "globe" : "folder"),
          tooltip: currentOnly ? "Search all repositories" : "Show current workspace only",
        },
      ];
    };

    picker.busy = false;
    refreshItems();

    const buttonDisposable = picker.onDidTriggerButton(() => {
      currentOnly = !currentOnly;
      refreshItems();
    });
    const acceptDisposable = picker.onDidAccept(() => {
      const selected = picker.selectedItems[0];
      if (!selected) {
        return;
      }
      picker.hide();
      void openTranscript(selected.summary, threadTitles).catch((error: unknown) => {
        void vscode.window.showErrorMessage(errorMessage("Could not open Codex conversation", error));
      });
    });
    picker.onDidHide(() => {
      buttonDisposable.dispose();
      acceptDisposable.dispose();
      picker.dispose();
    });
  } catch (error: unknown) {
    picker.dispose();
    void vscode.window.showErrorMessage(errorMessage("Could not load Codex history", error));
  }
}

function toHistoryItem(summary: SessionSummary): HistoryItem {
  return {
    label: summary.title,
    description: summary.cwd ?? "Unknown working directory",
    detail: `Last prompted ${new Date(summary.updatedAtMs).toLocaleString()} • ${summary.sessionId}`,
    summary,
  };
}

async function openTranscript(
  summary: SessionSummary,
  threadTitles: ReadonlyMap<string, string>,
): Promise<void> {
  const existing = openPanels.get(summary.sessionId);
  if (existing) {
    existing.reveal(vscode.ViewColumn.Active);
    return;
  }

  let session = await parseSessionFile(summary.filePath, threadTitles);
  const panel = vscode.window.createWebviewPanel(
    "codexHistory.transcript",
    `Codex: ${session.title}`,
    vscode.ViewColumn.Active,
    {
      enableScripts: true,
      localResourceRoots: [],
      retainContextWhenHidden: true,
    },
  );
  openPanels.set(summary.sessionId, panel);
  renderPanel(panel, session);

  const messageDisposable = panel.webview.onDidReceiveMessage(async (message: unknown) => {
    if (isResumeMessage(message)) {
      await resumeSession(session);
    }
  });
  const watcher = createSessionWatcher(summary.filePath, async () => {
    session = await parseSessionFile(summary.filePath, threadTitles);
    panel.title = `Codex: ${session.title}`;
    renderPanel(panel, session);
  });

  panel.onDidDispose(() => {
    openPanels.delete(summary.sessionId);
    messageDisposable.dispose();
    watcher?.close();
  });
}

function renderPanel(panel: vscode.WebviewPanel, session: ParsedSession): void {
  panel.webview.html = renderTranscriptHtml(session, randomBytes(16).toString("hex"));
}

function createSessionWatcher(
  filePath: string,
  refresh: () => Promise<void>,
): FSWatcher | undefined {
  try {
    let timer: NodeJS.Timeout | undefined;
    const watcher = watch(filePath, { persistent: false }, () => {
      if (timer) {
        clearTimeout(timer);
      }
      timer = setTimeout(() => {
        void refresh().catch((error: unknown) => {
          void vscode.window.showWarningMessage(
            errorMessage("Could not refresh Codex transcript", error),
          );
        });
      }, 150);
    });
    watcher.on("close", () => {
      if (timer) {
        clearTimeout(timer);
      }
    });
    return watcher;
  } catch {
    return undefined;
  }
}

async function resumeSession(session: ParsedSession): Promise<void> {
  const cwd = await chooseResumeDirectory(session.cwd);
  if (!cwd) {
    return;
  }
  let plan;
  try {
    plan = createResumePlan(session.sessionId, cwd);
  } catch (error: unknown) {
    void vscode.window.showErrorMessage(errorMessage("Cannot resume this Codex session", error));
    return;
  }
  const terminal = vscode.window.createTerminal({
    name: `Codex: ${session.title}`,
    cwd: plan.cwd,
    location: vscode.TerminalLocation.Editor,
  });
  terminal.show();
  terminal.sendText([plan.executable, ...plan.args].join(" "), true);
}

async function chooseResumeDirectory(savedCwd: string | undefined): Promise<string | undefined> {
  if (savedCwd && (await isDirectory(savedCwd))) {
    return savedCwd;
  }
  const currentWorkspace = workspaceRoots()[0];
  if (!currentWorkspace) {
    void vscode.window.showErrorMessage(
      "The saved working directory is unavailable and no workspace is open.",
    );
    return undefined;
  }
  const choice = await vscode.window.showWarningMessage(
    "The conversation's saved working directory is unavailable. Resume in the current workspace?",
    "Use current workspace",
    "Cancel",
  );
  return choice === "Use current workspace" ? currentWorkspace : undefined;
}

async function isDirectory(filePath: string): Promise<boolean> {
  try {
    return (await stat(filePath)).isDirectory();
  } catch {
    return false;
  }
}

function workspaceRoots(): string[] {
  return vscode.workspace.workspaceFolders?.map((folder) => folder.uri.fsPath) ?? [];
}

function isResumeMessage(value: unknown): value is { type: "resume" } {
  return typeof value === "object" && value !== null && "type" in value && value.type === "resume";
}

function errorMessage(prefix: string, error: unknown): string {
  return `${prefix}: ${error instanceof Error ? error.message : String(error)}`;
}
