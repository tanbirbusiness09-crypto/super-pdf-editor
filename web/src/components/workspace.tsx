"use client";

import { useCallback, useEffect, useState } from "react";
import {
  FilePenLine,
  FileStack,
  Hash,
  Image as ImageIcon,
  Layers,
  Loader2,
  ShieldCheck,
  Trash2,
  Type,
  Wifi,
  WifiOff,
} from "lucide-react";
import Dropzone from "@/components/dropzone";
import DocumentPreview from "@/components/document-preview";
import {
  DocumentMeta,
  apiUrl,
  deleteDocument,
  formatBytes,
  getDocument,
  listDocuments,
  renderUrl,
  uploadDocument,
} from "@/lib/api";

const FEATURES = [
  { icon: Type, title: "Edit text", copy: "Rewrite any word, keep the font" },
  { icon: ImageIcon, title: "Swap images", copy: "Replace or add pictures" },
  { icon: Hash, title: "Fix numbers", copy: "Change prices, totals, dates" },
  { icon: Layers, title: "Keep the look", copy: "Background stays untouched" },
];

export default function Workspace() {
  const [doc, setDoc] = useState<DocumentMeta | null>(null);
  const [recent, setRecent] = useState<DocumentMeta[]>([]);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);

  const refreshRecent = useCallback(async () => {
    try {
      const items = await listDocuments();
      setRecent(items);
      setOnline(true);
    } catch {
      setOnline(false);
    }
  }, []);

  useEffect(() => {
    const tick = () => {
      void refreshRecent();
    };
    const initial = window.setTimeout(tick, 0);
    const timer = window.setInterval(tick, 15000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
    };
  }, [refreshRecent]);

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("doc");
    if (!id) return;
    let cancelled = false;
    getDocument(id)
      .then((meta) => {
        if (!cancelled) setDoc(meta);
      })
      .catch(() => {
        if (!cancelled) setError("That document is no longer available.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const syncUrl = (id: string | null) => {
    const url = new URL(window.location.href);
    if (id) {
      url.searchParams.set("doc", id);
    } else {
      url.searchParams.delete("doc");
    }
    window.history.replaceState(null, "", url);
  };

  const openDocument = (meta: DocumentMeta) => {
    setError(null);
    setDoc(meta);
    syncUrl(meta.id);
  };

  const closeDocument = () => {
    setDoc(null);
    syncUrl(null);
  };

  const handleFile = async (file: File) => {
    setError(null);
    setUploading(true);
    setProgress(0);
    try {
      const meta = await uploadDocument(file, setProgress);
      openDocument(meta);
      await refreshRecent();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (id: string) => {
    const target = recent.find((item) => item.id === id);
    const confirmed = window.confirm(
      `Remove "${target?.filename ?? "this document"}" from local storage?`,
    );
    if (!confirmed) return;
    setError(null);
    setDeletingId(id);
    try {
      await deleteDocument(id);
      if (doc?.id === id) closeDocument();
      await refreshRecent();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not remove the file.");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-20 border-b border-line-soft bg-canvas/80 backdrop-blur-xl">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-5 py-3.5 sm:px-8">
          <div className="flex items-center gap-3">
            <div className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-brand to-brand-2 text-[#05070c]">
              <FilePenLine className="h-5 w-5" strokeWidth={2.2} />
            </div>
            <div className="leading-tight">
              <p className="text-sm font-semibold tracking-tight text-ink">PDF Studio</p>
              <p className="text-[11px] text-muted">Local PDF editor</p>
            </div>
            <span className="ml-1 rounded-md border border-line bg-white/[0.03] px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted">
              v0.1
            </span>
          </div>

          <div className="flex items-center gap-3">
            <span className="hidden items-center gap-1.5 text-xs text-muted sm:flex">
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-400/80" />
              Offline · private
            </span>
            <span
              className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium ${
                online === false
                  ? "border-red-500/30 bg-red-500/10 text-red-300"
                  : "border-emerald-500/25 bg-emerald-500/10 text-emerald-300"
              }`}
              title={online === false ? "Run start.bat to launch the local engine" : apiUrl("/api/health")}
            >
              {online === false ? (
                <WifiOff className="h-3 w-3" />
              ) : online === null ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Wifi className="h-3 w-3" />
              )}
              {online === false ? "Engine offline" : online === null ? "Checking" : "Engine online"}
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-10 sm:px-8 sm:py-14">
        {doc ? (
          <DocumentPreview
            doc={doc}
            onBack={closeDocument}
            onDelete={handleDelete}
            deleting={deletingId === doc.id}
          />
        ) : (
          <div className="space-y-12">
            <div className="mx-auto max-w-2xl space-y-5 text-center">
              <span className="inline-flex items-center gap-2 rounded-full border border-line bg-white/[0.03] px-3 py-1 text-[11px] font-medium uppercase tracking-wider text-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-brand-2" />
                Text · Images · Numbers
              </span>
              <h1 className="text-4xl font-semibold leading-[1.08] tracking-tight text-ink sm:text-5xl">
                Edit <span className="text-gradient">any PDF</span>,
                <br className="hidden sm:block" /> keep the original look.
              </h1>
              <p className="mx-auto max-w-xl text-[15px] leading-relaxed text-muted">
                Change text, swap images and fix numbers — the background, layout and
                fonts stay exactly as they are. Everything runs on your own computer.
              </p>
            </div>

            <div className="mx-auto max-w-3xl">
              <Dropzone
                onFile={handleFile}
                busy={uploading}
                progress={progress}
                error={error}
              />
            </div>

            <div className="mx-auto grid max-w-4xl gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {FEATURES.map((feature) => (
                <div
                  key={feature.title}
                  className="rounded-2xl border border-line bg-panel/50 p-4"
                >
                  <feature.icon className="h-4.5 w-4.5 text-brand" />
                  <p className="mt-3 text-sm font-medium text-ink">{feature.title}</p>
                  <p className="mt-0.5 text-xs text-muted">{feature.copy}</p>
                </div>
              ))}
            </div>

            <section className="mx-auto max-w-4xl">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="flex items-center gap-2 text-sm font-medium uppercase tracking-wider text-muted">
                  <FileStack className="h-4 w-4" />
                  Recent files
                </h2>
                <span className="text-xs text-muted/70">Stored in data/uploads</span>
              </div>

              {recent.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-line bg-panel/40 px-6 py-10 text-center">
                  <p className="text-sm text-muted">
                    {online === false
                      ? "Local engine is not running. Double-click start.bat, then refresh."
                      : "No files yet. Upload a PDF above to get started."}
                  </p>
                </div>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {recent.map((item) => (
                    <div
                      key={item.id}
                      className="group flex items-center gap-3 rounded-2xl border border-line bg-panel/60 p-3 transition-colors hover:border-brand/40 hover:bg-panel-2/70"
                    >
                      <button
                        type="button"
                        onClick={() => openDocument(item)}
                        className="flex min-w-0 flex-1 items-center gap-3 text-left"
                      >
                        <div className="h-16 w-12 shrink-0 overflow-hidden rounded-lg border border-line bg-white">
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={renderUrl(item.id, 0, 0.6)}
                            alt=""
                            loading="lazy"
                            className="h-full w-full object-cover object-top"
                          />
                        </div>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-ink">
                            {item.filename}
                          </p>
                          <p className="mt-0.5 text-xs text-muted">
                            {item.pageCount} {item.pageCount === 1 ? "page" : "pages"} ·{" "}
                            {formatBytes(item.size)}
                          </p>
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(item.id)}
                        disabled={deletingId === item.id}
                        aria-label={`Remove ${item.filename}`}
                        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted opacity-0 transition-all hover:bg-red-500/10 hover:text-red-300 focus-visible:opacity-100 group-hover:opacity-100 disabled:opacity-50"
                      >
                        {deletingId === item.id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Trash2 className="h-3.5 w-3.5" />
                        )}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}
      </main>

      <footer className="border-t border-line-soft">
        <div className="mx-auto flex w-full max-w-6xl flex-col items-center justify-between gap-2 px-5 py-5 text-xs text-muted/70 sm:flex-row sm:px-8">
          <p>PDF Studio · runs entirely offline on this computer</p>
          <p>Next: text &amp; image editing engine</p>
        </div>
      </footer>
    </div>
  );
}
