export type PageInfo = {
  index: number;
  width: number;
  height: number;
  rotation: number;
};

export type DocumentMeta = {
  id: string;
  filename: string;
  kind: "pdf" | "image";
  size: number;
  pageCount: number;
  pages: PageInfo[];
  createdAt: string;
};

const envBase = process.env.NEXT_PUBLIC_API_BASE;

function apiBase(): string {
  if (typeof envBase === "string") return envBase;
  if (typeof window !== "undefined" && window.location.port === "3000") {
    return "http://127.0.0.1:8000";
  }
  return "";
}

export function apiUrl(path: string): string {
  return `${apiBase()}${path}`;
}

export function renderUrl(docId: string, page: number, scale = 1.5): string {
  return apiUrl(
    `/api/documents/${encodeURIComponent(docId)}/pages/${page}/render?scale=${scale}`,
  );
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, index);
  return `${value >= 10 || index === 0 ? Math.round(value) : value.toFixed(1)} ${units[index]}`;
}

export function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function readError(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: string };
    if (data?.detail) return data.detail;
  } catch {
    /* ignore */
  }
  return `Request failed (${response.status})`;
}

export async function listDocuments(): Promise<DocumentMeta[]> {
  const response = await fetch(apiUrl("/api/documents?limit=12"), { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  const data = (await response.json()) as { items: DocumentMeta[] };
  return data.items;
}

export async function getDocument(id: string): Promise<DocumentMeta> {
  const response = await fetch(apiUrl(`/api/documents/${encodeURIComponent(id)}`), {
    cache: "no-store",
  });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as DocumentMeta;
}

export async function deleteDocument(id: string): Promise<void> {
  const response = await fetch(apiUrl(`/api/documents/${encodeURIComponent(id)}`), {
    method: "DELETE",
  });
  if (!response.ok && response.status !== 204) throw new Error(await readError(response));
}

export function uploadDocument(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<DocumentMeta> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", apiUrl("/api/documents"));
    request.responseType = "json";

    request.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress?.(Math.round((event.loaded / event.total) * 100));
      }
    };

    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        onProgress?.(100);
        resolve(request.response as DocumentMeta);
        return;
      }
      const detail = (request.response as { detail?: string } | null)?.detail;
      reject(new Error(detail ?? `Upload failed (${request.status})`));
    };

    request.onerror = () => {
      reject(new Error("Cannot reach the local engine. Is the server running?"));
    };

    const form = new FormData();
    form.append("file", file);
    request.send(form);
  });
}
