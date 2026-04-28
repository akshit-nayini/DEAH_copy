import React, { useState } from "react";
import { updateTask, deleteTask } from "../api/client.js";

const TASK_TYPES    = ["bug", "story", "task", "subtask"];
const TASK_STATUSES = ["extracted", "modified", "pushed", "deleted"];
const PRIORITIES    = ["critical", "high", "medium", "low"];

function parseAcceptanceCriteria(raw) {
  if (!raw) return "";
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed.join("\n");
  } catch {
    // not JSON — return as-is
  }
  return raw;
}

function serializeAcceptanceCriteria(text) {
  if (!text || !text.trim()) return null;
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  return JSON.stringify(lines);
}

export default function TaskCard({ task, onClose, onUpdated, onDeleted }) {
  const [form, setForm] = useState({
    task_heading:         task.task_heading,
    description:          task.description || "",
    task_type:            task.task_type,
    status:               task.status,
    user_name:            task.user_name || "",
    priority:             task.priority || "",
    reporter:             task.reporter || "",
    assignee:             task.assignee || "",
    sprint:               task.sprint || "",
    fix_version:          task.fix_version || "",
    start_date:           task.start_date ? task.start_date.split("T")[0] : "",
    due_date:             task.due_date   ? task.due_date.split("T")[0]   : "",
    story_points:         task.story_points ?? "",
    acceptance_criteria:  parseAcceptanceCriteria(task.acceptance_criteria),
    schedule_interval:    task.schedule_interval || "",
  });
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState(null);

  function handleChange(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const payload = {
        ...form,
        story_points: form.story_points !== "" ? Number(form.story_points) : null,
        acceptance_criteria: serializeAcceptanceCriteria(form.acceptance_criteria),
        priority: form.priority || null,
        reporter: form.reporter || null,
        assignee: form.assignee || null,
        sprint: form.sprint || null,
        fix_version: form.fix_version || null,
        start_date: form.start_date || null,
        due_date: form.due_date || null,
        schedule_interval: form.schedule_interval || null,
      };
      const updated = await updateTask(task.task_id, payload);
      onUpdated(updated);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!window.confirm(`Delete task ${task.task_id}? This action cannot be undone.`)) return;
    setDeleting(true);
    setError(null);
    try {
      const deleted = await deleteTask(task.task_id);
      onDeleted(deleted);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <div>
            <span className="text-xs font-mono text-gray-400">{task.task_id}</span>
            <h3 className="text-lg font-semibold text-gray-800">Edit Task</h3>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-2xl leading-none"
          >
            &times;
          </button>
        </div>

        <div className="px-6 py-5 space-y-4">
          {/* Summary (heading) */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Summary</label>
            <input
              type="text"
              value={form.task_heading}
              onChange={(e) => handleChange("task_heading", e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            />
          </div>

          {/* Description + Schedule Interval */}
          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
              <textarea
                value={form.description}
                onChange={(e) => handleChange("description", e.target.value)}
                rows={4}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 resize-y"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Schedule Interval
                <span className="ml-1 text-xs font-normal text-red-500">* required</span>
              </label>
              <input
                type="text"
                value={form.schedule_interval}
                onChange={(e) => handleChange("schedule_interval", e.target.value)}
                placeholder="e.g. daily, hourly, weekly, on-demand"
                className={`w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 ${
                  !form.schedule_interval ? "border-red-300 bg-red-50" : "border-gray-300"
                }`}
              />
            </div>
          </div>

          {/* Issue Type + Status */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Issue Type</label>
              <select
                value={form.task_type}
                onChange={(e) => handleChange("task_type", e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              >
                {TASK_TYPES.map((t) => (
                  <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
              <select
                value={form.status}
                onChange={(e) => handleChange("status", e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              >
                {TASK_STATUSES.map((s) => (
                  <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Priority + Story Points */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Priority</label>
              <select
                value={form.priority}
                onChange={(e) => handleChange("priority", e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              >
                <option value="">— Not set —</option>
                {PRIORITIES.map((p) => (
                  <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Story Points</label>
              <input
                type="number"
                min="0"
                value={form.story_points}
                onChange={(e) => handleChange("story_points", e.target.value)}
                placeholder="e.g. 3"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
            </div>
          </div>

          {/* Assigned To + Reporter */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Assigned To</label>
              <input
                type="text"
                value={form.user_name}
                onChange={(e) => handleChange("user_name", e.target.value)}
                placeholder="Leave blank if unassigned"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Reporter</label>
              <input
                type="text"
                value={form.reporter}
                onChange={(e) => handleChange("reporter", e.target.value)}
                placeholder="Leave blank if unknown"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
            </div>
          </div>

          {/* Assignee + Start Date + Due Date */}
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Assignee (Developer)</label>
              <input
                type="text"
                value={form.assignee}
                onChange={(e) => handleChange("assignee", e.target.value)}
                placeholder="e.g. Shailendra"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Start Date</label>
              <input
                type="date"
                value={form.start_date}
                onChange={(e) => handleChange("start_date", e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Due Date</label>
              <input
                type="date"
                value={form.due_date}
                onChange={(e) => handleChange("due_date", e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
            </div>
          </div>

          {/* Sprint + Fix Version */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Sprint</label>
              <input
                type="text"
                value={form.sprint}
                onChange={(e) => handleChange("sprint", e.target.value)}
                placeholder="e.g. Sprint 12"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Fix Version</label>
              <input
                type="text"
                value={form.fix_version}
                onChange={(e) => handleChange("fix_version", e.target.value)}
                placeholder="e.g. v2.1.0"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
            </div>
          </div>

          {/* Acceptance Criteria */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Acceptance Criteria
              <span className="ml-1 text-xs font-normal text-gray-400">(one criterion per line)</span>
            </label>
            <textarea
              value={form.acceptance_criteria}
              onChange={(e) => handleChange("acceptance_criteria", e.target.value)}
              rows={4}
              placeholder="Enter each acceptance criterion on a new line"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 resize-y"
            />
          </div>

          {/* Read-only metadata */}
          <div className="grid grid-cols-2 gap-4 text-sm text-gray-500 pt-1 border-t border-gray-100">
            <div>
              <span className="font-medium">Created:</span>{" "}
              {task.created_at ? new Date(task.created_at).toLocaleString() : "—"}
            </div>
            <div>
              <span className="font-medium">Source:</span> {task.task_source || "—"}
            </div>
            <div>
              <span className="font-medium">Location:</span> {task.location || "—"}
            </div>
            {task.jira_id && (
              <div>
                <span className="font-medium">Jira:</span>{" "}
                <a
                  href={task.jira_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:underline"
                >
                  {task.jira_id}
                </a>
              </div>
            )}
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
              {error}
            </div>
          )}
        </div>

        {/* Footer actions */}
        <div className="px-6 py-4 border-t border-gray-200 flex justify-between">
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="px-4 py-2 bg-red-50 border border-red-200 text-red-600 rounded-lg text-sm hover:bg-red-100 disabled:opacity-50 transition-colors"
          >
            {deleting ? "Deleting..." : "Delete"}
          </button>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 border border-gray-300 text-gray-600 rounded-lg text-sm hover:bg-gray-50 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {saving ? "Saving..." : "Save Changes"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
