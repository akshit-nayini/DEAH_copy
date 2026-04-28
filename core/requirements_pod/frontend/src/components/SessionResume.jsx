import React, { useState, useEffect } from "react";
import { listTasks } from "../api/client.js";
import TaskTable from "./TaskTable.jsx";

export default function SessionResume({ guestName }) {
  const [sourceFiles, setSourceFiles] = useState([]);
  const [selectedSource, setSelectedSource] = useState("");
  const [filterUser, setFilterUser] = useState(guestName || "");
  const [tasks, setTasks] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedTasks, setSelectedTasks] = useState([]);

  // Load distinct source file info from all tasks on mount
  useEffect(() => {
    async function fetchSources() {
      try {
        const allTasks = await listTasks();
        const sources = [...new Set(allTasks.map((t) => t.task_source).filter(Boolean))];
        setSourceFiles(sources);
      } catch {
        // ignore
      }
    }
    fetchSources();
  }, []);

  async function handleLoad() {
    setLoading(true);
    setError(null);
    try {
      const filters = {};
      if (filterUser.trim()) filters.user_name = filterUser.trim();
      const data = await listTasks(filters);
      // Client-side filter by source if selected
      const filtered = selectedSource
        ? data.filter((t) => t.task_source === selectedSource)
        : data;
      setTasks(filtered);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h2 className="text-xl font-semibold text-gray-800 mb-4">Resume Session</h2>
      <p className="text-sm text-gray-500 mb-5">
        Pick a previously uploaded file and/or a user name to reload previously extracted tasks.
      </p>

      {/* Filters */}
      <div className="flex flex-wrap gap-4 mb-6 bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-500">Source File</label>
          <select
            value={selectedSource}
            onChange={(e) => setSelectedSource(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 min-w-[220px]"
          >
            <option value="">— All sources —</option>
            {sourceFiles.map((src) => (
              <option key={src} value={src}>
                {src}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-500">User Name</label>
          <input
            type="text"
            value={filterUser}
            onChange={(e) => setFilterUser(e.target.value)}
            placeholder="Filter by user..."
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 w-48"
          />
        </div>

        <div className="flex items-end">
          <button
            onClick={handleLoad}
            disabled={loading}
            className="px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {loading ? "Loading..." : "Load Tasks"}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm mb-4">
          {error}
        </div>
      )}

      {tasks !== null && (
        <div>
          <p className="text-sm text-gray-500 mb-3">
            Found <strong>{tasks.length}</strong> task(s).
          </p>
          {tasks.length > 0 ? (
            <div>
              {/* Render a simplified task list */}
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200 text-sm">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left font-medium text-gray-500">ID</th>
                      <th className="px-4 py-3 text-left font-medium text-gray-500">Heading</th>
                      <th className="px-4 py-3 text-left font-medium text-gray-500">Type</th>
                      <th className="px-4 py-3 text-left font-medium text-gray-500">Status</th>
                      <th className="px-4 py-3 text-left font-medium text-gray-500">Source</th>
                      <th className="px-4 py-3 text-left font-medium text-gray-500">Assigned</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {tasks.map((task) => (
                      <tr key={task.task_id} className="hover:bg-gray-50">
                        <td className="px-4 py-2 font-mono text-xs text-gray-500">
                          {task.task_id}
                        </td>
                        <td className="px-4 py-2 text-gray-800 max-w-xs truncate">
                          {task.task_heading}
                        </td>
                        <td className="px-4 py-2">
                          <span className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">
                            {task.task_type}
                          </span>
                        </td>
                        <td className="px-4 py-2">
                          <span className="text-xs bg-yellow-50 text-yellow-700 px-2 py-0.5 rounded-full">
                            {task.status}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-gray-400 text-xs truncate max-w-xs">
                          {task.task_source || "—"}
                        </td>
                        <td className="px-4 py-2 text-gray-500">
                          {task.user_name || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="text-center text-gray-400 py-10">
              No tasks match the selected filters.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
