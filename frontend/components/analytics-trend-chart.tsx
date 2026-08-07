"use client";

import { AnalyticsTrendPoint } from "@/types";

const width = 860;
const height = 280;
const padding = { top: 24, right: 28, bottom: 46, left: 48 };

function points(values: number[], maxValue: number): string {
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  return values.map((value, index) => {
    const x = padding.left + (values.length === 1 ? plotWidth / 2 : index * plotWidth / (values.length - 1));
    const y = padding.top + plotHeight - (value / maxValue) * plotHeight;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

export default function AnalyticsTrendChart({ data }: { data: AnalyticsTrendPoint[] }) {
  if (data.length === 0) return <p className="muted">No trend data in this period.</p>;
  const created = data.map((row) => row.created_count);
  const completed = data.map((row) => row.completed_count);
  const maxValue = Math.max(1, ...created, ...completed);
  const plotHeight = height - padding.top - padding.bottom;
  const labelIndexes = Array.from(new Set([0, Math.floor((data.length - 1) / 2), data.length - 1]));
  return (
    <div>
      <div style={{ display: "flex", gap: 18, marginBottom: 8, fontSize: 13 }}>
        <span><span style={{ color: "#2563eb" }}>●</span> Created</span>
        <span><span style={{ color: "#16a34a" }}>●</span> Completed</span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Created and completed work orders over time" style={{ minWidth: 620, width: "100%" }}>
          {[0, 0.5, 1].map((ratio) => {
            const y = padding.top + plotHeight - ratio * plotHeight;
            return <g key={ratio}><line x1={padding.left} x2={width - padding.right} y1={y} y2={y} stroke="#dbe3ef" strokeWidth="1" /><text x={padding.left - 8} y={y + 4} textAnchor="end" fontSize="12" fill="#64748b">{Math.round(maxValue * ratio)}</text></g>;
          })}
          <polyline points={points(created, maxValue)} fill="none" stroke="#2563eb" strokeWidth="3" strokeLinejoin="round" />
          <polyline points={points(completed, maxValue)} fill="none" stroke="#16a34a" strokeWidth="3" strokeLinejoin="round" />
          {labelIndexes.map((index) => {
            const x = padding.left + (data.length === 1 ? (width - padding.left - padding.right) / 2 : index * (width - padding.left - padding.right) / (data.length - 1));
            return <text key={index} x={x} y={height - 16} textAnchor={index === 0 ? "start" : index === data.length - 1 ? "end" : "middle"} fontSize="12" fill="#64748b">{data[index].label}</text>;
          })}
        </svg>
      </div>
    </div>
  );
}
