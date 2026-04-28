import React, { useState, useEffect, useCallback, useRef } from "react";
import { listTasks, updateTask, deleteTask, exportTasks, pushToJira, pushToJiraLinked, getFileCoverageGaps, getGapProgress } from "../api/client.js";
import TaskCard from "./TaskCard.jsx";
import GapReportModal from "./GapReportModal.jsx";

const TYPE_COLORS = {
  bug:     "bg-red-100 text-red-700",
  story:   "bg-purple-100 text-purple-700",
  task:    "bg-blue-100 text-blue-700",
  subtask: "bg-gray-100 text-gray-600",
};

const STATUS_COLORS = {
  extracted: "bg-yellow-50 text-yellow-700",
  modified:  "bg-orange-50 text-orange-700",
  pushed:    "bg-green-50 text-green-700",
  deleted:   "bg-gray-100 text-gray-400",
};

const PRIORITY_COLORS = {
  critical: "bg-red-100 text-red-700",
  high:     "bg-orange-100 text-orange-700",
  medium:   "bg-yellow-100 text-yellow-700",
  low:      "bg-green-100 text-green-600",
};

function Badge({ value, colorMap }) {
  if (!value) return <span className="text-gray-300 text-xs">—</span>;
  const cls = colorMap[value] || "bg-gray-100 text-gray-600";
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}>
      {value}
    </span>
  );
}

const SORT_KEYS = ["task_id", "task_heading", "task_type", "priority", "story_points", "user_name", "status", "created_at", "confidence_score"];

function confidenceColor(score) {
  if (score == null) return null;
  if (score >= 0.9) return { pill: "bg-green-100 text-green-700", dot: "bg-green-400" };
  if (score >= 0.7) return { pill: "bg-blue-100 text-blue-700",  dot: "bg-blue-400"  };
  if (score >= 0.4) return { pill: "bg-amber-100 text-amber-700", dot: "bg-amber-400" };
  return              { pill: "bg-red-100 text-red-700",   dot: "bg-red-400"   };
}

// Fields checked in the gap analysis — content fields that LLM may leave empty
const GAP_FIELDS = [
  {
    key: "description",
    label: "Description",
    check: (v) => v && v.trim().length > 0,
  },
  {
    key: "acceptance_criteria",
    label: "Acceptance Criteria",
    check: (v) => {
      if (!v) return false;
      try { const p = JSON.parse(v); return Array.isArray(p) && p.length > 0; }
      catch { return v.trim().length > 0; }
    },
  },
  {
    key: "story_points",
    label: "Story Points",
    check: (v) => v != null && v !== "",
  },
];

