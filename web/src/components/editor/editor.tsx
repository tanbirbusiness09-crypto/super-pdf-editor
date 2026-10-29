"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  Bold,
  ChevronLeft,
  ChevronRight,
  Download,
  Eraser,
  FilePenLine,
  ImagePlus,
  Info,
  Layers,
  Loader2,
  Maximize2,
  MousePointer2,
  Pencil,
  Redo2,
  RotateCcw,
  Trash2,
  Type,
  Undo2,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import PageCanvas, { Tool, imageKey, spanKey } from "@/components/editor/page-canvas";
import {
  EditOp,
  EditorState,
  PageImage,
  Span,
  exportUrl,
  getEditorState,
  pageRenderUrl,
  resetEdits,
  saveOps,
  uploadAsset,
} from "@/lib/editor-api";

type Selection =
  | { kind: "text"; key: string; span: Span }
  | { kind: "image"; key: string; image: PageImage };

const normalize = (text: string) =>
  text.replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim();

function clampRect(rect: number[], width: number, height: number): number[] {
  const w = Math.min(rect[2] - rect[0], width);
  const h = Math.min(rect[3] - rect[1], height);
  const x0 = Math.max(0, Math.min(rect[0], width - w));
  const y0 = Math.max(0, Math.min(rect[1], height - h));
  return [x0, y0, x0 + w, y0 + h];
}

function rectsClose(left: number[], right: number[], tolerance = 0.75): boolean {
  return (
    left.length === 4 &&
    right.length === 4 &&
    left.every((value, index) => Math.abs(value - right[index]) <= tolerance)
  );
}

function spanBold(span: Span): boolean {
  return (
    Boolean(span.bold) ||
    (span.flags & 16) !== 0 ||
    /bold|black|heavy|semibold|demi/i.test(span.font)
  );
}

function spanIsBold(span: Span, ops: EditOp[], page: number): boolean {
  if (spanBold(span)) return true;
  for (let index = ops.length - 1; index >= 0; index -= 1) {
    const op = ops[index];
    if (
      (op.type === "replace_text" || op.type === "add_text") &&
      op.page === page &&
      (rectsClose(op.bbox ?? [], span.bbox, 1.0) ||
        (Math.abs(op.origin[0] - span.origin[0]) <= 0.75 &&
          Math.abs(op.origin[1] - span.origin[1]) <= 0.75))
    ) {
      return Boolean(op.bold);
    }
  }
  return false;
}

