export async function parseFile(file: File): Promise<string> {
  return new Promise(res => {
    const r = new FileReader();
    r.onload = e => res(String(e.target!.result || `[Binary:${file.name}]`).slice(0, 3000));
    r.readAsText(file);
  });
}

export const fmtDuration = (ms: number | null | undefined) =>
  !ms && ms !== 0 ? "" : ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;

export const fmtTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString() : "";