export default function TaskTable({ selectedTasks, onSelectionChange, currentFileIds = [] }) {
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [sortKey, setSortKey] = useState("created_at");
  const [sortDir, setSortDir] = useState("desc");
  const [editTask, setEditTask] = useState(null);
  const [exportFormat, setExportFormat] = useState("json");
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkStatus, setBulkStatus] = useState(null);
  const [inlineEdit, setInlineEdit] = useState({});
  const [gapModal, setGapModal] = useState(null);
  const [perTaskGapModal, setPerTaskGapModal] = useState(null);
  const [coverageGaps, setCoverageGaps] = useState([]);
  const [gapLoadingFileIds, setGapLoadingFileIds] = useState(new Set());
  const gapPollRef = useRef(null);

  const loadTasks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listTasks();
      setTasks(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  // Load coverage gaps for the current file when currentFileIds changes
  useEffect(() => {
    const fileId = currentFileIds[0];
    if (!fileId) { setCoverageGaps([]); return; }
    getFileCoverageGaps(fileId)
      .then((data) => setCoverageGaps(data.gaps || []))
      .catch(() => setCoverageGaps([]));
  }, [currentFileIds]);

  // Poll gap analysis progress for files that have story tasks without gap_report
  useEffect(() => {
    const pendingFileIds = [
      ...new Set(
        tasks
          .filter((t) => t.task_type === "story" && !t.gap_report)
          .map((t) => t.source_file_id)
          .filter(Boolean)
      ),
    ];

    // Stop any existing poll before deciding what to do
    if (gapPollRef.current) {
      clearInterval(gapPollRef.current);
      gapPollRef.current = null;
    }

    if (pendingFileIds.length === 0) {
      setGapLoadingFileIds(new Set());
      return;
    }

    const poll = async () => {
      const running = new Set();
      let anyDone = false;

      for (const fid of pendingFileIds) {
        try {
          const prog = await getGapProgress(fid);
          if (prog.status === "pending" || prog.status === "running") {
            running.add(fid);
          } else if (prog.status === "done") {
            anyDone = true;
          }
          // "idle" or "error" → not loading, not done → leave as-is
        } catch {
          // ignore network errors during polling
        }
      }

      setGapLoadingFileIds(new Set(running));

      if (anyDone) {
        // At least one file finished — reload tasks (gap_report will now be set)
        if (gapPollRef.current) {
          clearInterval(gapPollRef.current);
          gapPollRef.current = null;
        }
        loadTasks();
      }
    };

    poll(); // immediate first check
    gapPollRef.current = setInterval(poll, 3000);

    return () => {
      if (gapPollRef.current) {
        clearInterval(gapPollRef.current);
        gapPollRef.current = null;
      }
    };
  }, [tasks, loadTasks]);

  // Filter to current document's tasks when fileIds are set
  const filteredTasks = currentFileIds.length > 0
    ? tasks.filter((t) => currentFileIds.includes(t.source_file_id))
    : tasks;

  function toggleSelect(taskId) {
    const updated = selectedTasks.includes(taskId)
      ? selectedTasks.filter((id) => id !== taskId)
      : [...selectedTasks, taskId];
    onSelectionChange(updated);
  }

  function toggleSelectAll() {
    const allFilteredIds = filteredTasks.map((t) => t.task_id);
    const allSelected = allFilteredIds.every((id) => selectedTasks.includes(id)) && allFilteredIds.length > 0;
    if (allSelected) {
      onSelectionChange(selectedTasks.filter((id) => !allFilteredIds.includes(id)));
    } else {
      onSelectionChange([...new Set([...selectedTasks, ...allFilteredIds])]);
    }
  }

  function handleSort(key) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  const sortedTasks = [...filteredTasks].sort((a, b) => {
    const av = a[sortKey] ?? "";
    const bv = b[sortKey] ?? "";
    if (sortKey === "story_points" || sortKey === "confidence_score") {
      const an = parseFloat(av) || 0;
      const bn = parseFloat(bv) || 0;
      return sortDir === "asc" ? an - bn : bn - an;
    }
    const cmp = String(av).localeCompare(String(bv));
    return sortDir === "asc" ? cmp : -cmp;
  });

  async function handleExport() {
    if (selectedTasks.length === 0) return;
    setBulkLoading(true);
    try {
      const blob = await exportTasks(selectedTasks, exportFormat);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const now = new Date();
      const pad = (n) => String(n).padStart(2, "0");
      const ts = `${String(now.getFullYear()).slice(-2)}${pad(now.getMonth() + 1)}${pad(now.getDate())}${pad(now.getHours())}`;
      a.download = `tasks_${ts}.${exportFormat}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setBulkStatus(`Export failed: ${err.message}`);
    } finally {
      setBulkLoading(false);
    }
  }

  function handleJiraPush() {
    if (selectedTasks.length === 0) return;
    const selectedTaskObjs = tasks.filter((t) => selectedTasks.includes(t.task_id));
    setGapModal({ tasks: selectedTaskObjs });
  }

  // Called when a task is edited inside the gap modal
  function onGapTaskUpdated(updated) {
    setTasks((prev) => prev.map((t) => (t.task_id === updated.task_id ? updated : t)));
    setGapModal((m) => m ? { ...m, tasks: m.tasks.map((t) => t.task_id === updated.task_id ? updated : t) } : m);
  }

  async function executeJiraPush(taskIds) {
    setBulkLoading(true);
    setBulkStatus(null);
    setGapModal(null);
    try {
      const result = await pushToJira(taskIds);
      const ok = result.results.filter((r) => r.success).length;
      const fail = result.results.filter((r) => !r.success).length;
      const created = result.results.filter((r) => r.success && r.action === "created").length;
      const updated = result.results.filter((r) => r.success && r.action === "updated").length;
      let statusMsg = `Jira push: ${ok} succeeded, ${fail} failed.`;
      if (created > 0) statusMsg += ` (${created} created`;
      if (updated > 0) statusMsg += created > 0 ? `, ${updated} updated)` : ` (${updated} updated)`;
      else if (created > 0) statusMsg += ")";
      setBulkStatus(statusMsg);
      await loadTasks();
    } catch (err) {
      setBulkStatus(`Jira push failed: ${err.message}`);
    } finally {
      setBulkLoading(false);
    }
  }

  async function executeJiraPushLinked(storyTaskId, taskIds) {
    setBulkLoading(true);
    setBulkStatus(null);
    setGapModal(null);
    try {
      const result = await pushToJiraLinked(storyTaskId, taskIds);
      const storyResult = result.results.find((r) => r.role === "story");
      const taskResults = result.results.filter((r) => r.role === "task");
      const ok = taskResults.filter((r) => r.success).length;
      const fail = taskResults.filter((r) => !r.success).length;
      const linked = taskResults.filter((r) => r.success && r.linked_to).length;
      const warnings = taskResults.filter((r) => r.link_warning).length;
      let statusMsg = `Jira push: story ${storyResult?.jira_id || "—"}, ${ok} task(s) pushed`;
      if (linked > 0) statusMsg += `, ${linked} linked`;
      if (fail > 0) statusMsg += `, ${fail} failed`;
      if (warnings > 0) statusMsg += ` (${warnings} link warning(s))`;
      statusMsg += ".";
      setBulkStatus(statusMsg);
      await loadTasks();
    } catch (err) {
      setBulkStatus(`Jira linked push failed: ${err.message}`);
    } finally {
      setBulkLoading(false);
    }
  }

  function handleJiraPushLinked() {
    const selectedTaskObjs = tasks.filter((t) => selectedTasks.includes(t.task_id));
    const story = selectedTaskObjs.find((t) => t.task_type === "story");
    const taskIds = selectedTaskObjs.filter((t) => t.task_type !== "story").map((t) => t.task_id);
    if (!story || taskIds.length === 0) return;
    if (!window.confirm(
      `Push story "${story.task_heading}" and ${taskIds.length} task(s) to Jira, then link them to the story?`
    )) return;
    executeJiraPushLinked(story.task_id, taskIds);
  }

  async function handleBulkDelete() {
    if (selectedTasks.length === 0) return;
    if (!window.confirm(`Delete ${selectedTasks.length} selected task(s)?`)) return;
    setBulkLoading(true);
    setBulkStatus(null);
    let ok = 0;
    let fail = 0;
    for (const id of selectedTasks) {
      try {
        await deleteTask(id);
        ok++;
      } catch {
        fail++;
      }
    }
    setBulkStatus(`Deleted: ${ok} succeeded${fail ? `, ${fail} failed` : ""}.`);
    onSelectionChange([]);
    await loadTasks();
    setBulkLoading(false);
  }

  function startInlineEdit(taskId, field, value) {
    setInlineEdit({ taskId, field, value });
  }

  function cancelInlineEdit() {
    setInlineEdit({});
  }

  async function commitInlineEdit(task) {
    const { taskId, field, value } = inlineEdit;
    if (!taskId || !field) return;
    try {
      const updated = await updateTask(taskId, { [field]: value });
      setTasks((prev) => prev.map((t) => (t.task_id === taskId ? updated : t)));
    } catch (err) {
      setBulkStatus(`Update failed: ${err.message}`);
    } finally {
      setInlineEdit({});
    }
  }

  async function handleInlineDelete(taskId) {
    if (!window.confirm(`Soft-delete task ${taskId}?`)) return;
    try {
      await deleteTask(taskId);
      setTasks((prev) => prev.filter((t) => t.task_id !== taskId));
      onSelectionChange(selectedTasks.filter((id) => id !== taskId));
    } catch (err) {
      setBulkStatus(`Delete failed: ${err.message}`);
    }
  }

  function onTaskUpdated(updated) {
    setTasks((prev) => prev.map((t) => (t.task_id === updated.task_id ? updated : t)));
  }

  function onPerTaskGapUpdated(updated) {
    setTasks((prev) => prev.map((t) => (t.task_id === updated.task_id ? updated : t)));
    setPerTaskGapModal((prev) => (prev?.task_id === updated.task_id ? updated : prev));
  }

  function onTaskDeleted(deleted) {
    setTasks((prev) => prev.filter((t) => t.task_id !== deleted.task_id));
    onSelectionChange(selectedTasks.filter((id) => id !== deleted.task_id));
  }

  if (loading) {
    return <div className="text-gray-400 py-10 text-center">Loading tasks...</div>;
  }
  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
        Error: {error}
      </div>
    );
  }

  const allFilteredSelected =
    filteredTasks.length > 0 && filteredTasks.every((t) => selectedTasks.includes(t.task_id));

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold text-gray-800">
          Tasks ({filteredTasks.length}{currentFileIds.length > 0 && tasks.length !== filteredTasks.length ? ` of ${tasks.length} total` : ""})
        </h2>
        <button onClick={loadTasks} className="text-sm text-blue-600 hover:underline">
          Refresh
        </button>
      </div>

      {/* Coverage Gaps Banner */}
      {coverageGaps.length > 0 && (
        <CoverageGapsBanner
          gaps={coverageGaps}
          source={filteredTasks[0]?.task_source || ""}
        />
      )}

      {/* Bulk toolbar */}
      {selectedTasks.length > 0 && (() => {
        const selectedTaskObjs = tasks.filter((t) => selectedTasks.includes(t.task_id));
        const selectedStories = selectedTaskObjs.filter((t) => t.task_type === "story");
        const selectedNonStories = selectedTaskObjs.filter((t) => t.task_type !== "story");
        const canLinkToStory = selectedStories.length === 1 && selectedNonStories.length >= 1;
        return (
          <div className="mb-4 bg-blue-50 border border-blue-200 rounded-xl px-4 py-3 flex flex-wrap items-center gap-3">
            <span className="text-sm font-medium text-blue-800">
              {selectedTasks.length} selected
              {canLinkToStory && (
                <span className="ml-2 text-xs font-normal text-purple-600">
                  (1 story + {selectedNonStories.length} task{selectedNonStories.length > 1 ? "s" : ""})
                </span>
              )}
            </span>
            <select
              value={exportFormat}
              onChange={(e) => setExportFormat(e.target.value)}
              className="text-sm border border-blue-300 rounded px-2 py-1 bg-white"
            >
              <option value="json">JSON</option>
              <option value="csv">CSV</option>
              <option value="md">Markdown</option>
            </select>
            <button
              onClick={handleExport}
              disabled={bulkLoading}
              className="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              Download
            </button>
            <button
              onClick={handleJiraPush}
              disabled={bulkLoading}
              className="text-sm px-3 py-1 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
            >
              Push to Jira
            </button>
            {canLinkToStory && (
              <button
                onClick={handleJiraPushLinked}
                disabled={bulkLoading}
                className="text-sm px-3 py-1 bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-50"
                title={`Push tasks and link them to story ${selectedStories[0].jira_id || selectedStories[0].task_id}`}
              >
                Push & Link to Story
              </button>
            )}
            <button
              onClick={handleBulkDelete}
              disabled={bulkLoading}
              className="text-sm px-3 py-1 bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50"
            >
              Delete Selected
            </button>
            <button
              onClick={() => onSelectionChange([])}
              className="text-sm text-blue-600 hover:underline ml-auto"
            >
              Clear selection
            </button>
          </div>
        );
      })()}

      {bulkStatus && (
        <div className="mb-3 bg-gray-50 border border-gray-200 text-gray-700 px-4 py-2 rounded-lg text-sm">
          {bulkStatus}
        </div>
      )}

      {/* Table */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-3 text-left">
                <input
                  type="checkbox"
                  checked={allFilteredSelected}
                  onChange={toggleSelectAll}
                  className="rounded"
                />
              </th>
              {[
                { key: "task_id",          label: "ID" },
                { key: "task_heading",     label: "Summary" },
                { key: "task_type",        label: "Type" },
                { key: "priority",         label: "Priority" },
                { key: "story_points",     label: "Pts" },
                { key: "user_name",        label: "Assigned To" },
                { key: "status",           label: "Status" },
                { key: "created_at",       label: "Created" },
                { key: "confidence_score", label: "Confidence" },
              ].map(({ key, label }) => (
                <th
                  key={key}
                  onClick={() => handleSort(key)}
                  className="px-3 py-3 text-left font-medium text-gray-500 cursor-pointer hover:text-gray-700 select-none whitespace-nowrap"
                >
                  {label}
                  {sortKey === key && (
                    <span className="ml-1">{sortDir === "asc" ? "▲" : "▼"}</span>
                  )}
                </th>
              ))}
              <th className="px-3 py-3 text-left font-medium text-gray-500">Jira</th>
              <th className="px-3 py-3 text-left font-medium text-gray-500">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {sortedTasks.length === 0 && (
              <tr>
                <td colSpan={12} className="px-4 py-8 text-center text-gray-400">
                  {"No tasks found. Upload a document and extract tasks to get started."}
                </td>
              </tr>
            )}
            {sortedTasks.map((task) => (
              <tr
                key={task.task_id}
                className={`hover:bg-gray-50 ${selectedTasks.includes(task.task_id) ? "bg-blue-50" : ""}`}
              >
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    checked={selectedTasks.includes(task.task_id)}
                    onChange={() => toggleSelect(task.task_id)}
                    className="rounded"
                  />
                </td>

                {/* task_id */}
                <td className="px-3 py-2 font-mono text-xs text-gray-500 whitespace-nowrap">
                  {task.task_id}
                </td>

                {/* heading — inline editable */}
                <td className="px-3 py-2 max-w-xs">
                  {inlineEdit.taskId === task.task_id && inlineEdit.field === "task_heading" ? (
                    <input
                      autoFocus
                      value={inlineEdit.value}
                      onChange={(e) => setInlineEdit((p) => ({ ...p, value: e.target.value }))}
                      onBlur={() => commitInlineEdit(task)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") commitInlineEdit(task);
                        if (e.key === "Escape") cancelInlineEdit();
                      }}
                      className="border border-blue-300 rounded px-2 py-1 text-sm w-full focus:outline-none"
                    />
                  ) : (
                    <span
                      title={task.task_heading}
                      onClick={() => startInlineEdit(task.task_id, "task_heading", task.task_heading)}
                      className="cursor-pointer hover:text-blue-700 block truncate"
                    >
                      {task.task_heading}
                    </span>
                  )}
                </td>

                {/* task_type — inline select */}
                <td className="px-3 py-2">
                  {inlineEdit.taskId === task.task_id && inlineEdit.field === "task_type" ? (
                    <select
                      autoFocus
                      value={inlineEdit.value}
                      onChange={(e) => setInlineEdit((p) => ({ ...p, value: e.target.value }))}
                      onBlur={() => commitInlineEdit(task)}
                      className="border border-blue-300 rounded px-1 py-1 text-sm focus:outline-none"
                    >
                      {["bug", "story", "task", "subtask"].map((t) => (
                        <option key={t} value={t}>{t}</option>
                      ))}
                    </select>
                  ) : (
                    <span
                      onClick={() => startInlineEdit(task.task_id, "task_type", task.task_type)}
                      className="cursor-pointer"
                    >
                      <Badge value={task.task_type} colorMap={TYPE_COLORS} />
                    </span>
                  )}
                </td>

                {/* priority — inline select */}
                <td className="px-3 py-2">
                  {inlineEdit.taskId === task.task_id && inlineEdit.field === "priority" ? (
                    <select
                      autoFocus
                      value={inlineEdit.value}
                      onChange={(e) => setInlineEdit((p) => ({ ...p, value: e.target.value }))}
                      onBlur={() => commitInlineEdit(task)}
                      className="border border-blue-300 rounded px-1 py-1 text-sm focus:outline-none"
                    >
                      {["critical", "high", "medium", "low"].map((p) => (
                        <option key={p} value={p}>{p}</option>
                      ))}
                    </select>
                  ) : (
                    <span
                      onClick={() => startInlineEdit(task.task_id, "priority", task.priority || "medium")}
                      className="cursor-pointer"
                    >
                      <Badge value={task.priority} colorMap={PRIORITY_COLORS} />
                    </span>
                  )}
                </td>

                {/* story_points */}
                <td className="px-3 py-2 text-center text-gray-600 text-xs">
                  {inlineEdit.taskId === task.task_id && inlineEdit.field === "story_points" ? (
                    <input
                      autoFocus
                      type="number"
                      value={inlineEdit.value}
                      onChange={(e) => setInlineEdit((p) => ({ ...p, value: e.target.value }))}
                      onBlur={() => commitInlineEdit(task)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") commitInlineEdit(task);
                        if (e.key === "Escape") cancelInlineEdit();
                      }}
                      className="border border-blue-300 rounded px-1 py-1 text-sm w-14 focus:outline-none"
                    />
                  ) : (
                    <span
                      onClick={() => startInlineEdit(task.task_id, "story_points", task.story_points ?? "")}
                      className="cursor-pointer hover:text-blue-700"
                    >
                      {task.story_points ?? <span className="text-gray-300">—</span>}
                    </span>
                  )}
                </td>

                {/* user_name — inline editable */}
                <td className="px-3 py-2">
                  {inlineEdit.taskId === task.task_id && inlineEdit.field === "user_name" ? (
                    <input
                      autoFocus
                      value={inlineEdit.value}
                      onChange={(e) => setInlineEdit((p) => ({ ...p, value: e.target.value }))}
                      onBlur={() => commitInlineEdit(task)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") commitInlineEdit(task);
                        if (e.key === "Escape") cancelInlineEdit();
                      }}
                      className="border border-blue-300 rounded px-2 py-1 text-sm w-28 focus:outline-none"
                    />
                  ) : (
                    <span
                      onClick={() => startInlineEdit(task.task_id, "user_name", task.user_name || "")}
                      className="cursor-pointer hover:text-blue-700 text-gray-600"
                    >
                      {task.user_name || <span className="text-gray-300 italic">unassigned</span>}
                    </span>
                  )}
                </td>

                {/* status — inline select */}
                <td className="px-3 py-2">
                  {inlineEdit.taskId === task.task_id && inlineEdit.field === "status" ? (
                    <select
                      autoFocus
                      value={inlineEdit.value}
                      onChange={(e) => setInlineEdit((p) => ({ ...p, value: e.target.value }))}
                      onBlur={() => commitInlineEdit(task)}
                      className="border border-blue-300 rounded px-1 py-1 text-sm focus:outline-none"
                    >
                      {["extracted", "modified", "pushed", "deleted"].map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  ) : (
                    <span
                      onClick={() => startInlineEdit(task.task_id, "status", task.status)}
                      className="cursor-pointer"
                    >
                      <Badge value={task.status} colorMap={STATUS_COLORS} />
                    </span>
                  )}
                </td>

                {/* created_at */}
                <td className="px-3 py-2 text-gray-400 text-xs whitespace-nowrap">
                  {new Date(task.created_at).toLocaleDateString()}
                </td>

                {/* confidence_score */}
                <td className="px-3 py-2 text-center">
                  {task.confidence_score != null ? (() => {
                    const c = confidenceColor(task.confidence_score);
                    return (
                      <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${c.pill}`}>
                        {Math.round(task.confidence_score * 100)}%
                      </span>
                    );
                  })() : (
                    <span className="text-gray-300 text-xs">—</span>
                  )}
                </td>

                {/* jira link */}
                <td className="px-3 py-2">
                  {task.jira_id ? (
                    <a
                      href={task.jira_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:underline text-xs font-mono"
                    >
                      {task.jira_id}
                    </a>
                  ) : (
                    <span className="text-gray-300 text-xs">—</span>
                  )}
                </td>

                {/* actions */}
                <td className="px-3 py-2">
                  <div className="flex gap-1.5 items-center">
                    <button
                      onClick={() => setEditTask(task)}
                      className="text-xs px-2 py-1 bg-gray-100 hover:bg-gray-200 rounded text-gray-700 transition-colors"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleInlineDelete(task.task_id)}
                      className="text-xs px-2 py-1 bg-red-50 hover:bg-red-100 rounded text-red-600 transition-colors"
                    >
                      Del
                    </button>
                    <GapBadgeButton
                      task={task}
                      isLoading={gapLoadingFileIds.has(task.source_file_id)}
                      onClick={() => setPerTaskGapModal(task)}
                    />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Confidence Score Legend */}
      <div className="mt-4 bg-gray-50 border border-gray-200 rounded-xl px-4 py-3">
        <p className="text-xs font-semibold text-gray-500 mb-2">Confidence Score Legend</p>
        <div className="flex flex-wrap gap-x-6 gap-y-1.5">
          {[
            { dot: "bg-green-400", range: "90% – 100%", label: "High",     desc: "AI is highly confident — safe to use as-is" },
            { dot: "bg-blue-400",  range: "70% – 89%",  label: "Good",     desc: "Likely accurate, spot-check recommended" },
            { dot: "bg-amber-400", range: "40% – 69%",  label: "Moderate", desc: "Review before accepting" },
            { dot: "bg-red-400",   range: "0% – 39%",   label: "Low",      desc: "Needs manual review" },
          ].map(({ dot, range, label, desc }) => (
            <span key={label} className="flex items-center gap-1.5 text-xs text-gray-600">
              <span className={`inline-block w-2.5 h-2.5 rounded-full flex-shrink-0 ${dot}`} />
              <span className="font-medium">{range}</span>
              <span className="text-gray-400">·</span>
              <span className="font-semibold">{label}</span>
              <span className="text-gray-400 hidden sm:inline">— {desc}</span>
            </span>
          ))}
        </div>
      </div>

      {/* Task edit modal */}
      {editTask && (
        <TaskCard
          task={editTask}
          onClose={() => setEditTask(null)}
          onUpdated={onTaskUpdated}
          onDeleted={onTaskDeleted}
        />
      )}

      {/* Pre-push Gap Analysis Modal (bulk) */}
      {gapModal && (
        <GapAnalysisModal
          tasks={gapModal.tasks}
          onTaskUpdated={onGapTaskUpdated}
          onPush={(ids) => executeJiraPush(ids)}
          onClose={() => setGapModal(null)}
        />
      )}

      {/* Per-task Gap Report Modal */}
      {perTaskGapModal && (
        <GapReportModal
          task={perTaskGapModal}
          onClose={() => setPerTaskGapModal(null)}
          onUpdated={onPerTaskGapUpdated}
          onEdit={(t) => { setPerTaskGapModal(null); setEditTask(t); }}
        />
      )}

    </div>
  );
}