export default function Editor() {
  const [docId, setDocId] = useState<string | null>(null);
  const [state, setState] = useState<EditorState | null>(null);
  const [page, setPage] = useState(0);
  const [ops, setOps] = useState<EditOp[]>([]);
  const [redoStack, setRedoStack] = useState<EditOp[]>([]);
  const [zoom, setZoom] = useState(1);
  const [tool, setTool] = useState<Tool>("select");
  const toolRef = useRef<Tool>("select");

  const chooseTool = useCallback((next: Tool) => {
    toolRef.current = next;
    setTool(next);
  }, []);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [draft, setDraft] = useState<{
    text: string;
    size: number;
    color: string;
    bold: boolean;
  } | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const focusedSelectionRef = useRef<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingPoint, setPendingPoint] = useState<[number, number] | null>(null);

  useEffect(() => {
    if (selection?.kind !== "text") {
      focusedSelectionRef.current = null;
      return;
    }
    if (focusedSelectionRef.current === selection.key) return;
    focusedSelectionRef.current = selection.key;
    const node = textareaRef.current;
    if (!node) return;
    node.focus();
    node.select();
  }, [selection]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const addImageInput = useRef<HTMLInputElement>(null);
  const replaceImageInput = useRef<HTMLInputElement>(null);
  const replaceTextImageInput = useRef<HTMLInputElement>(null);
  const replaceTargetRef = useRef<PageImage | null>(null);
  const replaceTextTargetRef = useRef<Span | null>(null);
  const fittedRef = useRef("");

  const load = useCallback(async (id: string, pageIndex: number) => {
    setLoading(true);
    setError(null);
    try {
      const fresh = await getEditorState(id, pageIndex);
      setState(fresh);
      setOps(fresh.ops);
      setSelection(null);
      setDraft(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load the document.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("doc");
    const timer = window.setTimeout(() => {
      if (!id) {
        setError("No document selected. Go back and upload a file.");
        setLoading(false);
        return;
      }
      setDocId(id);
      void load(id, 0);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    const element = scrollRef.current;
    if (!element || !state) return;
    const key = `${state.id}:${page}`;
    const pageInfo = state.pages[page];
    if (!pageInfo) return;

    const observer = new ResizeObserver(() => {
      if (fittedRef.current === key) return;
      const available = element.clientWidth - 96;
      if (available <= 0) return;
      fittedRef.current = key;
      setZoom(Math.max(0.45, Math.min(2.4, available / pageInfo.width)));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [state, page]);

  const fitWidth = useCallback(() => {
    const element = scrollRef.current;
    const info = state?.pages[page];
    if (!element || !info) return;
    const available = element.clientWidth - 96;
    if (available <= 0) return;
    fittedRef.current = `${state?.id}:${page}`;
    setZoom(Math.max(0.45, Math.min(2.4, available / info.width)));
  }, [state, page]);

  const commit = useCallback(
    async (nextOps: EditOp[], selectText?: string): Promise<EditorState | null> => {
      if (!docId) return null;
      setBusy(true);
      setError(null);
      try {
        await saveOps(docId, nextOps);
        const fresh = await getEditorState(docId, page);
        setState(fresh);
        setOps(nextOps);
        setRedoStack([]);
        if (selectText) {
          const target = fresh.spans.find(
            (span) => normalize(span.text) === normalize(selectText),
          );
          if (target) {
            setSelection({ kind: "text", key: spanKey(page, target), span: target });
            setDraft({
              text: normalize(target.text),
              size: target.size,
              color: target.color,
              bold: spanIsBold(target, nextOps, page),
            });
            return fresh;
          }
        }
        setSelection(null);
        setDraft(null);
        return fresh;
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Could not apply the edit.");
        return null;
      } finally {
        setBusy(false);
      }
    },
    [docId, page],
  );

  const imageAsset = useCallback(
    (image: PageImage): string | null => {
      for (let index = ops.length - 1; index >= 0; index -= 1) {
        const item = ops[index];
        if (item.page !== page) continue;
        if (item.type === "add_image" && rectsClose(item.rect, image.rect)) {
          return item.asset;
        }
        if (item.type === "transform_image" && rectsClose(item.newRect, image.rect)) {
          return item.asset;
        }
      }
      return null;
    },
    [ops, page],
  );

  const goToPage = useCallback(
    async (next: number) => {
      if (!docId || !state) return;
      if (next < 0 || next >= state.pageCount) return;
      setPage(next);
      await load(docId, next);
    },
    [docId, state, load],
  );

  const undo = useCallback(async () => {
    if (!ops.length) return;
    const last = ops[ops.length - 1];
    await commit(ops.slice(0, -1));
    setRedoStack((current) => [last, ...current]);
  }, [ops, commit]);

  const redo = useCallback(async () => {
    if (!redoStack.length) return;
    const next = redoStack[0];
    await commit([...ops, next]);
    setRedoStack((current) => current.slice(1));
  }, [redoStack, ops, commit]);

  const deleteSelection = useCallback(() => {
    if (!selection) return;
    if (selection.kind === "text") {
      const span = selection.span;
      const pad = 1.5;
      const op: EditOp = span.ocr
        ? {
            type: "erase_area",
            page,
            rect: [
              span.bbox[0] - pad,
              span.bbox[1] - pad,
              span.bbox[2] + pad,
              span.bbox[3] + pad,
            ],
          }
        : { type: "delete_text", page, bbox: span.bbox };
      void commit([...ops, op]);
      return;
    }
    const op: EditOp = { type: "delete_image", page, rect: selection.image.rect };
    void commit([...ops, op]);
  }, [selection, page, ops, commit]);

  const deleteSpanAt = useCallback(
    (span: Span) => {
      const pad = 1.5;
      const op: EditOp = span.ocr
        ? {
            type: "erase_area",
            page,
            rect: [
              span.bbox[0] - pad,
              span.bbox[1] - pad,
              span.bbox[2] + pad,
              span.bbox[3] + pad,
            ],
          }
        : { type: "delete_text", page, bbox: span.bbox };
      void commit([...ops, op]);
    },
    [page, ops, commit],
  );

  const deleteImageAt = useCallback(
    (image: PageImage) => {
      const op: EditOp = { type: "delete_image", page, rect: image.rect };
      void commit([...ops, op]);
    },
    [page, ops, commit],
  );

  const selectSpan = useCallback(
    (span: Span) => {
      setSelection({ kind: "text", key: spanKey(page, span), span });
      setDraft({
        text: normalize(span.text),
        size: span.size,
        color: span.color,
        bold: spanIsBold(span, ops, page),
      });
      chooseTool("select");
    },
    [page, ops, chooseTool],
  );

  const selectImage = useCallback(
    (image: PageImage) => {
      setSelection({ kind: "image", key: imageKey(page, image), image });
      setDraft(null);
      chooseTool("select");
    },
    [page, chooseTool],
  );

  const transformImage = useCallback(
    (image: PageImage, rect: number[]) => {
      const asset = imageAsset(image);
      const pageInfo = state?.pages[page];
      if (!asset || !pageInfo) return;
      const next = clampRect(rect, pageInfo.width, pageInfo.height);
      if (rectsClose(next, image.rect)) return;
      const op: EditOp = {
        type: "transform_image",
        page,
        rect: image.rect,
        newRect: next,
        asset,
      };
      void (async () => {
        const fresh = await commit([...ops, op]);
        if (!fresh) return;
        const target = fresh.images.find((item) => rectsClose(item.rect, next, 1.5));
        if (target) {
          setSelection({ kind: "image", key: imageKey(page, target), image: target });
        }
      })();
    },
    [imageAsset, state, page, ops, commit],
  );

  const changeImage = useCallback(
    (image: PageImage) => {
      replaceTargetRef.current = image;
      selectImage(image);
      replaceImageInput.current?.click();
    },
    [selectImage],
  );

  const moveSpan = useCallback(
    (span: Span, dx: number, dy: number) => {
      if (span.ocr) {
        const pad = 1.5;
        const moved: [number, number, number, number] = [
          span.bbox[0] + dx,
          span.bbox[1] + dy,
          span.bbox[2] + dx,
          span.bbox[3] + dy,
        ];
        const erase: EditOp = {
          type: "erase_area",
          page,
          rect: [
            span.bbox[0] - pad,
            span.bbox[1] - pad,
            span.bbox[2] + pad,
            span.bbox[3] + pad,
          ],
        };
        const add: EditOp = {
          type: "add_text",
          page,
          origin: [moved[0], moved[3] - span.size * 0.18],
          bbox: moved,
          text: span.text,
          font: "Helvetica",
          size: span.size,
          color: span.color,
          bold: spanIsBold(span, ops, page),
          fit: false,
        };
        void commit([...ops, erase, add], span.text);
        return;
      }
      const op: EditOp = {
        type: "replace_text",
        page,
        bbox: span.bbox,
        origin: [span.origin[0] + dx, span.origin[1] + dy],
        text: span.text,
        font: span.font,
        size: span.size,
        color: span.color,
        bold: spanIsBold(span, ops, page),
      };
      void commit([...ops, op], span.text);
    },
    [page, ops, commit],
  );

  const applyText = useCallback(() => {
    if (selection?.kind !== "text" || !draft) return;
    const span = selection.span;
    const wantedBold = draft.bold;
    if (span.ocr) {
      const pad = 1.5;
      const erase: EditOp = {
        type: "erase_area",
        page,
        rect: [
          span.bbox[0] - pad,
          span.bbox[1] - pad,
          span.bbox[2] + pad,
          span.bbox[3] + pad,
        ],
      };
      const add: EditOp = {
        type: "add_text",
        page,
        origin: [span.bbox[0], span.bbox[3] - draft.size * 0.18],
        bbox: span.bbox,
        text: draft.text,
        font: "Helvetica",
        size: draft.size,
        color: draft.color,
        bold: draft.bold,
        fit: false,
      };
      void (async () => {
        const fresh = await commit([...ops, erase, add], draft.text);
        if (fresh) {
          setDraft((current) => (current ? { ...current, bold: wantedBold } : current));
        }
      })();
      return;
    }
    const isNewText = ops.some(
      (item) =>
        item.type === "add_text" &&
        item.page === page &&
        Math.abs(item.origin[0] - span.origin[0]) < 0.75 &&
        Math.abs(item.origin[1] - span.origin[1]) < 0.75,
    );
    const sizeChanged = Math.abs(draft.size - span.size) > 0.01;
    const boldChanged = draft.bold !== spanIsBold(span, ops, page);
    const op: EditOp = {
      type: "replace_text",
      page,
      bbox: span.bbox,
      origin: span.origin,
      text: draft.text,
      font: span.font,
      size: draft.size,
      color: draft.color,
      bold: draft.bold,
      fit: !isNewText && !sizeChanged && !boldChanged,
    };
    void (async () => {
      const fresh = await commit([...ops, op], draft.text);
      if (fresh) {
        setDraft((current) => (current ? { ...current, bold: wantedBold } : current));
      }
    })();
  }, [selection, draft, page, ops, commit]);

  const addTextAt = useCallback(
    (x: number, y: number) => {
      const size = 14;
      const op: EditOp = {
        type: "add_text",
        page,
        origin: [x, y],
        bbox: [x, y - size * 1.1, x + 180, y + size * 0.35],
        text: "New text",
        font: "Helvetica",
        size,
        color: "#111111",
        bold: false,
      };
      void commit([...ops, op], "New text");
    },
    [page, ops, commit],
  );

  const handleCanvasClick = useCallback(
    (x: number, y: number) => {
      const currentTool = toolRef.current;
      if (currentTool === "erase") return;
      if (currentTool === "text") {
        addTextAt(x, y);
        chooseTool("select");
        return;
      }
      if (currentTool === "image") {
        setPendingPoint([x, y]);
        addImageInput.current?.click();
        return;
      }
      setSelection(null);
      setDraft(null);
    },
    [addTextAt, chooseTool],
  );

  const handleErase = useCallback(
    (rect: number[]) => {
      const op: EditOp = { type: "erase_area", page, rect };
      void commit([...ops, op]);
      chooseTool("select");
    },
    [page, ops, commit, chooseTool],
  );

  const handleAddImageFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !state) return;
    setBusy(true);
    setError(null);
    try {
      const asset = await uploadAsset(file);
      const pageInfo = state.pages[page];
      const [cx, cy] = pendingPoint ?? [pageInfo.width / 2, pageInfo.height / 2];
      const boxWidth = Math.min(220, pageInfo.width * 0.4);
      const ratio = asset.width > 0 ? asset.height / asset.width : 1;
      const boxHeight = boxWidth * ratio;
      const rect = clampRect(
        [cx - boxWidth / 2, cy - boxHeight / 2, cx + boxWidth / 2, cy + boxHeight / 2],
        pageInfo.width,
        pageInfo.height,
      );
      const fresh = await commit([...ops, { type: "add_image", page, rect, asset: asset.id }]);
      chooseTool("select");
      if (fresh) {
        const target = fresh.images.find((item) => rectsClose(item.rect, rect, 1.5));
        if (target) selectImage(target);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not place the image.");
    } finally {
      setBusy(false);
      setPendingPoint(null);
    }
  };

  const handleReplaceImageFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    const target = replaceTargetRef.current ?? (selection?.kind === "image" ? selection.image : null);
    if (!file || !target) return;
    setBusy(true);
    setError(null);
    try {
      const asset = await uploadAsset(file);
      await commit([
        ...ops,
        { type: "replace_image", page, rect: target.rect, asset: asset.id },
      ]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not replace the image.");
    } finally {
      setBusy(false);
      replaceTargetRef.current = null;
    }
  };

  const handleReplaceTextWithImageFile = async (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    const target = replaceTextTargetRef.current;
    if (!file || !target) return;
    setBusy(true);
    setError(null);
    try {
      const asset = await uploadAsset(file);
      await commit([
        ...ops,
        { type: "delete_text", page, bbox: target.bbox },
        { type: "add_image", page, rect: target.bbox, asset: asset.id },
      ]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not place the image.");
    } finally {
      setBusy(false);
      replaceTextTargetRef.current = null;
    }
  };

  const handleReset = async () => {
    if (!docId) return;
    if (!window.confirm("Discard every edit and restore the original file?")) return;
    setBusy(true);
    setError(null);
    try {
      await resetEdits(docId);
      setRedoStack([]);
      await load(docId, page);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not reset the document.");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        !!target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable);

      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) {
          void redo();
        } else {
          void undo();
        }
        return;
      }
      if (typing) return;
      if (event.key === "Escape") {
        setSelection(null);
        setDraft(null);
        chooseTool("select");
      }
      if ((event.key === "Delete" || event.key === "Backspace") && selection) {
        event.preventDefault();
        deleteSelection();
      }
      if (event.key === "PageDown") {
        event.preventDefault();
        void goToPage(page + 1);
      }
      if (event.key === "PageUp") {
        event.preventDefault();
        void goToPage(page - 1);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [selection, redo, undo, deleteSelection, goToPage, page, chooseTool]);

  const pageInfo = state?.pages[page];
  const selectedText = selection?.kind === "text";
  const selectedImage = selection?.kind === "image";
  const contents = state
    ? [
        ...state.spans.map((span) => ({
          kind: "text" as const,
          key: spanKey(page, span),
          top: span.bbox[1],
          left: span.bbox[0],
          span,
        })),
        ...state.images.map((image) => ({
          kind: "image" as const,
          key: imageKey(page, image),
          top: image.rect[1],
          left: image.rect[0],
          image,
        })),
      ].sort((a, b) => a.top - b.top || a.left - b.left)
    : [];

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <header className="z-30 shrink-0 border-b border-line-soft bg-[#080c14]/95 backdrop-blur-xl">
        <div className="flex h-14 items-center gap-2 px-3">
          <Link
            href="/"
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-line bg-white/[0.03] text-muted transition-colors hover:border-brand/50 hover:text-ink"
            aria-label="Back to files"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>

          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-brand to-brand-2 text-[#05070c]">
            <FilePenLine className="h-4 w-4" strokeWidth={2.2} />
          </div>

          <div className="min-w-0 max-w-[240px]">
            <p className="truncate text-[13px] font-semibold leading-tight text-ink">
              {state?.filename ?? "Loading…"}
            </p>
            <p className="flex items-center gap-1.5 text-[10px] leading-tight text-muted">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400/90" />
              {ops.length === 0 ? "Original file" : `${ops.length} edit${ops.length === 1 ? "" : "s"}`}
              <span className="text-muted/40">·</span> Saved locally
            </p>
          </div>

          <div className="ml-auto flex items-center gap-1 rounded-xl border border-line bg-panel/70 p-1">
            <button
              type="button"
              onClick={() => void goToPage(page - 1)}
              disabled={page <= 0 || busy}
              className="flex h-7 w-7 items-center justify-center rounded-lg text-muted transition-colors hover:bg-white/5 hover:text-ink disabled:opacity-30"
              aria-label="Previous page"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="min-w-[74px] text-center text-xs text-muted">
              Page <span className="font-semibold text-ink">{page + 1}</span> /{" "}
              {state?.pageCount ?? 1}
            </span>
            <button
              type="button"
              onClick={() => void goToPage(page + 1)}
              disabled={!state || page >= state.pageCount - 1 || busy}
              className="flex h-7 w-7 items-center justify-center rounded-lg text-muted transition-colors hover:bg-white/5 hover:text-ink disabled:opacity-30"
              aria-label="Next page"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>

          <div className="flex items-center gap-1 rounded-xl border border-line bg-panel/70 p-1">
            <button
              type="button"
              onClick={() => setZoom((value) => Math.max(0.45, value - 0.15))}
              className="flex h-7 w-7 items-center justify-center rounded-lg text-muted transition-colors hover:bg-white/5 hover:text-ink"
              aria-label="Zoom out"
            >
              <ZoomOut className="h-4 w-4" />
            </button>
            <span className="min-w-[44px] text-center text-xs text-muted">
              {Math.round(zoom * 100)}%
            </span>
            <button
              type="button"
              onClick={() => setZoom((value) => Math.min(3, value + 0.15))}
              className="flex h-7 w-7 items-center justify-center rounded-lg text-muted transition-colors hover:bg-white/5 hover:text-ink"
              aria-label="Zoom in"
            >
              <ZoomIn className="h-4 w-4" />
            </button>
          </div>

          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => void undo()}
              disabled={!ops.length || busy}
              className="flex h-8 w-8 items-center justify-center rounded-lg border border-line bg-white/[0.03] text-muted transition-colors hover:border-brand/50 hover:text-ink disabled:opacity-30"
              aria-label="Undo"
              title="Undo (Ctrl+Z)"
            >
              <Undo2 className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => void redo()}
              disabled={!redoStack.length || busy}
              className="flex h-8 w-8 items-center justify-center rounded-lg border border-line bg-white/[0.03] text-muted transition-colors hover:border-brand/50 hover:text-ink disabled:opacity-30"
              aria-label="Redo"
              title="Redo (Ctrl+Shift+Z)"
            >
              <Redo2 className="h-4 w-4" />
            </button>
          </div>

          <a
            href={docId ? exportUrl(docId) : "#"}
            className="flex h-9 items-center gap-2 rounded-xl bg-gradient-to-r from-brand to-brand-2 px-4 text-sm font-semibold text-[#05070c] transition-opacity hover:opacity-90"
          >
            <Download className="h-4 w-4" />
            Export PDF
          </a>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {state && (
          <nav className="hidden w-[104px] shrink-0 flex-col gap-2 overflow-y-auto border-r border-line-soft bg-[#070a11] px-2 py-3 lg:flex">
            <p className="px-1 text-[10px] font-semibold uppercase tracking-wider text-muted/60">
              Pages
            </p>
            {state.pages.map((info, index) => (
              <button
                key={index}
                type="button"
                onClick={() => void goToPage(index)}
                className={`rounded-lg p-1 text-center transition-colors ${
                  index === page
                    ? "bg-brand/10 ring-1 ring-brand/40"
                    : "hover:bg-white/[0.04]"
                }`}
              >
                <span className="block overflow-hidden rounded border border-line bg-white shadow-sm">
                  <img
                    src={pageRenderUrl(docId ?? "", index, 0.5, state.version)}
                    alt={`Page ${index + 1}`}
                    loading="lazy"
                    className="block w-full"
                    style={{ aspectRatio: `${info.width} / ${info.height}` }}
                  />
                </span>
                <span
                  className={`mt-1 block text-[10px] ${
                    index === page ? "text-brand" : "text-muted/70"
                  }`}
                >
                  {index + 1}
                </span>
              </button>
            ))}
          </nav>
        )}

        <main className="relative flex min-w-0 flex-1 flex-col">
          <div className="pointer-events-none absolute inset-x-0 top-3 z-20 flex justify-center px-4">
            <div className="pointer-events-auto flex items-center gap-0.5 rounded-2xl border border-line bg-[#0b111b]/90 p-1 shadow-[0_18px_50px_-24px_rgba(0,0,0,0.95)] backdrop-blur-xl">
              <ToolButton
                active={tool === "select"}
                onClick={() => chooseTool("select")}
                icon={<MousePointer2 className="h-3.5 w-3.5" />}
                label="Select"
              />
              <ToolButton
                active={tool === "text"}
                onClick={() => chooseTool("text")}
                icon={<Type className="h-3.5 w-3.5" />}
                label="Text"
              />
              <ToolButton
                active={tool === "image"}
                onClick={() => chooseTool("image")}
                icon={<ImagePlus className="h-3.5 w-3.5" />}
                label="Image"
              />
              <ToolButton
                active={tool === "erase"}
                onClick={() => chooseTool("erase")}
                icon={<Eraser className="h-3.5 w-3.5" />}
                label="Erase"
              />
              <div className="mx-1 h-6 w-px bg-line-soft" />
              <button
                type="button"
                onClick={fitWidth}
                aria-label="Fit width"
                title="Fit width"
                className="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-white/[0.06] hover:text-ink"
              >
                <Maximize2 className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto bg-[#070a11] px-8 pb-12 pt-20">
          {error && (
            <div className="sticky top-0 z-20 mx-auto mb-4 flex max-w-xl items-center gap-2 rounded-xl border border-red-500/25 bg-red-500/10 px-4 py-2.5 text-sm text-red-300">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {error}
            </div>
          )}

          {state && state.spans.length === 0 && !loading && (
            <div className="mx-auto mb-4 flex max-w-xl items-start gap-2 rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-2.5 text-xs leading-relaxed text-amber-200">
              <Info className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                This page has no selectable text (scanned PDF). Use the{" "}
                <strong>Erase</strong> tool to clear an area, then the <strong>Text</strong>{" "}
                tool to write on top. The background stays intact.
              </span>
            </div>
          )}

          {state && pageInfo ? (
            <div className="mx-auto w-fit">
              <PageCanvas
                page={page}
                src={pageRenderUrl(docId ?? "", page, Math.min(zoom * 2, 3), state.version)}
                width={pageInfo.width}
                height={pageInfo.height}
                zoom={zoom}
                spans={state.spans}
                images={state.images}
                tool={tool}
                selectedKey={selection?.key ?? null}
                onSelectSpan={selectSpan}
                onEditSpan={selectSpan}
                onSelectImage={selectImage}
                onMoveSpan={moveSpan}
                onCanvasClick={handleCanvasClick}
                onErase={handleErase}
                canTransformImage={(image) => imageAsset(image) !== null}
                onTransformImage={transformImage}
              />
              <p className="mt-3 text-center text-[11px] text-muted/60">
                Page {page + 1} · {Math.round(pageInfo.width)} × {Math.round(pageInfo.height)} pt
              </p>
            </div>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-muted">
              {loading ? (
                <span className="flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" /> Loading page…
                </span>
              ) : (
                "Nothing to show."
              )}
            </div>
          )}

          {busy && (
            <div className="pointer-events-none fixed inset-0 z-40 flex items-center justify-center bg-canvas/30 backdrop-blur-[1px]">
              <span className="flex items-center gap-2 rounded-xl border border-line bg-panel px-4 py-2 text-sm text-ink shadow-xl">
                <Loader2 className="h-4 w-4 animate-spin text-brand" />
                Applying…
              </span>
            </div>
          )}
          </div>

          {tool !== "select" && (
            <div className="pointer-events-none absolute inset-x-0 bottom-4 z-20 flex justify-center px-4">
              <p className="rounded-full border border-brand/30 bg-[#0b111b]/95 px-4 py-1.5 text-[11px] text-brand shadow-xl backdrop-blur">
                {tool === "erase"
                  ? "Drag over the text to remove it — the background stays intact."
                  : `Click on the page to place ${tool === "text" ? "text" : "an image"}.`}
              </p>
            </div>
          )}
        </main>

        <aside className="flex w-[340px] shrink-0 flex-col border-l border-line-soft bg-[#080c14]">
          <div className="flex-1 overflow-y-auto">
            <div className="space-y-5 p-4">
              <div>
                <div className="mb-3 flex items-center gap-2">
                  <MousePointer2 className="h-3.5 w-3.5 text-brand" />
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                    Inspector
                  </p>
                  {(selectedText || selectedImage) && (
                    <span className="ml-auto rounded-full border border-brand/30 bg-brand/10 px-2 py-0.5 text-[10px] text-brand">
                      {selectedText ? "Text" : "Image"}
                    </span>
                  )}
                </div>
                {!selectedText && !selectedImage && (
                  <div className="rounded-xl border border-dashed border-line/70 px-4 py-6 text-center">
                    <MousePointer2 className="mx-auto mb-2 h-5 w-5 text-muted/40" />
                    <p className="text-xs font-medium text-muted">Nothing selected</p>
                    <p className="mt-1 text-[11px] leading-relaxed text-muted/60">
                      Click a highlighted block on the page, or pick one from the list
                      below.
                    </p>
                  </div>
                )}
              </div>

            {selectedText && draft && selection.kind === "text" && (
              <div className="space-y-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                    Text
                  </p>
                  <div className="flex min-w-0 items-center gap-2">
                    {selection.span.ocr && (
                      <span className="shrink-0 rounded-full border border-brand/40 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-brand">
                        OCR
                      </span>
                    )}
                    <span className="truncate text-[10px] text-muted/70">
                      {selection.span.font}
                    </span>
                  </div>
                </div>
                <textarea
                  ref={textareaRef}
                  value={draft.text}
                  onChange={(event) =>
                    setDraft((current) =>
                      current ? { ...current, text: event.target.value } : current,
                    )
                  }
                  onKeyDown={(event) => {
                    if (
                      (event.ctrlKey || event.metaKey) &&
                      event.key.toLowerCase() === "b"
                    ) {
                      event.preventDefault();
                      setDraft((current) =>
                        current ? { ...current, bold: !current.bold } : current,
                      );
                      return;
                    }
                    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                      event.preventDefault();
                      applyText();
                    }
                  }}
                  rows={3}
                  className="w-full resize-y rounded-xl border border-line bg-canvas/70 p-3 text-sm text-ink outline-none transition-colors focus:border-brand/60"
                />
                <div className="grid grid-cols-2 gap-2">
                  <label className="space-y-1">
                    <span className="text-[11px] text-muted">Font size</span>
                    <input
                      type="number"
                      min={4}
                      max={200}
                      step={0.5}
                      value={draft.size}
                      onChange={(event) =>
                        setDraft((current) =>
                          current
                            ? { ...current, size: Number(event.target.value) || 11 }
                            : current,
                        )
                      }
                      className="w-full rounded-lg border border-line bg-canvas/70 px-2.5 py-1.5 text-sm text-ink outline-none focus:border-brand/60"
                    />
                  </label>
                  <label className="space-y-1">
                    <span className="text-[11px] text-muted">Colour</span>
                    <input
                      type="color"
                      value={draft.color}
                      onChange={(event) =>
                        setDraft((current) =>
                          current ? { ...current, color: event.target.value } : current,
                        )
                      }
                      className="h-[34px] w-full cursor-pointer rounded-lg border border-line bg-canvas/70 p-1"
                    />
                  </label>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    setDraft((current) =>
                      current ? { ...current, bold: !current.bold } : current,
                    )
                  }
                  aria-pressed={draft.bold}
                  title="Bold (Ctrl+B)"
                  className={`flex w-full items-center justify-center gap-2 rounded-lg border px-3 py-1.5 text-sm font-semibold transition-colors ${
                    draft.bold
                      ? "border-brand/60 bg-brand/15 text-brand"
                      : "border-line bg-canvas/70 text-muted hover:border-brand/40 hover:text-ink"
                  }`}
                >
                  <Bold className="h-4 w-4" />
                  Bold
                </button>
                <button
                  type="button"
                  onClick={applyText}
                  disabled={busy || !draft.text.trim()}
                  className="w-full rounded-xl bg-gradient-to-r from-brand to-brand-2 px-4 py-2 text-sm font-semibold text-[#05070c] transition-opacity hover:opacity-90 disabled:opacity-40"
                >
                  Apply changes
                </button>
                <button
                  type="button"
                  onClick={() => {
                    replaceTextTargetRef.current = selection.span;
                    replaceTextImageInput.current?.click();
                  }}
                  disabled={busy}
                  className="flex w-full items-center justify-center gap-2 rounded-xl border border-line bg-white/[0.03] px-4 py-2 text-sm text-muted transition-colors hover:border-brand-2/50 hover:text-ink disabled:opacity-40"
                >
                  <ImagePlus className="h-4 w-4" />
                  Replace with photo
                </button>
                <button
                  type="button"
                  onClick={deleteSelection}
                  disabled={busy}
                  className="flex w-full items-center justify-center gap-2 rounded-xl border border-line bg-white/[0.03] px-4 py-2 text-sm text-muted transition-colors hover:border-red-500/40 hover:text-red-300 disabled:opacity-40"
                >
                  <Trash2 className="h-4 w-4" />
                  Delete text
                </button>
                <p className="text-[11px] leading-relaxed text-muted/70">
                  Position and size stay the same. Drag the highlighted block on the page to
                  move it. Ctrl+Enter applies the change.
                </p>
              </div>
            )}

            {selectedImage && selection.kind === "image" && (
              <div className="space-y-3">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                  Image
                </p>
                <div className="rounded-xl border border-line bg-canvas/50 p-3 text-xs text-muted">
                  {selection.image.width} × {selection.image.height} px
                  <br />
                  Position {Math.round(selection.image.rect[0])},{" "}
                  {Math.round(selection.image.rect[1])} pt
                </div>
                <button
                  type="button"
                  onClick={() => {
                    replaceTargetRef.current = selection.image;
                    replaceImageInput.current?.click();
                  }}
                  disabled={busy}
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-brand to-brand-2 px-4 py-2 text-sm font-semibold text-[#05070c] transition-opacity hover:opacity-90 disabled:opacity-40"
                >
                  <ImagePlus className="h-4 w-4" />
                  Replace image
                </button>
                <button
                  type="button"
                  onClick={deleteSelection}
                  disabled={busy}
                  className="flex w-full items-center justify-center gap-2 rounded-xl border border-line bg-white/[0.03] px-4 py-2 text-sm text-muted transition-colors hover:border-red-500/40 hover:text-red-300 disabled:opacity-40"
                >
                  <Trash2 className="h-4 w-4" />
                  Delete image
                </button>
                <p className="text-[11px] leading-relaxed text-muted/70">
                  {imageAsset(selection.image)
                    ? "Drag the image on the page to move it, or drag a corner handle to resize. Hold Shift while resizing to keep the shape."
                    : "The new photo fills this exact box, so the position and size stay the same."}
                </p>
              </div>
            )}

            <div className="h-px bg-line-soft" />

            <div>
              <div className="mb-2 flex items-center gap-2">
                <Layers className="h-3.5 w-3.5 text-brand-2" />
                <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                  Page contents
                </p>
                <span className="ml-auto text-[10px] text-muted/60">
                  {state?.spans.length ?? 0} text · {state?.images.length ?? 0} image
                </span>
              </div>
              <div className="space-y-1.5">
                {contents.map((item) =>
                  item.kind === "text" ? (
                    <ContentRow
                      key={item.key}
                      active={selection?.key === item.key}
                      kind="text"
                      label={normalize(item.span.text) || "(empty)"}
                      meta={`${Math.round(item.span.size)} pt`}
                      badge={<Type className="h-3.5 w-3.5" />}
                      onChange={() => selectSpan(item.span)}
                      onDelete={() => void deleteSpanAt(item.span)}
                    />
                  ) : (
                    <ContentRow
                      key={item.key}
                      active={selection?.key === item.key}
                      kind="image"
                      label={`Image ${item.image.width} × ${item.image.height} px`}
                      meta={`${Math.round(item.image.rect[2] - item.image.rect[0])} × ${Math.round(
                        item.image.rect[3] - item.image.rect[1],
                      )} pt`}
                      badge={
                        <ImageThumb
                          src={pageRenderUrl(
                            docId ?? "",
                            page,
                            Math.min(zoom * 2, 3),
                            state?.version ?? 0,
                          )}
                          pageWidth={pageInfo?.width ?? 1}
                          pageHeight={pageInfo?.height ?? 1}
                          rect={item.image.rect}
                        />
                      }
                      onChange={() => changeImage(item.image)}
                      onDelete={() => void deleteImageAt(item.image)}
                    />
                  ),
                )}
                {contents.length === 0 && (
                  <p className="rounded-lg border border-dashed border-line px-3 py-3 text-center text-[11px] leading-relaxed text-muted/70">
                    No text or images on this page. Use the Text or Image tool to add
                    something.
                  </p>
                )}
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-muted/70">
                Every block is outlined on the page. Pick one to change or delete — the
                position and size stay the same.
              </p>
            </div>

            <div className="h-px bg-line-soft" />

            <button
              type="button"
              onClick={() => void handleReset()}
              disabled={busy || ops.length === 0}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-line bg-white/[0.03] px-4 py-2 text-xs text-muted transition-colors hover:border-red-500/40 hover:text-red-300 disabled:opacity-40"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Reset all edits
            </button>
            </div>
          </div>

          <div className="border-t border-line-soft p-4 text-[11px] text-muted/60">
            Background, layout and fonts stay untouched. Everything is processed on this
            computer.
          </div>
        </aside>
      </div>

      <footer className="flex h-8 shrink-0 items-center gap-3 border-t border-line-soft bg-[#070a11] px-4 text-[11px] text-muted/80">
        <span className="flex max-w-[280px] items-center gap-1.5">
          <FilePenLine className="h-3 w-3 shrink-0" />
          <span className="truncate">{state?.filename ?? "No document"}</span>
        </span>
        <span className="text-muted/25">|</span>
        <span>
          Page {page + 1} of {state?.pageCount ?? 1}
        </span>
        {pageInfo && (
          <>
            <span className="text-muted/25">|</span>
            <span>
              {Math.round(pageInfo.width)} × {Math.round(pageInfo.height)} pt
            </span>
          </>
        )}
        <span className="ml-auto">Zoom {Math.round(zoom * 100)}%</span>
        <span className="text-muted/25">|</span>
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
          All changes saved locally
        </span>
      </footer>

      <input
        ref={addImageInput}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/bmp,image/tiff"
        className="hidden"
        onChange={handleAddImageFile}
      />
      <input
        ref={replaceImageInput}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/bmp,image/tiff"
        className="hidden"
        onChange={handleReplaceImageFile}
      />
      <input
        ref={replaceTextImageInput}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/bmp,image/tiff"
        className="hidden"
        onChange={handleReplaceTextWithImageFile}
      />
    </div>
  );
}

function ToolButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      className={`flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[11px] font-medium transition-colors ${
        active
          ? "bg-brand/15 text-brand ring-1 ring-brand/30"
          : "text-muted hover:bg-white/[0.06] hover:text-ink"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

function ContentRow({
  active,
  kind,
  label,
  meta,
  badge,
  onChange,
  onDelete,
}: {
  active: boolean;
  kind: "text" | "image";
  label: string;
  meta: string;
  badge: React.ReactNode;
  onChange: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onChange}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onChange();
        }
      }}
      className={`flex cursor-pointer items-center gap-2 rounded-lg border px-2 py-1.5 transition-colors ${
        active
          ? "border-brand/60 bg-brand/10"
          : "border-line bg-white/[0.02] hover:border-brand/40 hover:bg-white/[0.04]"
      }`}
    >
      <span
        className={`flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded-md border ${
          kind === "text"
            ? "border-brand/40 bg-brand/10 text-brand"
            : "border-brand-2/40 bg-brand-2/10 text-brand-2"
        }`}
      >
        {badge}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[12px] leading-tight text-ink">{label}</span>
        <span className="block text-[10px] leading-tight text-muted/70">{meta}</span>
      </span>
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          onChange();
        }}
        aria-label={kind === "text" ? "Edit text" : "Replace image"}
        title={kind === "text" ? "Edit this text" : "Replace this image"}
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted transition-colors hover:bg-white/10 hover:text-ink"
      >
        {kind === "text" ? (
          <Pencil className="h-3.5 w-3.5" />
        ) : (
          <ImagePlus className="h-3.5 w-3.5" />
        )}
      </button>
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          onDelete();
        }}
        aria-label={kind === "text" ? "Delete text" : "Delete image"}
        title={kind === "text" ? "Delete this text" : "Delete this image"}
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted transition-colors hover:bg-red-500/15 hover:text-red-300"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function ImageThumb({
  src,
  pageWidth,
  pageHeight,
  rect,
}: {
  src: string;
  pageWidth: number;
  pageHeight: number;
  rect: number[];
}) {
  const box = 28;
  const width = Math.max(rect[2] - rect[0], 1);
  const height = Math.max(rect[3] - rect[1], 1);
  const scale = Math.min(box / width, box / height);
  const left = (box - width * scale) / 2 - rect[0] * scale;
  const top = (box - height * scale) / 2 - rect[1] * scale;
  return (
    <span
      className="block h-full w-full"
      style={{
        backgroundImage: `url(${src})`,
        backgroundSize: `${pageWidth * scale}px ${pageHeight * scale}px`,
        backgroundPosition: `${left}px ${top}px`,
        backgroundRepeat: "no-repeat",
      }}
    />
  );
}



