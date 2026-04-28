import { SC, RunStatus } from "../constants";
import { fmtDuration, fmtTime } from "../utils";

interface Props {
  status: RunStatus;
  duration?: number | null;
  completedAt?: string | null;
  small?: boolean;
}

export function StatusBadge({ status, duration, completedAt, small }: Props) {
  const fs = small ? 9 : 10;
  return (
    <div style={{ display:"flex", flexDirection:"column", alignItems:"flex-end", gap:2 }}>
      <span style={{ fontSize:fs, fontWeight:700, background:SC.bg[status], color:SC.color[status], borderRadius:10, padding:"2px 7px", border:`1px solid ${SC.bdr[status]}` }}>
        {SC.icon[status]} {SC.label[status]}
      </span>
      {status === "done" && duration != null && <span style={{ fontSize:8, color:"#64748b" }}>⏱ {fmtDuration(duration)}</span>}
      {status === "done" && completedAt && <span style={{ fontSize:8, color:"#94a3b8" }}>{fmtTime(completedAt)}</span>}
    </div>
  );
}