// ── Gap Badge Button (per-task Actions column) ────────────────────────────────

function GapBadgeButton({ task, isLoading, onClick }) {
  // Story with no gap_report yet and gap analysis is running → spinner
  if (!task.gap_report && isLoading && task.task_type === "story") {
    return (
      <span
        title="Gap analysis in progress…"
        className="text-xs px-2 py-1 bg-blue-50 rounded text-blue-500 flex items-center gap-1 cursor-default"
      >
        <svg
          className="animate-spin w-3 h-3 flex-shrink-0"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
        >
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
        </svg>
        Gaps
      </span>
    );
  }

  if (!task.gap_report) return null;

  let report;
  try { report = JSON.parse(task.gap_report); } catch { return null; }

  const gaps = report.field_gaps || [];
  const unresolved = gaps.filter((g) => !g.resolved).length;

  if (unresolved === 0) {
    return (
      <button
        onClick={onClick}
        title="All gaps resolved"
        className="text-xs px-2 py-1 bg-green-50 hover:bg-green-100 rounded text-green-700 transition-colors flex items-center gap-1"
      >
        <span className="inline-block w-2 h-2 rounded-full bg-green-500" />
        Gaps
      </button>
    );
  }

  const hasHigh = gaps.some((g) => !g.resolved && g.severity === "high");
  const color = hasHigh
    ? "bg-red-50 hover:bg-red-100 text-red-700"
    : "bg-amber-50 hover:bg-amber-100 text-amber-700";

  return (
    <button
      onClick={onClick}
      title={`${unresolved} unresolved gap${unresolved !== 1 ? "s" : ""}`}
      className={`text-xs px-2 py-1 rounded transition-colors flex items-center gap-1 ${color}`}
    >
      <span className="font-bold">{unresolved}</span>
      Gaps
    </button>
  );
}


