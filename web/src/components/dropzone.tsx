"use client";

import { useCallback, useRef, useState } from "react";
import { FileUp, Loader2, ShieldCheck } from "lucide-react";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff";
const VALID = /\.(pdf|png|jpe?g|webp|bmp|tiff?)$/i;
const MAX_BYTES = 100 * 1024 * 1024;

type Props = {
  onFile: (file: File) => void;
  busy: boolean;
  progress: number;
  error: string | null;
};

export default function Dropzone({ onFile, busy, progress, error }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const handleFiles = useCallback(
    (files: FileList | null) => {
      setLocalError(null);
      const file = files?.[0];
      if (!file) return;
      if (!VALID.test(file.name)) {
        setLocalError("Please choose a PDF or an image (PNG, JPG, WEBP, BMP, TIFF).");
        return;
      }
      if (file.size > MAX_BYTES) {
        setLocalError("File is larger than 100 MB.");
        return;
      }
      onFile(file);
    },
    [onFile],
  );

  const openPicker = () => {
    if (!busy) inputRef.current?.click();
  };

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload a PDF or image"
        onClick={openPicker}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openPicker();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          if (!busy) handleFiles(event.dataTransfer.files);
        }}
        className={`card-glow group relative overflow-hidden rounded-3xl border-2 border-dashed bg-panel/70 p-10 text-center transition-colors sm:p-14 ${
          dragging
            ? "border-brand bg-brand/10"
            : "border-line hover:border-brand/60 hover:bg-panel-2/70"
        } ${busy ? "cursor-wait" : "cursor-pointer"}`}
      >
        <div className="pointer-events-none absolute inset-0 grid-surface opacity-60" />

        <div className="relative flex flex-col items-center gap-5">
          <div className="relative">
            <div className="absolute inset-0 rounded-2xl bg-brand/30 blur-xl" />
            <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl border border-white/10 bg-gradient-to-br from-brand/30 to-brand-2/20 text-ink">
              {busy ? (
                <Loader2 className="h-7 w-7 animate-spin" />
              ) : (
                <FileUp className="h-7 w-7" />
              )}
            </div>
          </div>

          {busy ? (
            <div className="w-full max-w-sm space-y-3">
              <p className="text-sm font-medium text-ink">Processing your file…</p>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-brand to-brand-2 transition-all duration-300"
                  style={{ width: `${Math.max(progress, 4)}%` }}
                />
              </div>
              <p className="text-xs text-muted">{progress}% uploaded</p>
            </div>
          ) : (
            <>
              <div className="space-y-2">
                <p className="text-lg font-semibold text-ink">
                  Drag &amp; drop your PDF or image
                </p>
                <p className="text-sm text-muted">
                  or{" "}
                  <span className="font-medium text-brand">browse files</span> from your
                  computer
                </p>
              </div>
              <div className="flex flex-wrap items-center justify-center gap-2 text-xs text-muted">
                <span className="rounded-full border border-line bg-white/[0.03] px-3 py-1">
                  PDF
                </span>
                <span className="rounded-full border border-line bg-white/[0.03] px-3 py-1">
                  PNG · JPG · WEBP
                </span>
                <span className="rounded-full border border-line bg-white/[0.03] px-3 py-1">
                  up to 100 MB
                </span>
              </div>
            </>
          )}

          <div className="mt-1 flex items-center gap-1.5 text-xs text-muted/80">
            <ShieldCheck className="h-3.5 w-3.5 text-emerald-400/80" />
            Files never leave this computer
          </div>
        </div>

        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          className="hidden"
          onChange={(event) => {
            handleFiles(event.target.files);
            event.target.value = "";
          }}
        />
      </div>

      {(localError || error) && (
        <p className="mt-3 rounded-xl border border-red-500/25 bg-red-500/10 px-4 py-2.5 text-sm text-red-300">
          {localError ?? error}
        </p>
      )}
    </div>
  );
}
