import { readdir, stat } from "node:fs/promises";
import path from "node:path";

interface DiscoveredFile {
  filePath: string;
  updatedAtMs: number;
}

export async function discoverSessionFiles(codexHome: string): Promise<string[]> {
  const files = await walkForJsonl(path.join(codexHome, "sessions"));
  files.sort((left, right) => right.updatedAtMs - left.updatedAtMs);
  return files.map(({ filePath }) => filePath);
}

async function walkForJsonl(directory: string): Promise<DiscoveredFile[]> {
  let entries;
  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch (error: unknown) {
    if (isIgnorableFileError(error)) {
      return [];
    }
    throw error;
  }

  const discovered: DiscoveredFile[] = [];
  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      discovered.push(...(await walkForJsonl(entryPath)));
      continue;
    }
    if (!entry.isFile() || path.extname(entry.name).toLowerCase() !== ".jsonl") {
      continue;
    }
    try {
      const details = await stat(entryPath);
      discovered.push({ filePath: entryPath, updatedAtMs: details.mtimeMs });
    } catch (error: unknown) {
      if (!isIgnorableFileError(error)) {
        throw error;
      }
    }
  }
  return discovered;
}

function isIgnorableFileError(error: unknown): boolean {
  if (!(error instanceof Error) || !("code" in error)) {
    return false;
  }
  return error.code === "ENOENT" || error.code === "EACCES" || error.code === "EPERM";
}