// ── Coverage Gaps Banner ──────────────────────────────────────────────────────

function CoverageGapsBanner({ gaps, source }) {
  const [open, setOpen] = useState(true);
  if (!gaps || gaps.length === 0) return null;

  const highCount = gaps.filter((g) => g.severity === "high").length;

  return (
    <div className="mb-4 bg-orange-50 border border-orange-200 rounded-xl overflow-hidden">
      <button
        className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-orange-100 transition-colors"
        onClick={() => setOpen((o) => !o)}
      >
        <div className="flex items-center gap-2">
          <span className="text-orange-500 font-bold text-base">⚠</span>
          <span className="text-sm font-semibold text-orange-800">
            Coverage Gaps — {source}
          </span>
          <span className="text-xs bg-orange-200 text-orange-800 px-2 py-0.5 rounded-full">
            {gaps.length} gap{gaps.length !== 1 ? "s" : ""}
            {highCount > 0 && `, ${highCount} high severity`}
          </span>
        </div>
        <span className="text-orange-400 text-sm">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-2">
          <p className="text-xs text-orange-600 mb-3">
            These topics were mentioned in the transcript but were not captured as tasks.
            Review and create tasks manually if needed.
          </p>
          {gaps.map((gap, i) => {
            const severityColor = gap.severity === "high"
              ? "border-red-300 bg-red-50"
              : gap.severity === "medium"
              ? "border-amber-300 bg-amber-50"
              : "border-blue-200 bg-blue-50";
            const dotColor = gap.severity === "high" ? "bg-red-500"
              : gap.severity === "medium" ? "bg-amber-500" : "bg-blue-400";
            return (
              <div key={i} className={`rounded-lg border px-3 py-2 ${severityColor}`}>
                <div className="flex items-center gap-2 mb-0.5">
                  <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${dotColor}`} />
                  <span className="text-xs font-semibold text-gray-800">{gap.topic}</span>
                  <span className="text-xs text-gray-400 capitalize">{gap.severity}</span>
                </div>
                <p className="text-xs text-gray-600 ml-4">{gap.description}</p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}


// ── Gap Analysis Modal ────────────────────────────────────────────────────────

function GapAnalysisModal({ tasks, onTaskUpdated, onPush, onClose }) {
  const [editingTask, setEditingTask] = useState(null);

  function fieldComplete(task, { key, check }) {
    return check(task[key]);
  }

  const rows = tasks.map((t) => ({
    task: t,
    gaps: GAP_FIELDS.filter((f) => !fieldComplete(t, f)),
  }));

  const completeCount = rows.filter((r) => r.gaps.length === 0).length;
  const hasGaps = rows.some((r) => r.gaps.length > 0);

  function handleTaskUpdated(updated) {
    onTaskUpdated(updated);
    setEditingTask(null);
  }

  function handleTaskDeleted(deleted) {
    onTaskUpdated(deleted); // parent will remove from list
    setEditingTask(null);
  }

  return (
    <>
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-40 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-5xl max-h-[90vh] flex flex-col">

        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-800">Gap Analysis — Before Jira Push</h3>
            <p className="text-sm text-gray-500 mt-0.5">
              {tasks.length} task{tasks.length !== 1 ? "s" : ""} selected · Edit any task to fill missing fields before pushing
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-2xl leading-none">&times;</button>
        </div>

        {/* Summary bar */}
        <div className={`px-6 py-2.5 flex items-center gap-4 border-b text-sm ${hasGaps ? "bg-amber-50 border-amber-100" : "bg-green-50 border-green-100"}`}>
          <span className={`font-medium ${hasGaps ? "text-amber-800" : "text-green-700"}`}>
            {completeCount}/{tasks.length} tasks fully complete
          </span>
          <span className={hasGaps ? "text-amber-600" : "text-green-600"}>
            {hasGaps
              ? "Some tasks have missing content fields. Click Edit to fill them in, then push."
              : "All content fields are complete — ready to push!"}
          </span>
        </div>

        {/* Table */}
        <div className="overflow-auto flex-1">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 sticky top-0 z-10">
              <tr>
                <th className="px-4 py-2.5 text-left font-medium text-gray-500 whitespace-nowrap w-24">Task ID</th>
                <th className="px-4 py-2.5 text-left font-medium text-gray-500">Summary</th>
                {GAP_FIELDS.map(({ key, label }) => (
                  <th key={key} className="px-4 py-2.5 text-center font-medium text-gray-500 whitespace-nowrap">{label}</th>
                ))}
                <th className="px-4 py-2.5 text-left font-medium text-gray-500">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map(({ task, gaps }) => {
                const hasTaskGaps = gaps.length > 0;
                return (
                  <tr key={task.task_id} className={hasTaskGaps ? "bg-amber-50" : ""}>
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-500 whitespace-nowrap">{task.task_id}</td>

                    {/* Summary */}
                    <td className="px-4 py-2.5 max-w-xs">
                      <span className="block truncate text-gray-800" title={task.task_heading}>
                        {task.task_heading}
                      </span>
                      <span className="text-xs text-gray-400">{task.task_type} · {task.priority || "—"} · {task.schedule_interval || "—"}</span>
                    </td>

                    {/* Field indicators */}
                    {GAP_FIELDS.map((f) => {
                      const ok = fieldComplete(task, f);
                      return (
                        <td key={f.key} className="px-4 py-2.5 text-center">
                          {ok
                            ? <span className="inline-block w-5 h-5 rounded-full bg-green-100 text-green-600 text-xs font-bold leading-5">✓</span>
                            : <span className="inline-block w-5 h-5 rounded-full bg-red-100 text-red-500 text-xs font-bold leading-5">✗</span>
                          }
                        </td>
                      );
                    })}

                    {/* Edit */}
                    <td className="px-4 py-2.5">
                      <button
                        onClick={() => setEditingTask(task)}
                        className="text-xs px-3 py-1 bg-blue-50 border border-blue-200 text-blue-700 rounded hover:bg-blue-100 transition-colors"
                      >
                        Edit
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-between">
          <button
            onClick={onClose}
            className="px-4 py-2 border border-gray-300 text-gray-600 rounded-lg text-sm hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={() => onPush(tasks.map((t) => t.task_id))}
            className="px-6 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 transition-colors"
          >
            Push to Jira ({tasks.length} task{tasks.length !== 1 ? "s" : ""})
          </button>
        </div>
      </div>
    </div>

    {/* TaskCard opens on top of the gap modal (z-50 > z-40) */}
    {editingTask && (
      <TaskCard
        task={editingTask}
        onClose={() => setEditingTask(null)}
        onUpdated={handleTaskUpdated}
        onDeleted={handleTaskDeleted}
      />
    )}
    </>
  );
}

