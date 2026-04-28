import React, { useState } from "react";
import { applyGapSuggestion } from "../api/client.js";

const SEVERITY_STYLES = {
  high:   { badge: "bg-red-100 text-red-700 border-red-200",      dot: "bg-red-500",   label: "High" },
  medium: { badge: "bg-amber-100 text-amber-700 border-amber-200", dot: "bg-amber-500", label: "Medium" },
  low:    { badge: "bg-blue-100 text-blue-700 border-blue-200",    dot: "bg-blue-400",  label: "Low" },
};

const TYPE_BADGE_STYLES = {
  story:   "bg-purple-100 text-purple-700 border-purple-200",
  task:    "bg-blue-100 text-blue-700 border-blue-200",
  bug:     "bg-red-100 text-red-700 border-red-200",
  subtask: "bg-gray-100 text-gray-600 border-gray-200",
};

/**
 * GapReportModal — shows the automated gap analysis for a single task.
 *
 * Props:
 *   task       — TaskOut object (must have task_id, task_heading, gap_report)
 *   onClose    — close handler
 *   onUpdated  — called with updated TaskOut after applying a suggestion
 *   onEdit     — optional: open full Edit modal for this task
 */
export default function GapReportModal({ task, onClose, onUpdated, onEdit }) {
  const rawReport = task.gap_report ? JSON.parse(task.gap_report) : null;
  const [report, setReport] = useState(rawReport);
  const [applying, setApplying] = useState(null);
  const [error, setError] = useState(null);

  const fieldGaps = report?.field_gaps || [];
  const displayFieldGaps = fieldGaps;
  const assumedFields = report?.assumed_fields || [];
  const aiNotes = report?.assumptions || [];          // LLM free-text inferences about requirements
  const unresolvedCount = fieldGaps.filter((g) => !g.resolved).length;
  const highCount = fieldGaps.filter((g) => !g.resolved && g.severity === "high").length;
  const mediumCount = fieldGaps.filter((g) => !g.resolved && g.severity === "medium").length;

  async function handleAccept(gap) {
    if (!gap.suggestion) return;
    setApplying(gap.field);
    setError(null);
    try {
      const updated = await applyGapSuggestion(task.task_id, gap.field, gap.suggestion);
      // Sync modal state from the server's refreshed gap_report (filled field is removed, not just flagged resolved)
      if (updated.gap_report) {
        try { setReport(JSON.parse(updated.gap_report)); } catch { /* keep existing state */ }
      }
      onUpdated(updated);
    } catch (err) {
      setError(`Failed to apply suggestion for ${gap.field}: ${err.message}`);
    } finally {
      setApplying(null);
    }
  }

  async function handleAcceptAll() {
    const pending = fieldGaps.filter((g) => !g.resolved && g.can_apply && g.suggestion);
    for (const gap of pending) {
      await handleAccept(gap);
    }
  }

  if (!report) {
    return (
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
        <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg p-8 text-center border border-indigo-100">
          <div className="w-12 h-12 rounded-2xl bg-indigo-50 flex items-center justify-center mx-auto mb-3">
            <svg className="w-6 h-6 text-indigo-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
          </div>
          <p className="text-gray-600 text-sm font-medium">No gap report available for this task yet.</p>
          <p className="text-gray-400 text-xs mt-1">Gap analysis runs automatically after extraction.</p>
          <button onClick={onClose} className="mt-4 px-4 py-2 bg-indigo-50 text-indigo-700 rounded-lg text-sm hover:bg-indigo-100 font-medium transition-colors">
            Close
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto border border-indigo-100">

        {/* Header */}
        <div className="modal-header-gradient flex items-center justify-between px-6 py-4 rounded-t-2xl">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <span className="text-xs font-mono text-gray-400 bg-gray-100 px-2 py-0.5 rounded-md">{task.task_id}</span>
              {task.task_type && (
                <span className={`text-xs border px-2 py-0.5 rounded-full font-medium capitalize ${TYPE_BADGE_STYLES[task.task_type] || TYPE_BADGE_STYLES.subtask}`}>
                  {task.task_type}
                </span>
              )}
              {unresolvedCount === 0 ? (
                <span className="text-xs bg-emerald-50 text-emerald-700 border border-emerald-200 px-2 py-0.5 rounded-full">All gaps resolved</span>
              ) : (
                <span className="text-xs bg-amber-50 text-amber-700 border border-amber-200 px-2 py-0.5 rounded-full">
                  {unresolvedCount} gap{unresolvedCount !== 1 ? "s" : ""} remaining
                </span>
              )}
              {assumedFields.length > 0 && (
                <span className="text-xs bg-violet-50 text-violet-700 border border-violet-200 px-2 py-0.5 rounded-full">
                  {assumedFields.length} assumption{assumedFields.length !== 1 ? "s" : ""}
                </span>
              )}
              {aiNotes.length > 0 && (
                <span className="text-xs bg-teal-50 text-teal-700 border border-teal-200 px-2 py-0.5 rounded-full">
                  {aiNotes.length} AI note{aiNotes.length !== 1 ? "s" : ""}
                </span>
              )}
            </div>
            <h3 className="text-lg font-bold text-gray-900">Gap Analysis Report</h3>
            <p className="text-sm text-gray-500 truncate max-w-md" title={task.task_heading}>{task.task_heading}</p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 text-2xl leading-none transition-colors w-8 h-8 flex items-center justify-center rounded-lg hover:bg-gray-100 flex-shrink-0"
          >
            &times;
          </button>
        </div>

        <div className="px-6 py-4 space-y-4">

          {/* Gap Summary */}
          {unresolvedCount > 0 && (
            <div className="bg-gray-50 border border-gray-200 rounded-xl px-4 py-3">
              <h4 className="text-sm font-semibold text-gray-700 mb-2">Gap Summary</h4>
              <div className="flex flex-wrap gap-3 text-xs">
                <span className="flex items-center gap-1.5">
                  <span className="inline-block w-2 h-2 rounded-full bg-gray-400" />
                  <span className="text-gray-600">{unresolvedCount} unresolved gap{unresolvedCount !== 1 ? "s" : ""}</span>
                </span>
                {highCount > 0 && (
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block w-2 h-2 rounded-full bg-red-500" />
                    <span className="text-red-700">{highCount} high severity</span>
                  </span>
                )}
                {mediumCount > 0 && (
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block w-2 h-2 rounded-full bg-amber-500" />
                    <span className="text-amber-700">{mediumCount} medium severity</span>
                  </span>
                )}
              </div>
              <p className="text-xs text-gray-500 mt-2">
                {highCount > 0
                  ? "High-severity gaps should be resolved before pushing to Jira."
                  : "No high-severity gaps — safe to push, but review medium gaps."}
              </p>
            </div>
          )}

          {/* AI Analysis Notes — free-text inferences from LLM, always shown when present */}
          {aiNotes.length > 0 && (
            <div className="bg-teal-50 border border-teal-200 rounded-xl px-4 py-3">
              <div className="flex items-center gap-2 mb-2">
                <svg className="w-3.5 h-3.5 text-teal-600 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.347.347a3.75 3.75 0 00-1.097 2.65v.002a.75.75 0 01-.75.75H8.75a.75.75 0 01-.75-.75v-.002a3.75 3.75 0 00-1.097-2.65L6.343 16.34z" />
                </svg>
                <h4 className="text-sm font-semibold text-teal-800">AI Analysis Notes</h4>
                <span className="text-xs bg-teal-100 text-teal-700 px-2 py-0.5 rounded-full">{aiNotes.length}</span>
              </div>
              <p className="text-xs text-teal-700 mb-2">
                The AI inferred the following from context — not explicitly stated in the document.
              </p>
              <ul className="space-y-1">
                {aiNotes.map((note, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-teal-800">
                    <span className="inline-block w-1.5 h-1.5 rounded-full bg-teal-500 mt-1.5 flex-shrink-0" />
                    {note}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* All resolved summary */}
          {unresolvedCount === 0 && displayFieldGaps.length > 0 && (
            <div className="bg-green-50 border border-green-200 rounded-xl px-4 py-3 text-sm text-green-700">
              All gaps have been resolved{assumedFields.length > 0 ? " — review assumed values below before pushing to Jira" : " — this task is ready to push to Jira"}.
            </div>
          )}

          {/* No gaps at all */}
          {displayFieldGaps.length === 0 && (
            <div className="bg-green-50 border border-green-200 rounded-xl px-4 py-3 text-sm text-green-700">
              No field gaps detected{assumedFields.length > 0 ? " — review assumed values below" : " — this task is complete"}.
            </div>
          )}

          {/* Field Gaps */}
          {displayFieldGaps.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-sm font-semibold text-gray-700">Field Gaps</h4>
                {displayFieldGaps.some((g) => !g.resolved && g.can_apply && g.suggestion) && (
                  <button
                    onClick={handleAcceptAll}
                    disabled={applying !== null}
                    className="text-xs px-3 py-1.5 bg-violet-500 text-white rounded-lg hover:bg-violet-600 disabled:opacity-50 transition-colors font-medium"
                  >
                    Accept All Suggestions
                  </button>
                )}
              </div>
              <div className="space-y-2">
                {displayFieldGaps.map((gap) => {
                  const sty = SEVERITY_STYLES[gap.severity] || SEVERITY_STYLES.low;
                  return (
                    <div
                      key={gap.field}
                      className={`rounded-xl border p-3 ${gap.resolved ? "bg-green-50 border-green-200 opacity-70" : sty.badge}`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-0.5">
                            {gap.resolved ? (
                              <span className="text-green-600 text-xs font-bold">✓ Resolved</span>
                            ) : (
                              <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${sty.dot}`} />
                            )}
                            <span className="text-xs font-semibold uppercase tracking-wide">
                              {gap.field.replace(/_/g, " ")}
                            </span>
                            {!gap.resolved && (
                              <span className={`text-xs px-1.5 py-0.5 rounded border ${sty.badge}`}>
                                {sty.label}
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-gray-600">{gap.message}</p>
                          {gap.suggestion && !gap.resolved && (
                            <div className="mt-1.5 bg-white bg-opacity-60 rounded-lg px-2.5 py-1.5">
                              <p className="text-xs text-gray-500 mb-0.5 font-medium">Suggested value:</p>
                              <p className="text-xs text-gray-800 break-words">
                                {gap.field === "acceptance_criteria"
                                  ? (() => {
                                      try {
                                        const items = JSON.parse(gap.suggestion);
                                        return Array.isArray(items)
                                          ? items.map((it, i) => <span key={i} className="block">• {it}</span>)
                                          : gap.suggestion;
                                      } catch {
                                        return gap.suggestion;
                                      }
                                    })()
                                  : gap.suggestion}
                              </p>
                            </div>
                          )}
                        </div>

                        {/* can_apply=true: Accept button auto-patches the field */}
                        {!gap.resolved && gap.can_apply && gap.suggestion && (
                          <button
                            onClick={() => handleAccept(gap)}
                            disabled={applying === gap.field}
                            className="flex-shrink-0 text-xs px-3 py-1.5 bg-white border border-current rounded-lg hover:bg-opacity-80 disabled:opacity-50 font-medium transition-colors"
                          >
                            {applying === gap.field ? "Applying…" : "Accept"}
                          </button>
                        )}
                        {/* can_apply=false: metadata field — must be filled via Edit modal */}
                        {!gap.resolved && !gap.can_apply && (
                          <button
                            onClick={() => { onClose(); onEdit && onEdit(task); }}
                            className="flex-shrink-0 text-xs px-3 py-1.5 bg-white border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 font-medium transition-colors"
                          >
                            Fill via Edit
                          </button>
                        )}
                        {!gap.resolved && gap.can_apply && !gap.suggestion && (
                          <span className="flex-shrink-0 text-xs text-gray-400 italic">No suggestion</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Assumed Values — present but inferred by the LLM, not explicitly stated */}
          {assumedFields.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <h4 className="text-sm font-semibold text-gray-700">Assumptions</h4>
                <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
                  {assumedFields.length} field{assumedFields.length !== 1 ? "s" : ""}
                </span>
              </div>
              <p className="text-xs text-gray-500 mb-3">
                The AI assumed these mandatory field values from context. Please verify before pushing to Jira.
              </p>
              <div className="space-y-2">
                {assumedFields.map((af) => {
                  const hasValue = !!af.current_value;
                  const cardCls  = hasValue
                    ? "rounded-xl border border-blue-200 bg-blue-50 p-3"
                    : "rounded-xl border border-gray-200 bg-gray-50 p-3";
                  const dotCls   = hasValue ? "bg-blue-400" : "bg-gray-400";
                  const labelCls = hasValue
                    ? "text-xs px-1.5 py-0.5 rounded border border-blue-300 bg-blue-100 text-blue-700"
                    : "text-xs px-1.5 py-0.5 rounded border border-gray-300 bg-gray-100 text-gray-600";
                  const labelTxt = hasValue ? "AI estimated" : "AI could not determine";
                  const msgCls   = hasValue ? "text-xs text-blue-700" : "text-xs text-gray-500";
                  return (
                    <div key={af.field} className={cardCls}>
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-0.5">
                            <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${dotCls}`} />
                            <span className={`text-xs font-semibold uppercase tracking-wide ${hasValue ? "text-blue-900" : "text-gray-700"}`}>
                              {af.field.replace(/_/g, " ")}
                            </span>
                            <span className={labelCls}>{labelTxt}</span>
                          </div>
                          <p className={msgCls}>{af.message}</p>
                          {hasValue && (
                            <div className="mt-1.5 bg-white bg-opacity-70 rounded-lg px-2.5 py-1.5">
                              <p className="text-xs text-gray-500 mb-0.5 font-medium">Current value:</p>
                              <p className="text-xs text-gray-800 font-medium">{af.current_value}</p>
                            </div>
                          )}
                        </div>
                        <button
                          onClick={() => { onClose(); onEdit && onEdit(task); }}
                          className={`flex-shrink-0 text-xs px-3 py-1.5 bg-white rounded-lg font-medium transition-colors ${hasValue ? "border border-blue-300 text-blue-700 hover:bg-blue-50" : "border border-gray-300 text-gray-600 hover:bg-gray-100"}`}
                        >
                          Verify / Edit
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-xl text-sm">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200 flex justify-end">
          <button
            onClick={onClose}
            className="px-5 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm hover:bg-gray-200 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
