import path from "node:path";

export function resolveCodexHome(
  configured: string | undefined,
  env: NodeJS.ProcessEnv,
  homeDir: string,
): string {
  const selected = configured?.trim() || env.CODEX_HOME?.trim() || path.join(homeDir, ".codex");
  return path.resolve(selected);
}
