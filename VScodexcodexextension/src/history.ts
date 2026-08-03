import path from "node:path";

import type { SessionSummary } from "./model";

export function isSessionInWorkspace(
  session: SessionSummary,
  workspaceRoots: readonly string[],
): boolean {
  if (!session.cwd) {
    return false;
  }
  const sessionDirectory = path.resolve(session.cwd);
  return workspaceRoots.some((root) => {
    const relative = path.relative(path.resolve(root), sessionDirectory);
    return relative === "" || (!path.isAbsolute(relative) && relative !== ".." && !relative.startsWith(`..${path.sep}`));
  });
}

export function sortSessionSummaries(
  sessions: readonly SessionSummary[],
  workspaceRoots: readonly string[],
): SessionSummary[] {
  return [...sessions].sort((left, right) => {
    const leftIsCurrent = isSessionInWorkspace(left, workspaceRoots);
    const rightIsCurrent = isSessionInWorkspace(right, workspaceRoots);
    if (leftIsCurrent !== rightIsCurrent) {
      return leftIsCurrent ? -1 : 1;
    }
    return right.updatedAtMs - left.updatedAtMs;
  });
}
