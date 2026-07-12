import { ReplenishmentRequest } from "@/types";

function formatTimestamp(value?: string | null): string {
  if (!value) return "Pending";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export default function ReplenishmentTimeline({ item }: { item: ReplenishmentRequest }) {
  const steps = [
    {
      label: "Requested",
      person: item.requested_by_name,
      at: item.created_at
    },
    {
      label: "Picking",
      person: item.picking_by_name,
      at: item.picking_at
    },
    {
      label: "Shipped",
      person: item.shipped_by_name,
      at: item.shipped_at
    },
    {
      label: "Received",
      person: item.received_by_name,
      at: item.received_at,
      detail: item.received_device_name ? `Device: ${item.received_device_name}` : undefined
    },
    {
      label: "Completed",
      person: item.completed_by_name,
      at: item.completed_at
    }
  ];

  return (
    <div className="custody-timeline" aria-label="Replenishment responsibility timeline">
      {steps.map((step, index) => {
        const done = Boolean(step.at);
        return (
          <div className={`custody-step${done ? " custody-step--done" : ""}`} key={step.label}>
            <span className="custody-step__marker" aria-hidden="true">{done ? "✓" : index + 1}</span>
            <div>
              <strong>{step.label}</strong>
              <div className="muted">{done ? `${step.person || "Recorded user"} · ${formatTimestamp(step.at)}` : "Pending"}</div>
              {done && step.detail && <div className="muted">{step.detail}</div>}
            </div>
          </div>
        );
      })}
      {item.status === "cancelled" && (
        <div className="notice notice-error" style={{ marginTop: 8 }}>
          Cancelled by {item.cancelled_by_name || "authorized user"}
          {item.cancelled_at ? ` · ${formatTimestamp(item.cancelled_at)}` : ""}
          {item.cancellation_reason ? ` · ${item.cancellation_reason}` : ""}
        </div>
      )}
    </div>
  );
}
