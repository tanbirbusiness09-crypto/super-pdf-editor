"use client";

import Link from "next/link";
import { useState } from "react";
import {
  ArrowLeft,
  FileText,
  Image as ImageIcon,
  Loader2,
  Sparkles,
  Trash2,
} from "lucide-react";
import {
  DocumentMeta,
  formatBytes,
  formatDate,
  renderUrl,
} from "@/lib/api";

type Props = {
  doc: DocumentMeta;
  onBack: () => void;
  deleting: boolean;
  onDelete: (id: string) => void;
};

export default function DocumentPreview({
  doc,
  onBack,
  onDelete,
  deleting,
}: Props) {
  const [loaded, setLoaded] = useState<Record<number, boolean>>({});

  return (
    <section className="space-y-6">
      <div className="card-glow flex flex-col gap-5 rounded-2xl border border-line bg-panel/80 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-4">
          <button
            type="button"
            onClick={onBack}
            className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-line bg-white/[0.03] text-muted transition-colors hover:border-brand/50 hover:text-ink"
            aria-label="Back to upload"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>

          <div className="min-w-0 space-y-2">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-md bg-brand/15 text-brand">
                {doc.kind === "image" ? (
                  <ImageIcon className="h-3.5 w-3.5" />
                ) : (
                  <FileText className="h-3.5 w-3.5" />
                )}
              </span>
              <h2 className="truncate text-lg font-semibold text-ink">{doc.filename}</h2>
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
              <span>{doc.pageCount} {doc.pageCount === 1 ? "page" : "pages"}</span>
              <span className="h-1 w-1 rounded-full bg-line" />
              <span>{formatBytes(doc.size)}</span>
              <span className="h-1 w-1 rounded-full bg-line" />
              <span>{formatDate(doc.createdAt)}</span>
              <span className="rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-emerald-300">
                Ready
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 sm:shrink-0">
          <button
            type="button"
            onClick={() => onDelete(doc.id)}
            disabled={deleting}
            className="flex h-10 items-center gap-2 rounded-xl border border-line bg-white/[0.03] px-3.5 text-sm text-muted transition-colors hover:border-red-500/40 hover:text-red-300 disabled:opacity-50"
          >
            {deleting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="h-4 w-4" />
            )}
            Remove
          </button>
          <Link
            href={`/editor/?doc=${doc.id}`}
            className="flex h-10 items-center gap-2 rounded-xl bg-gradient-to-r from-brand to-brand-2 px-4 text-sm font-semibold text-[#05070c] transition-opacity hover:opacity-90"
          >
            <Sparkles className="h-4 w-4" />
            Open editor
          </Link>
        </div>
      </div>

      <div>
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-medium uppercase tracking-wider text-muted">
            Page preview
          </h3>
          <span className="text-xs text-muted/70">
            Rendered locally from the original file
          </span>
        </div>

        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {doc.pages.map((page) => (
            <div key={page.index} className="space-y-2">
              <div
                className="relative overflow-hidden rounded-xl border border-line bg-white shadow-[0_20px_50px_-30px_rgba(0,0,0,0.9)]"
                style={{ aspectRatio: `${page.width} / ${page.height}` }}
              >
                {!loaded[page.index] && (
                  <div className="shimmer absolute inset-0 bg-white/90" />
                )}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={renderUrl(doc.id, page.index, 1.6)}
                  alt={`Page ${page.index + 1}`}
                  decoding="async"
                  onLoad={() =>
                    setLoaded((current) => ({ ...current, [page.index]: true }))
                  }
                  className="h-full w-full object-contain"
                />
              </div>
              <p className="text-center text-xs text-muted">
                Page {page.index + 1} · {Math.round(page.width)} × {Math.round(page.height)} pt
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
