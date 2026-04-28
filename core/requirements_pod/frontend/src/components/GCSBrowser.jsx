import React, { useState, useEffect, useRef } from "react";
import { listFiles, listProjects, parseFile, findFileByPath, registerFile, deleteFile, getFileProgress } from "../api/client.js";

const MAX_SELECTION = 3;

const STAGE_LABELS = {
  normalising:   "Normalising",
  chunking:      "Chunking",
  extracting:    "Extracting",
  deduplicating: "Deduplicating",
  merging:       "Merging",
  scoring:       "Scoring",
  saving:        "Saving",
  done:          "Complete!",
};

function todayStr() {
  return new Date().toISOString().split("T")[0];
}

function daysAgoStr(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().split("T")[0];
}

export default function GCSBrowser({ onParsed, llmProvider, guestName }) {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [parseStatus, setParseStatus] = useState({});
  const [selectedFiles, setSelectedFiles] = useState(new Set());
  const [batchParsing, setBatchParsing] = useState(false);

  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState("");

  // Per-file parse progress: { [fileName]: { stage, chunks_done, chunks_total, pct } }
  const [fileProgress, setFileProgress] = useState({});
  const pollIntervalsRef = useRef({});

  // Date filters — default last 2 days
  const [dateFrom, setDateFrom] = useState(() => daysAgoStr(2));
  const [dateTo, setDateTo] = useState(() => todayStr());

  useEffect(() => {
    listProjects().then((ps) => {
      setProjects(ps);
      if (ps.length > 0) setSelectedProject(ps[0]);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    loadFiles();
  }, [selectedProject]);

  // Cleanup any pending polling intervals on unmount
  useEffect(() => {
    return () => {
      Object.values(pollIntervalsRef.current).forEach(clearInterval);
    };
  }, []);

  async function loadFiles() {
    setLoading(true);
    setError(null);
    try {
      const data = await listFiles(selectedProject || "");
      setFiles(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function toggleFileSelect(fileName) {
    setSelectedFiles((prev) => {
      const next = new Set(prev);
      if (next.has(fileName)) {
        next.delete(fileName);
      } else if (next.size < MAX_SELECTION) {
        next.add(fileName);
      }
      return next;
    });
  }

  async function resolveFileRecord(fileName, fileSize) {
    try {
      return await findFileByPath(fileName);
    } catch (err) {
      if (err.status === 404) {
        return await registerFile(fileName, guestName, fileSize);
      }
      throw err;
    }
  }

  function startProgressPoll(fileName, fileId) {
    const interval = setInterval(async () => {
      try {
        const data = await getFileProgress(fileId);
        if (data.stage) {
          setFileProgress((prev) => ({ ...prev, [fileName]: data }));
        }
      } catch {
        // ignore — parse may have just finished
      }
    }, 800);
    pollIntervalsRef.current[fileName] = interval;
    return interval;
  }

  function stopProgressPoll(fileName) {
    if (pollIntervalsRef.current[fileName]) {
      clearInterval(pollIntervalsRef.current[fileName]);
      delete pollIntervalsRef.current[fileName];
    }
  }

  async function handleParse(file) {
    setParseStatus((prev) => ({ ...prev, [file.name]: "parsing" }));
    try {
      const fileRecord = await resolveFileRecord(file.name, file.size);
      startProgressPoll(file.name, fileRecord.id);

      const tasks = await parseFile(fileRecord.id, llmProvider);

      stopProgressPoll(file.name);
      // Show 100% briefly before clearing
      setFileProgress((prev) => ({ ...prev, [file.name]: { stage: "done", chunks_done: 0, chunks_total: 0, pct: 100 } }));
      await new Promise((r) => setTimeout(r, 900));
      setFileProgress((prev) => { const n = { ...prev }; delete n[file.name]; return n; });

      const statusMsg = tasks.length === 0
        ? "warning: No tasks extracted — document may have no actionable items"
        : `done (${tasks.length} tasks)`;
      setParseStatus((prev) => ({ ...prev, [file.name]: statusMsg }));
      if (tasks.length > 0 && onParsed) onParsed(tasks);
    } catch (err) {
      stopProgressPoll(file.name);
      setFileProgress((prev) => { const n = { ...prev }; delete n[file.name]; return n; });
      setParseStatus((prev) => ({ ...prev, [file.name]: "error: " + err.message }));
    }
  }

  async function handleParseSelected() {
    if (selectedFiles.size === 0) return;
    setBatchParsing(true);
    const fileNames = [...selectedFiles];
    setSelectedFiles(new Set());
    let anySuccess = false;
    const fileMap = Object.fromEntries(files.map((f) => [f.name, f]));

    for (const fileName of fileNames) {
      setParseStatus((prev) => ({ ...prev, [fileName]: "parsing" }));
      try {
        const fileRecord = await resolveFileRecord(fileName, fileMap[fileName]?.size);
        startProgressPoll(fileName, fileRecord.id);

        const tasks = await parseFile(fileRecord.id, llmProvider);

        stopProgressPoll(fileName);
        setFileProgress((prev) => ({ ...prev, [fileName]: { stage: "done", chunks_done: 0, chunks_total: 0, pct: 100 } }));
        await new Promise((r) => setTimeout(r, 700));
        setFileProgress((prev) => { const n = { ...prev }; delete n[fileName]; return n; });

        const statusMsg = tasks.length === 0
          ? "warning: No tasks extracted — document may have no actionable items"
          : `done (${tasks.length} tasks)`;
        setParseStatus((prev) => ({ ...prev, [fileName]: statusMsg }));
        if (tasks.length > 0) anySuccess = true;
      } catch (err) {
        stopProgressPoll(fileName);
        setFileProgress((prev) => { const n = { ...prev }; delete n[fileName]; return n; });
        setParseStatus((prev) => ({ ...prev, [fileName]: "error: " + err.message }));
      }
    }

    setBatchParsing(false);
    if (anySuccess && onParsed) onParsed();
  }

  async function handleDeleteFile(file) {
    if (!window.confirm(`Delete "${file.name}"?\nThis will permanently remove it from storage.`)) return;
    try {
      await deleteFile(file.name);
      setFiles((prev) => prev.filter((f) => f.name !== file.name));
      setParseStatus((prev) => { const n = { ...prev }; delete n[file.name]; return n; });
    } catch (err) {
      setError("Delete failed: " + err.message);
    }
  }

  // Filter by date and search
  const dateFromTs = dateFrom ? new Date(dateFrom + "T00:00:00").getTime() / 1000 : null;
  const dateToTs = dateTo ? new Date(dateTo + "T23:59:59").getTime() / 1000 : null;

  const filtered = files
    .filter((f) => {
      if (dateFromTs && f.updated != null && f.updated < dateFromTs) return false;
      if (dateToTs && f.updated != null && f.updated > dateToTs) return false;
      if (search && !f.name.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    })
    .sort((a, b) => (b.updated ?? 0) - (a.updated ?? 0));

  function formatBytes(bytes) {
    if (!bytes) return "—";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1048576).toFixed(1)} MB`;
  }

  function formatDate(ts) {
    if (!ts) return "—";
    return new Date(ts * 1000).toLocaleString();
  }

  return (
    <div>
      <h2 className="text-xl font-semibold text-gray-800 mb-4">Browse Stored Files</h2>

      {/* Filters row */}
      <div className="flex flex-wrap gap-3 mb-3 items-end">
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-500">Project / Product</label>
          <select
            value={selectedProject}
            onChange={(e) => { setSelectedProject(e.target.value); setSelectedFiles(new Set()); }}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-48 focus:outline-none focus:ring-2 focus:ring-blue-400"
          >
            <option value="">— All projects —</option>
            {projects.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-500">Search</label>
          <input
            type="text"
            placeholder="Filename..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-44 focus:outline-none focus:ring-2 focus:ring-blue-400"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-500">Uploaded from</label>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-500">to</label>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          />
        </div>
        <button
          onClick={() => { setDateFrom(daysAgoStr(2)); setDateTo(todayStr()); }}
          className="text-xs text-blue-600 hover:underline self-end pb-2"
          title="Reset to last 2 days"
        >
          Reset dates
        </button>
        <button
          onClick={loadFiles}
          disabled={loading}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors self-end"
        >
          {loading ? "Loading..." : "Refresh"}
        </button>

        {selectedFiles.size > 0 && (
          <button
            onClick={handleParseSelected}
            disabled={batchParsing}
            className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50 transition-colors self-end"
          >
            {batchParsing ? "Parsing..." : `Parse Selected (${selectedFiles.size})`}
          </button>
        )}

        {selectedFiles.size > 0 && !batchParsing && (
          <button
            onClick={() => setSelectedFiles(new Set())}
            className="text-sm text-gray-500 hover:underline self-end pb-2"
          >
            Clear selection
          </button>
        )}
      </div>

      {selectedFiles.size > 0 && (
        <p className="text-xs text-blue-600 mb-3">
          {selectedFiles.size} of {MAX_SELECTION} files selected — tasks from all selected files will be merged.
          {selectedFiles.size < MAX_SELECTION && ` Select up to ${MAX_SELECTION - selectedFiles.size} more.`}
        </p>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm mb-4">
          {error}
        </div>
      )}

      {/* File table */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-3 text-left">
                <span className="text-xs text-gray-400 font-normal">
                  {selectedFiles.size}/{MAX_SELECTION}
                </span>
              </th>
              <th className="px-4 py-3 text-left font-medium text-gray-500">Name</th>
              <th className="px-4 py-3 text-left font-medium text-gray-500">Size</th>
              <th className="px-4 py-3 text-left font-medium text-gray-500">Last Modified</th>
              <th className="px-4 py-3 text-left font-medium text-gray-500">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-gray-400">
                  {loading ? "Loading files..." : "No files found for the selected date range."}
                </td>
              </tr>
            ) : (
              filtered.map((file) => {
                const isSelected = selectedFiles.has(file.name);
                const isDisabled = !isSelected && selectedFiles.size >= MAX_SELECTION;
                const status = parseStatus[file.name];
                const progress = fileProgress[file.name];
                const isParsing = status === "parsing";

                return (
                  <tr
                    key={file.name}
                    className={`hover:bg-gray-50 ${isSelected ? "bg-blue-50" : ""}`}
                  >
                    <td className="px-3 py-3">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        disabled={isDisabled || batchParsing || isParsing}
                        onChange={() => toggleFileSelect(file.name)}
                        className="rounded"
                        title={isDisabled ? `Maximum ${MAX_SELECTION} files can be selected` : ""}
                      />
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-700 max-w-xs truncate">
                      {file.name}
                    </td>
                    <td className="px-4 py-3 text-gray-500">{formatBytes(file.size)}</td>
                    <td className="px-4 py-3 text-gray-500">{formatDate(file.updated)}</td>
                    <td className="px-4 py-3">
                      {/* Progress bar takes priority while parsing */}
                      {progress ? (
                        <div className="min-w-[180px]">
                          <div className="flex justify-between text-xs mb-1">
                            <span className="text-blue-700 truncate max-w-[130px]">
                              {STAGE_LABELS[progress.stage] ?? "Processing…"}
                            </span>
                            <span className="font-mono ml-1">{progress.pct}%</span>
                          </div>
                          <div className="w-full bg-blue-200 rounded-full h-1.5">
                            <div
                              className="bg-blue-600 h-1.5 rounded-full transition-all duration-500"
                              style={{ width: `${progress.pct}%` }}
                            />
                          </div>
                        </div>
                      ) : status ? (
                        <span
                          className={`text-xs ${
                            status.startsWith("error")
                              ? "text-red-500"
                              : status.startsWith("warning")
                              ? "text-amber-600"
                              : "text-green-600"
                          }`}
                          title={status.startsWith("error") || status.startsWith("warning") ? status : undefined}
                        >
                          {status.startsWith("error")
                            ? status.replace(/^error:\s*/, "")
                            : status.startsWith("warning")
                            ? "no tasks found"
                            : status}
                        </span>
                      ) : (
                        <div className="flex gap-2">
                          <button
                            onClick={() => handleParse(file)}
                            disabled={batchParsing}
                            className="text-xs px-3 py-1 bg-blue-50 border border-blue-200 text-blue-700 rounded hover:bg-blue-100 disabled:opacity-50 transition-colors"
                          >
                            Parse
                          </button>
                          <button
                            onClick={() => handleDeleteFile(file)}
                            disabled={batchParsing}
                            className="text-xs px-2 py-1 bg-red-50 border border-red-200 text-red-600 rounded hover:bg-red-100 disabled:opacity-50 transition-colors"
                            title="Delete file from storage"
                          >
                            Del
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <p className="mt-2 text-xs text-gray-400">
        Showing {filtered.length} of {files.length} file(s)
        {(dateFrom || dateTo) && <span> · filtered by date</span>}
      </p>
    </div>
  );
}
