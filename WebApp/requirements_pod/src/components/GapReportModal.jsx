import React, { useState } from "react";
import { applyGapSuggestion } from "../api/client.js";

const SEVERITY_STYLES = {
  high:   { badge: "bg-red-100 text-red-700 border-red-200",      dot: "bg-red-500",   label: "High" },
  medium: { badge: "bg-amber-100 text-amber-700 border-amber-200", dot: "bg-amber-500", label: "Medium" },
  low:    { badge: "bg-blue-100 text-blue-700 border-blue-200",    dot: "bg-blue-400",  label: "Low" },
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
  const assumedFields = report?.assumed_fields || [];
  const unresolvedCount = fieldGaps.filter((g) => !g.resolved).length;
  const highCount = fieldGaps.filter((g) => !g.resolved && g.severity === "high").length;
  const mediumCount = fieldGaps.filter((g) => !g.resolved && g.severity === "medium").length;

  async function handleAccept(gap) {
    if (!gap.suggestion) return;
    setApplying(gap.field);
    setError(null);
    try {
      const updated = await applyGapSuggestion(task.task_id, gap.field, gap.suggestion);
      setReport((prev) => ({
        ...prev,
        field_gaps: prev.field_gaps.map((g) =>
          g.field === gap.field ? { ...g, resolved: true } : g
        ),
      }));
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
      <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50 p-4">
        <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg p-8 text-center">
          <p className="text-gray-500 text-sm">No gap report available for this task yet.</p>
          <p className="text-gray-400 text-xs mt-1">Gap analysis runs automatically after extraction.</p>
          <button onClick={onClose} className="mt-4 px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm hover:bg-gray-200">
            Close
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-mono text-gray-400">{task.task_id}</span>
              {unresolvedCount === 0 ? (
                <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">All gaps resolved</span>
              ) : (
                <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full">
                  {unresolvedCount} gap{unresolvedCount !== 1 ? "s" : ""} remaining
                </span>
              )}
              {assumedFields.length > 0 && (
                <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
                  {assumedFields.length} assumed value{assumedFields.length !== 1 ? "s" : ""}
                </span>
              )}
            </div>
            <h3 className="text-lg font-semibold text-gray-800 mt-0.5">Gap Analysis Report</h3>
            <p className="text-sm text-gray-500 truncate max-w-md" title={task.task_heading}>{task.task_heading}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-2xl leading-none">&times;</button>
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

          {/* All resolved summary */}
          {unresolvedCount === 0 && fieldGaps.length > 0 && (
            <div className="bg-green-50 border border-green-200 rounded-xl px-4 py-3 text-sm text-green-700">
              All gaps have been resolved{assumedFields.length > 0 ? " — review assumed values below before pushing to Jira" : " — this task is ready to push to Jira"}.
            </div>
          )}

          {/* No gaps at all */}
          {fieldGaps.length === 0 && (
            <div className="bg-green-50 border border-green-200 rounded-xl px-4 py-3 text-sm text-green-700">
              No field gaps detected{assumedFields.length > 0 ? " — review assumed values below" : " — this task is complete"}.
            </div>
          )}

          {/* Field Gaps */}
          {fieldGaps.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-sm font-semibold text-gray-700">Field Gaps</h4>
                {fieldGaps.some((g) => !g.resolved && g.can_apply && g.suggestion) && (
                  <button
                    onClick={handleAcceptAll}
                    disabled={applying !== null}
                    className="text-xs px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 transition-colors"
                  >
                    Accept All Suggestions
                  </button>
                )}
              </div>
              <div className="space-y-2">
                {fieldGaps.map((gap) => {
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
                <h4 className="text-sm font-semibold text-gray-700">Assumed Values</h4>
                <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
                  {assumedFields.length} field{assumedFields.length !== 1 ? "s" : ""}
                </span>
              </div>
              <p className="text-xs text-gray-500 mb-3">
                These values were not explicitly stated in the conversation. The AI inferred them from
                context — please verify they are correct before pushing to Jira.
              </p>
              <div className="space-y-2">
                {assumedFields.map((af) => (
                  <div
                    key={af.field}
                    className="rounded-xl border border-blue-200 bg-blue-50 p-3"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="inline-block w-2 h-2 rounded-full flex-shrink-0 bg-blue-400" />
                          <span className="text-xs font-semibold uppercase tracking-wide text-blue-900">
                            {af.field.replace(/_/g, " ")}
                          </span>
                          <span className="text-xs px-1.5 py-0.5 rounded border border-blue-300 bg-blue-100 text-blue-700">
                            Assumed from conversation
                          </span>
                        </div>
                        <p className="text-xs text-blue-700">{af.message}</p>
                        {af.current_value && (
                          <div className="mt-1.5 bg-white bg-opacity-70 rounded-lg px-2.5 py-1.5">
                            <p className="text-xs text-gray-500 mb-0.5 font-medium">Current value:</p>
                            <p className="text-xs text-gray-800 font-medium">{af.current_value}</p>
                          </div>
                        )}
                      </div>
                      <button
                        onClick={() => { onClose(); onEdit && onEdit(task); }}
                        className="flex-shrink-0 text-xs px-3 py-1.5 bg-white border border-blue-300 text-blue-700 rounded-lg hover:bg-blue-50 font-medium transition-colors"
                      >
                        Verify / Edit
                      </button>
                    </div>
                  </div>
                ))}
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
