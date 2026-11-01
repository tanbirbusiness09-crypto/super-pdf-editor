"use client";

import { useState } from "react";
import { Pencil } from "lucide-react";
import type { PageImage, Span } from "@/lib/editor-api";

export type Tool = "select" | "text" | "image" | "erase";

type Props = {
  page: number;
  src: string;
  width: number;
  height: number;
  zoom: number;
  spans: Span[];
  images: PageImage[];
  tool: Tool;
  selectedKey: string | null;
  onSelectSpan: (span: Span, key: string) => void;
  onEditSpan?: (span: Span, key: string) => void;
  onSelectImage: (image: PageImage, key: string) => void;
  onMoveSpan: (span: Span, dx: number, dy: number) => void;
  onCanvasClick: (x: number, y: number) => void;
  onErase: (rect: number[]) => void;
  onTransformImage: (image: PageImage, rect: number[]) => void;
  canTransformImage: (image: PageImage) => boolean;
};

const HANDLE = 10;
const MIN_SIZE = 8;
const CORNERS = ["nw", "ne", "sw", "se"] as const;

type Corner = (typeof CORNERS)[number];

function clampValue(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function rectStyle(rect: number[], zoom: number) {
  return {
    left: rect[0] * zoom,
    top: rect[1] * zoom,
    width: Math.max(2, (rect[2] - rect[0]) * zoom),
    height: Math.max(2, (rect[3] - rect[1]) * zoom),
  };
}

function rectArea(rect: number[]): number {
  return Math.max(0, rect[2] - rect[0]) * Math.max(0, rect[3] - rect[1]);
}

export function spanKey(page: number, span: Span): string {
  return `t:${page}:${span.bbox.join(",")}:${span.text}`;
}

export function imageKey(page: number, image: PageImage): string {
  return `i:${page}:${image.xref}:${image.rect.join(",")}`;
}

export default function PageCanvas({
  page,
  src,
  width,
  height,
  zoom,
  spans,
  images,
  tool,
  selectedKey,
  onSelectSpan,
  onEditSpan,
  onSelectImage,
  onMoveSpan,
  onCanvasClick,
  onErase,
  onTransformImage,
  canTransformImage,
}: Props) {
  const [drag, setDrag] = useState<{ key: string; dx: number; dy: number } | null>(null);
  const [imageEdit, setImageEdit] = useState<{ key: string; rect: number[] } | null>(
    null,
  );
  const [eraseRect, setEraseRect] = useState<
    { x0: number; y0: number; x1: number; y1: number } | null
  >(null);

  const handlePagePointerDown = (event: React.PointerEvent) => {
    if (tool !== "erase" || event.button !== 0) return;
    event.preventDefault();
    const bounds = event.currentTarget.getBoundingClientRect();
    const startX = (event.clientX - bounds.left) / zoom;
    const startY = (event.clientY - bounds.top) / zoom;
    let moved = false;

    const move = (moveEvent: PointerEvent) => {
      const x = (moveEvent.clientX - bounds.left) / zoom;
      const y = (moveEvent.clientY - bounds.top) / zoom;
      if (Math.abs(x - startX) > 2 || Math.abs(y - startY) > 2) moved = true;
      setEraseRect({ x0: startX, y0: startY, x1: x, y1: y });
    };

    const up = (upEvent: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      const x = (upEvent.clientX - bounds.left) / zoom;
      const y = (upEvent.clientY - bounds.top) / zoom;
      setEraseRect(null);
      if (!moved) return;
      const rect = [
        Math.min(startX, x),
        Math.min(startY, y),
        Math.max(startX, x),
        Math.max(startY, y),
      ];
      if (rect[2] - rect[0] > 2 && rect[3] - rect[1] > 2) onErase(rect);
    };

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const handleSpanPointerDown = (
    event: React.PointerEvent,
    span: Span,
    key: string,
  ) => {
    if (tool !== "select" || event.button !== 0) return;
    event.stopPropagation();
    onSelectSpan(span, key);

    const startX = event.clientX;
    const startY = event.clientY;
    let moved = false;

    const move = (moveEvent: PointerEvent) => {
      const dx = (moveEvent.clientX - startX) / zoom;
      const dy = (moveEvent.clientY - startY) / zoom;
      if (Math.abs(dx) > 1 || Math.abs(dy) > 1) moved = true;
      setDrag({ key, dx, dy });
    };

    const up = (upEvent: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setDrag(null);
      if (!moved) return;
      const dx = (upEvent.clientX - startX) / zoom;
      const dy = (upEvent.clientY - startY) / zoom;
      onMoveSpan(span, dx, dy);
    };

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const handleImagePointerDown = (
    event: React.PointerEvent,
    image: PageImage,
    key: string,
  ) => {
    if (tool !== "select" || event.button !== 0) return;
    event.stopPropagation();
    onSelectImage(image, key);
    if (!canTransformImage(image)) return;

    const startX = event.clientX;
    const startY = event.clientY;
    const start = image.rect;
    const boxWidth = start[2] - start[0];
    const boxHeight = start[3] - start[1];
    let latest = start;
    let moved = false;

    const move = (moveEvent: PointerEvent) => {
      const dx = (moveEvent.clientX - startX) / zoom;
      const dy = (moveEvent.clientY - startY) / zoom;
      if (Math.abs(dx) > 0.75 || Math.abs(dy) > 0.75) moved = true;
      if (!moved) return;
      const x0 = clampValue(start[0] + dx, 0, width - boxWidth);
      const y0 = clampValue(start[1] + dy, 0, height - boxHeight);
      latest = [x0, y0, x0 + boxWidth, y0 + boxHeight];
      setImageEdit({ key, rect: latest });
    };

    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setImageEdit(null);
      if (moved) onTransformImage(image, latest);
    };

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const handleResizePointerDown = (
    event: React.PointerEvent,
    image: PageImage,
    key: string,
    corner: Corner,
  ) => {
    if (tool !== "select" || event.button !== 0) return;
    event.stopPropagation();
    event.preventDefault();

    const startX = event.clientX;
    const startY = event.clientY;
    const start = image.rect;
    const aspect = (start[3] - start[1]) / Math.max(start[2] - start[0], 0.01);
    let latest = start;
    let moved = false;

    const move = (moveEvent: PointerEvent) => {
      const dx = (moveEvent.clientX - startX) / zoom;
      const dy = (moveEvent.clientY - startY) / zoom;
      if (Math.abs(dx) > 0.75 || Math.abs(dy) > 0.75) moved = true;
      if (!moved) return;

      let x0 = start[0];
      let y0 = start[1];
      let x1 = start[2];
      let y1 = start[3];
      if (corner.includes("w")) x0 = start[0] + dx;
      if (corner.includes("e")) x1 = start[2] + dx;
      if (corner.includes("n")) y0 = start[1] + dy;
      if (corner.includes("s")) y1 = start[3] + dy;

      if (moveEvent.shiftKey) {
        const newHeight = Math.max(MIN_SIZE, x1 - x0) * aspect;
        if (corner.includes("s")) y1 = y0 + newHeight;
        else y0 = y1 - newHeight;
      }

      x0 = clampValue(x0, 0, width - MIN_SIZE);
      y0 = clampValue(y0, 0, height - MIN_SIZE);
      x1 = clampValue(x1, x0 + MIN_SIZE, width);
      y1 = clampValue(y1, y0 + MIN_SIZE, height);

      latest = [x0, y0, x1, y1];
      setImageEdit({ key, rect: latest });
    };

    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setImageEdit(null);
      if (moved) onTransformImage(image, latest);
    };

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div
      className="relative select-none bg-white shadow-[0_30px_80px_-40px_rgba(0,0,0,0.95)]"
      style={{
        width: width * zoom,
        height: height * zoom,
        cursor: tool === "erase" ? "crosshair" : undefined,
      }}
      onPointerDown={handlePagePointerDown}
      onClick={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        const x = (event.clientX - rect.left) / zoom;
        const y = (event.clientY - rect.top) / zoom;
        onCanvasClick(x, y);
      }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt="PDF page"
        draggable={false}
        className="pointer-events-none absolute inset-0 h-full w-full object-fill"
      />

      {images.map((image) => {
        const key = imageKey(page, image);
        const selected = selectedKey === key;
        const transformable = canTransformImage(image);
        const displayRect =
          imageEdit?.key === key ? imageEdit.rect : image.rect;
        return (
          <div
            key={key}
            onClick={(event) => event.stopPropagation()}
            onPointerDown={(event) => handleImagePointerDown(event, image, key)}
            className={`absolute rounded-[2px] border-2 transition-colors ${
              tool !== "select"
                ? "pointer-events-none border-transparent"
                : selected
                  ? `border-brand-2 bg-brand-2/15 ${transformable ? "cursor-move" : "cursor-pointer"}`
                  : `border-brand-2/40 bg-brand-2/[0.04] hover:border-brand-2 hover:bg-brand-2/10 ${
                      transformable ? "cursor-move" : "cursor-pointer"
                    }`
            }`}
            style={rectStyle(displayRect, zoom)}
            title={transformable ? "Drag to move · drag a corner to resize" : "Image"}
          >
            {selected &&
              transformable &&
              CORNERS.map((corner) => (
                <span
                  key={corner}
                  onPointerDown={(event) =>
                    handleResizePointerDown(event, image, key, corner)
                  }
                  className="absolute z-10 rounded-[2px] border border-white bg-brand-2 shadow-[0_1px_3px_rgba(0,0,0,0.6)]"
                  style={{
                    width: HANDLE,
                    height: HANDLE,
                    left: corner.includes("w") ? -HANDLE / 2 : undefined,
                    right: corner.includes("e") ? -HANDLE / 2 : undefined,
                    top: corner.includes("n") ? -HANDLE / 2 : undefined,
                    bottom: corner.includes("s") ? -HANDLE / 2 : undefined,
                    cursor:
                      corner === "nw" || corner === "se"
                        ? "nwse-resize"
                        : "nesw-resize",
                    touchAction: "none",
                  }}
                />
              ))}
          </div>
        );
      })}

      {[...spans]
        .sort((left, right) => rectArea(right.bbox) - rectArea(left.bbox))
        .map((span) => {
          const key = spanKey(page, span);
          const selected = selectedKey === key;
          const dragging = drag?.key === key;
          return (
            <div
              key={key}
              onClick={(event) => event.stopPropagation()}
              onPointerDown={(event) => handleSpanPointerDown(event, span, key)}
              className={`group absolute rounded-[2px] border transition-colors before:absolute before:-inset-1.5 before:content-[''] ${
                tool !== "select"
                  ? "pointer-events-none border-transparent"
                  : selected
                    ? "cursor-move border-brand bg-brand/20"
                    : "cursor-move border-brand/40 bg-brand/[0.06] hover:border-brand hover:bg-brand/15"
              }`}
              style={{
                ...rectStyle(span.bbox, zoom),
                transform: dragging
                  ? `translate(${drag.dx * zoom}px, ${drag.dy * zoom}px)`
                  : undefined,
              }}
              title={span.text}
            >
              {tool === "select" && onEditSpan && (
                <button
                  type="button"
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={(event) => {
                    event.stopPropagation();
                    onEditSpan(span, key);
                  }}
                  aria-label="Edit text"
                  title="Edit text"
                  className="absolute -right-2 top-1/2 z-20 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded-full border border-brand/50 bg-panel text-brand shadow-[0_1px_3px_rgba(0,0,0,0.5)] transition-colors hover:bg-brand hover:text-[#05070c]"
                >
                  <Pencil className="h-3 w-3" />
                </button>
              )}
            </div>
          );
        })}

      {eraseRect && (
        <div
          className="pointer-events-none absolute border-2 border-dashed border-brand bg-brand/20"
          style={{
            left: Math.min(eraseRect.x0, eraseRect.x1) * zoom,
            top: Math.min(eraseRect.y0, eraseRect.y1) * zoom,
            width: Math.abs(eraseRect.x1 - eraseRect.x0) * zoom,
            height: Math.abs(eraseRect.y1 - eraseRect.y0) * zoom,
          }}
        />
      )}

      {tool !== "select" && (
        <div className="pointer-events-none absolute inset-0 bg-brand/[0.03]" />
      )}
    </div>
  );
}

