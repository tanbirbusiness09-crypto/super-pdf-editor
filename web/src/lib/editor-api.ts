import { apiUrl } from "@/lib/api";

export type Span = {
  text: string;
  bbox: [number, number, number, number];
  origin: [number, number];
  font: string;
  size: number;
  flags: number;
  color: string;
  direction: [number, number];
  ocr?: boolean;
  bold?: boolean;
  confidence?: number;
  rtl?: boolean;
  edited?: boolean;
  fragments?: number;
};

export type PageImage = {
  xref: number;
  rect: [number, number, number, number];
  width: number;
  height: number;
};

export type EditOp =
  | {
      type: "add_text";
      page: number;
      origin: [number, number];
      bbox?: number[];
      text: string;
      font: string;
      size: number;
      color: string;
      bold?: boolean;
      fit?: boolean;
    }
  | {
      type: "replace_text";
      page: number;
      bbox: number[];
      origin: [number, number];
      text: string;
      font: string;
      size: number;
      color: string;
      bold?: boolean;
      fit?: boolean;
    }
  | { type: "delete_text"; page: number; bbox: number[] }
  | { type: "add_image"; page: number; rect: number[]; asset: string }
  | { type: "replace_image"; page: number; rect: number[]; asset: string }
  | {
      type: "transform_image";
      page: number;
      rect: number[];
      newRect: number[];
      asset: string;
    }
  | { type: "delete_image"; page: number; rect: number[] }
  | { type: "erase_area"; page: number; rect: number[] };

export type EditorState = {
  id: string;
  filename: string;
  version: number;
  pageCount: number;
  page: number;
  spans: Span[];
  images: PageImage[];
  ops: EditOp[];
  pages: { index: number; width: number; height: number; rotation: number }[];
  ocrAvailable?: boolean;
};

export type AssetInfo = {
  id: string;
  ext: string;
  width: number;
  height: number;
  size: number;
};

async function readError(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: string };
    if (data?.detail) return data.detail;
  } catch {
    /* ignore */
  }
  return `Request failed (${response.status})`;
}

export async function getEditorState(id: string, page: number): Promise<EditorState> {
  const response = await fetch(
    apiUrl(`/api/documents/${encodeURIComponent(id)}/editor?page=${page}`),
    { cache: "no-store" },
  );
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as EditorState;
}

export async function saveOps(id: string, ops: EditOp[]): Promise<number> {
  const response = await fetch(apiUrl(`/api/documents/${encodeURIComponent(id)}/ops`), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ops }),
  });
  if (!response.ok) throw new Error(await readError(response));
  const data = (await response.json()) as { version: number };
  return data.version;
}

export async function resetEdits(id: string): Promise<void> {
  const response = await fetch(apiUrl(`/api/documents/${encodeURIComponent(id)}/reset`), {
    method: "POST",
  });
  if (!response.ok && response.status !== 204) throw new Error(await readError(response));
}

export function uploadAsset(file: File): Promise<AssetInfo> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", apiUrl("/api/assets"));
    request.responseType = "json";
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        resolve(request.response as AssetInfo);
        return;
      }
      const detail = (request.response as { detail?: string } | null)?.detail;
      reject(new Error(detail ?? `Image upload failed (${request.status})`));
    };
    request.onerror = () => reject(new Error("Cannot reach the local engine."));
    const form = new FormData();
    form.append("file", file);
    request.send(form);
  });
}

export function exportUrl(id: string): string {
  return apiUrl(`/api/documents/${encodeURIComponent(id)}/export`);
}

export function pageRenderUrl(
  id: string,
  page: number,
  scale: number,
  version: number,
): string {
  return apiUrl(
    `/api/documents/${encodeURIComponent(id)}/pages/${page}/render?scale=${scale}&v=${version}`,
  );
}
