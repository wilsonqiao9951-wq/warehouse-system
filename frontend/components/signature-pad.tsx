"use client";

import { PointerEvent, useEffect, useRef, useState } from "react";

interface SignaturePadProps {
  disabled?: boolean;
  onChange: (dataUrl: string) => void;
}

export function SignaturePad({ disabled = false, onChange }: SignaturePadProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawingRef = useRef(false);
  const [hasSignature, setHasSignature] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ratio = Math.max(window.devicePixelRatio || 1, 1);
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    const context = canvas.getContext("2d");
    if (!context) return;
    context.scale(ratio, ratio);
    context.lineWidth = 2.5;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.strokeStyle = "#0f172a";
  }, []);

  const point = (event: PointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };

  const start = (event: PointerEvent<HTMLCanvasElement>) => {
    if (disabled) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const context = event.currentTarget.getContext("2d");
    if (!context) return;
    const p = point(event);
    context.beginPath();
    context.moveTo(p.x, p.y);
    drawingRef.current = true;
  };

  const draw = (event: PointerEvent<HTMLCanvasElement>) => {
    if (!drawingRef.current || disabled) return;
    const context = event.currentTarget.getContext("2d");
    if (!context) return;
    const p = point(event);
    context.lineTo(p.x, p.y);
    context.stroke();
  };

  const finish = (event: PointerEvent<HTMLCanvasElement>) => {
    if (!drawingRef.current) return;
    drawingRef.current = false;
    const dataUrl = event.currentTarget.toDataURL("image/png");
    setHasSignature(true);
    onChange(dataUrl);
  };

  const clear = () => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    context.clearRect(0, 0, canvas.width, canvas.height);
    setHasSignature(false);
    onChange("");
  };

  return (
    <div>
      <canvas
        ref={canvasRef}
        aria-label="Customer signature pad"
        onPointerDown={start}
        onPointerMove={draw}
        onPointerUp={finish}
        onPointerCancel={finish}
        style={{
          width: "100%",
          height: 180,
          display: "block",
          border: "1px solid #cbd5e1",
          borderRadius: 10,
          background: disabled ? "#f1f5f9" : "#fff",
          touchAction: "none"
        }}
      />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 8 }}>
        <span className="muted">{hasSignature ? "Signature captured" : "Sign inside the box"}</span>
        <button type="button" onClick={clear} disabled={disabled || !hasSignature}>Clear signature</button>
      </div>
    </div>
  );
}
