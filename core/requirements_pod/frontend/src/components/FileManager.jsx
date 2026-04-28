import React, { useState, useEffect, useRef } from "react";
import {
  uploadFile, parseFile, parseMergedFiles, getFileProgress,
  listProjects, listFiles, findFileByPath, registerFile, deleteFile,
} from "../api/client.js";

const MAX_STAGED = 5;
const ALLOWED_EXTENSIONS = ["pdf", "docx", "txt", "md", "vtt", "srt"];
const MAX_SIZE_MB = 50;

const STAGE_LABELS = {
  normalising:   "Normalising",
  chunking:      "Chunking",
  extracting:    "Extracting with AI",
  deduplicating: "Deduplicating",
  merging:       "Merging",
  scoring:       "Scoring",
  saving:        "Saving",
  done:          "Complete!",
};

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

function daysAgoStr(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().split("T")[0];
}

function todayStr() {
  return new Date().toISOString().split("T")[0];
}

function basename(path) {
  return path ? path.split("/").pop() : path;
}

function StagedStatusIcon({ status }) {
  if (status === "extracting")
    return <span className="text-blue-500 animate-pulse text-base leading-none">⟳</span>;
  if (status === "done")
    return <span className="text-green-600 text-base leading-none">✓</span>;
  if (status === "warning")
    return <span className="text-amber-500 text-base leading-none">⚠</span>;
  if (status === "error")
    return <span className="text-red-500 text-base leading-none">✗</span>;
  return <span className="text-gray-300 text-base leading-none">○</span>;
}

/**
 * FileManager — unified upload + browse + staging page.
 *
 * Props:
 *   onParsed(tasks) — called after successful extraction
 *   llmProvider     — "claude-sdk" | "claude" | "mock"
 */
export default function FileManager({ onParsed, llmProvider }) {
  // ── Project ───────────────────────────────────────────────────────────────
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState("");
  const [isNewProject, setIsNewProject] = useState(false);
  const [newProjectInput, setNewProjectInput] = useState("");

  // ── Local upload queue ────────────────────────────────────────────────────
  // { file, status: "uploading"|"uploaded"|"error", error, uploadedRecord }
  const [uploadQueue, setUploadQueue] = useState([]);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);

  // ── Stored files (browse) ─────────────────────────────────────────────────
  const [storedFiles, setStoredFiles] = useState([]);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [filesError, setFilesError] = useState(null);
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState(() => daysAgoStr(2));
  const [dateTo, setDateTo] = useState(() => todayStr());
  // filenames currently being resolved (findFileByPath / registerFile in flight)
  const [resolvingFiles, setResolvingFiles] = useState(new Set());

  // ── Staging area ──────────────────────────────────────────────────────────
  // StagedEntry: { fileId, name, source: "upload"|"browse",
  //               status: "ready"|"extracting"|"done"|"warning"|"error",
  //               progress: null|{ stage, pct }, resultMsg: null|string }
  const [staged, setStaged] = useState([]);

  // Keep a ref so async callbacks can read the current staged length reliably
  const stagedRef = useRef(staged);
  useEffect(() => { stagedRef.current = staged; }, [staged]);

  // ── Extraction ─────────────────────────────────────────────────────────────
  const [isExtracting, setIsExtracting] = useState(false);
  const extractPollRefs = useRef({});

  const effectiveProject = isNewProject ? newProjectInput.trim() : selectedProject;

  // ── Init ──────────────────────────────────────────────────────────────────

  useEffect(() => {
    listProjects()
      .then((ps) => {
        setProjects(ps);
        if (ps.length > 0) setSelectedProject(ps[0]);
      })
      .catch(() => {});
    return () => Object.values(extractPollRefs.current).forEach(clearInterval);
  }, []);

  useEffect(() => {
    loadStoredFiles();
  }, [selectedProject]); // eslint-disable-line react-hooks/exhaustive-deps

  async function loadStoredFiles() {
    setLoadingFiles(true);
    setFilesError(null);
    try {
      const data = await listFiles(selectedProject || "");
      setStoredFiles(data);
    } catch (err) {
      setFilesError(err.message);
    } finally {
      setLoadingFiles(false);
    }
  }

  // ── Staging helpers ───────────────────────────────────────────────────────

  function addToStaged(fileId, name, source) {
    setStaged((prev) => {
      if (prev.length >= MAX_STAGED) return prev;
      if (prev.find((s) => s.fileId === fileId)) return prev;
      return [
        ...prev,
        { fileId, name, source, status: "ready", progress: null, resultMsg: null },
      ];
    });
  }

  function removeFromStaged(fileId) {
    setStaged((prev) => prev.filter((s) => s.fileId !== fileId));
  }

  function updateStaged(fileId, patch) {
    setStaged((prev) => prev.map((s) => (s.fileId === fileId ? { ...s, ...patch } : s)));
  }

  function clearDoneFromStaged() {
    setStaged((prev) => prev.filter((s) => s.status !== "done" && s.status !== "warning"));
  }

  // ── Local upload ──────────────────────────────────────────────────────────

  function validateFile(file) {
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(ext))
      return `".${ext}" not allowed. Accepted: ${ALLOWED_EXTENSIONS.join(", ")}`;
    if (file.size > MAX_SIZE_MB * 1024 * 1024)
      return `File exceeds ${MAX_SIZE_MB} MB limit.`;
    return null;
  }

  function updateUploadEntry(name, patch) {
    setUploadQueue((prev) =>
      prev.map((e) => (e.file.name === name ? { ...e, ...patch } : e))
    );
  }

  async function addLocalFiles(files) {
    const incoming = Array.from(files);
    for (const file of incoming) {
      const err = validateFile(file);
      setUploadQueue((prev) => {
        if (prev.find((e) => e.file.name === file.name)) return prev;
        return [
          ...prev,
          { file, status: err ? "error" : "uploading", error: err, uploadedRecord: null },
        ];
      });
      if (!err) uploadOneFile(file);
    }
  }

  async function uploadOneFile(file) {
    try {
      const record = await uploadFile(file, null, effectiveProject);
      // Auto-stage if space available (use ref for current count)
      if (
        stagedRef.current.length < MAX_STAGED &&
        !stagedRef.current.find((s) => s.fileId === record.id)
      ) {
        setUploadQueue((prev) => prev.filter((e) => e.file.name !== file.name));
        addToStaged(record.id, file.name, "upload");
      } else {
        // Staging full — keep in queue as "uploaded" so user can stage manually later
        updateUploadEntry(file.name, { status: "uploaded", uploadedRecord: record, error: null });
      }
    } catch (err) {
      updateUploadEntry(file.name, { status: "error", error: err.message });
    }
  }

  function stageUploadedEntry(entry) {
    if (staged.length >= MAX_STAGED) return;
    addToStaged(entry.uploadedRecord.id, entry.file.name, "upload");
    setUploadQueue((prev) => prev.filter((e) => e.file.name !== entry.file.name));
  }

  function removeUploadEntry(name) {
    setUploadQueue((prev) => prev.filter((e) => e.file.name !== name));
  }

  function handleDrop(e) {
    e.preventDefault();
    setDragOver(false);
    addLocalFiles(e.dataTransfer.files);
  }

  // ── Browse ────────────────────────────────────────────────────────────────

  async function resolveFileRecord(fileName, fileSize) {
    try {
      return await findFileByPath(fileName);
    } catch (err) {
      if (err.status === 404) return await registerFile(fileName, null, fileSize);
      throw err;
    }
  }

  async function handleBrowseToggle(file) {
    const alreadyStaged = staged.find((s) => s.name === file.name);
    if (alreadyStaged) {
      removeFromStaged(alreadyStaged.fileId);
      return;
    }
    if (staged.length >= MAX_STAGED) return;
    if (resolvingFiles.has(file.name)) return;

    setResolvingFiles((prev) => new Set([...prev, file.name]));
    try {
      const record = await resolveFileRecord(file.name, file.size);
      addToStaged(record.id, file.name, "browse");
    } catch (err) {
      setFilesError(`Could not stage "${basename(file.name)}": ${err.message}`);
    } finally {
      setResolvingFiles((prev) => {
        const next = new Set(prev);
        next.delete(file.name);
        return next;
      });
    }
  }

  async function handleDeleteStoredFile(file) {
    if (
      !window.confirm(
        `Delete "${basename(file.name)}"?\nThis permanently removes it from storage.`
      )
    )
      return;
    try {
      await deleteFile(file.name);
      setStoredFiles((prev) => prev.filter((f) => f.name !== file.name));
      const stagedEntry = staged.find((s) => s.name === file.name);
      if (stagedEntry) removeFromStaged(stagedEntry.fileId);
    } catch (err) {
      setFilesError("Delete failed: " + err.message);
    }
  }

  // ── Extraction ─────────────────────────────────────────────────────────────

  async function handleExtractSeparately() {
    const readyItems = staged.filter((s) => s.status === "ready");
    if (readyItems.length === 0) return;
    setIsExtracting(true);
    const successfulFileIds = [];
    const allNewTaskIds = [];

    for (const item of readyItems) {
      updateStaged(item.fileId, { status: "extracting", progress: { stage: null, pct: 0 } });

      const interval = setInterval(async () => {
        try {
          const data = await getFileProgress(item.fileId);
          if (data.stage) updateStaged(item.fileId, { progress: data });
        } catch { /* ignore */ }
      }, 800);
      extractPollRefs.current[item.fileId] = interval;

      try {
        const tasks = await parseFile(item.fileId, llmProvider);
        clearInterval(interval);
        delete extractPollRefs.current[item.fileId];
        const ok = tasks.length > 0;
        updateStaged(item.fileId, {
          status: ok ? "done" : "warning",
          progress: { stage: "done", pct: 100 },
          resultMsg: ok
            ? `${tasks.length} task${tasks.length !== 1 ? "s" : ""} extracted`
            : "No tasks found",
        });
        if (ok) {
          successfulFileIds.push(item.fileId);
          allNewTaskIds.push(...tasks.map((t) => t.task_id));
        }
      } catch (err) {
        clearInterval(interval);
        delete extractPollRefs.current[item.fileId];
        updateStaged(item.fileId, { status: "error", progress: null, resultMsg: err.message });
      }
    }

    setIsExtracting(false);
    if (successfulFileIds.length > 0) {
      await new Promise((r) => setTimeout(r, 600));
      onParsed(successfulFileIds, allNewTaskIds);
    }
  }

  async function handleMergeExtract() {
    const readyItems = staged.filter((s) => s.status === "ready");
    if (readyItems.length === 0) return;
    setIsExtracting(true);

    for (const item of readyItems) {
      updateStaged(item.fileId, { status: "extracting", progress: { stage: null, pct: 0 } });
    }

    const primary = readyItems[0];
    const interval = setInterval(async () => {
      try {
        const data = await getFileProgress(primary.fileId);
        if (data.stage) {
          for (const item of readyItems) {
            updateStaged(item.fileId, { progress: data });
          }
        }
      } catch { /* ignore */ }
    }, 800);
    extractPollRefs.current["__merged__"] = interval;

    try {
      const fileIds = readyItems.map((i) => i.fileId);
      const tasks = await parseMergedFiles(fileIds, llmProvider);
      clearInterval(interval);
      delete extractPollRefs.current["__merged__"];
      const ok = tasks.length > 0;
      for (const item of readyItems) {
        updateStaged(item.fileId, {
          status: ok ? "done" : "warning",
          progress: { stage: "done", pct: 100 },
          resultMsg: ok
            ? `merged — ${tasks.length} task${tasks.length !== 1 ? "s" : ""} total`
            : "No tasks found",
        });
      }
      setIsExtracting(false);
      if (tasks.length > 0) {
        await new Promise((r) => setTimeout(r, 600));
        onParsed(readyItems.map((i) => i.fileId), tasks.map((t) => t.task_id));
      }
    } catch (err) {
      clearInterval(interval);
      delete extractPollRefs.current["__merged__"];
      for (const item of readyItems) {
        updateStaged(item.fileId, { status: "error", progress: null, resultMsg: err.message });
      }
      setIsExtracting(false);
    }
  }

  // ── Derived values ────────────────────────────────────────────────────────

  const dateFromTs = dateFrom
    ? new Date(dateFrom + "T00:00:00").getTime() / 1000
    : null;
  const dateToTs = dateTo
    ? new Date(dateTo + "T23:59:59").getTime() / 1000
    : null;

  const filteredFiles = storedFiles
    .filter((f) => {
      if (dateFromTs && f.updated != null && f.updated < dateFromTs) return false;
      if (dateToTs && f.updated != null && f.updated > dateToTs) return false;
      if (search && !f.name.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    })
    .sort((a, b) => (b.updated ?? 0) - (a.updated ?? 0));

  const readyStagedCount = staged.filter((s) => s.status === "ready").length;
  const hasDoneItems = staged.some(
    (s) => s.status === "done" || s.status === "warning"
  );

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">

      {/* ── Project selector ─────────────────────────────────────────────── */}
      <div className="flex items-end gap-3">
        <div className="flex flex-col gap-1 w-72">
          <label className="text-sm font-semibold text-indigo-800 flex items-center gap-1.5">
            <svg className="w-4 h-4 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
            </svg>
            Project / Product
          </label>
          {!isNewProject ? (
            <select
              value={selectedProject}
              onChange={(e) => {
                if (e.target.value === "__new__") {
                  setIsNewProject(true);
                  setSelectedProject("");
                } else {
                  setSelectedProject(e.target.value);
                }
              }}
              disabled={isExtracting}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-gray-50"
            >
              <option value="">— All projects —</option>
              {projects.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
              <option value="__new__">+ New project…</option>
            </select>
          ) : (
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="New project name…"
                value={newProjectInput}
                onChange={(e) => setNewProjectInput(e.target.value)}
                autoFocus
                className="flex-1 border border-blue-400 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
              <button
                onClick={() => { setIsNewProject(false); setNewProjectInput(""); }}
                className="px-3 py-2 text-sm border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>
          )}
          {effectiveProject && (
            <p className="text-xs text-gray-400">
              Upload path:{" "}
              <span className="font-mono">{effectiveProject}/date/file</span>
            </p>
          )}
        </div>
      </div>

      {/* ── Two-column layout ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-4">

        {/* LEFT — Upload new files */}
        <div className="border border-indigo-100 rounded-xl bg-white flex flex-col overflow-hidden shadow-sm">
          <div className="px-4 py-3 card-header-indigo">
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
              <h3 className="text-sm font-semibold text-indigo-800">Upload New Files</h3>
            </div>
            <p className="text-xs text-indigo-400 mt-0.5 ml-6">
              {ALLOWED_EXTENSIONS.join(", ")} · max {MAX_SIZE_MB} MB each
            </p>
          </div>

          <div className="p-4 flex flex-col gap-3 flex-1">
            {/* Drop zone */}
            <div
              onDrop={handleDrop}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onClick={() => !isExtracting && fileInputRef.current?.click()}
              className={`border-2 border-dashed rounded-xl p-6 text-center transition-all duration-200 flex flex-col items-center justify-center min-h-36 ${
                isExtracting
                  ? "border-gray-200 bg-gray-50 cursor-not-allowed opacity-50"
                  : dragOver
                  ? "dropzone-hover border-indigo-500 cursor-copy"
                  : "border-indigo-200 bg-gradient-to-br from-slate-50 to-indigo-50/40 hover:border-indigo-400 hover:from-indigo-50/60 hover:to-violet-50/40 cursor-pointer"
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept={ALLOWED_EXTENSIONS.map((e) => `.${e}`).join(",")}
                className="hidden"
                onChange={(e) => { addLocalFiles(e.target.files); e.target.value = ""; }}
              />
              <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-indigo-100 to-violet-100 flex items-center justify-center mb-3">
                <svg className="w-6 h-6 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                </svg>
              </div>
              <p className="text-sm text-indigo-700 font-semibold">
                Drop files here or click to browse
              </p>
              <p className="text-xs text-indigo-400 mt-1">Multiple files supported</p>
            </div>

            {/* Upload queue — shows uploading and error/uploaded-but-full entries */}
            {uploadQueue.length > 0 && (
              <ul className="space-y-1.5">
                {uploadQueue.map((entry) => (
                  <li
                    key={entry.file.name}
                    className="flex items-start gap-2 text-xs rounded-lg border px-3 py-2 bg-white"
                  >
                    <span className="flex-shrink-0 mt-0.5">
                      {entry.status === "uploading" && (
                        <span className="text-blue-500 animate-pulse">⟳</span>
                      )}
                      {entry.status === "uploaded" && (
                        <span className="text-green-500">✓</span>
                      )}
                      {entry.status === "error" && (
                        <span className="text-red-500">✗</span>
                      )}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="truncate font-medium text-gray-700">{entry.file.name}</p>
                      {entry.status === "uploading" && (
                        <p className="text-blue-500">Uploading…</p>
                      )}
                      {entry.status === "uploaded" && (
                        <p className="text-gray-400">
                          Uploaded — staging full.{" "}
                          <button
                            onClick={() => stageUploadedEntry(entry)}
                            disabled={staged.length >= MAX_STAGED}
                            className="text-blue-600 hover:underline disabled:opacity-40 disabled:no-underline"
                          >
                            Stage when ready
                          </button>
                        </p>
                      )}
                      {entry.error && (
                        <p className="text-red-500">{entry.error}</p>
                      )}
                    </div>
                    {entry.status !== "uploading" && (
                      <button
                        onClick={() => removeUploadEntry(entry.file.name)}
                        className="flex-shrink-0 text-gray-300 hover:text-gray-500 text-base leading-none"
                      >
                        ×
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* RIGHT — Browse stored files */}
        <div className="border border-violet-100 rounded-xl bg-white flex flex-col overflow-hidden shadow-sm">
          <div className="px-4 py-3 card-header-violet flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-violet-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
                </svg>
                <h3 className="text-sm font-semibold text-violet-800">Stored Files</h3>
              </div>
              <p className="text-xs text-violet-400 mt-0.5 ml-6">
                Check to stage · up to {MAX_STAGED} total
              </p>
            </div>
            <button
              onClick={loadStoredFiles}
              disabled={loadingFiles || isExtracting}
              className="text-xs px-3 py-1.5 bg-white border border-violet-200 text-violet-600 rounded-lg hover:bg-violet-50 disabled:opacity-50 transition-colors"
            >
              {loadingFiles ? "Loading…" : "↺ Refresh"}
            </button>
          </div>

          {/* Filters */}
          <div className="px-4 py-2 border-b border-gray-100 flex flex-wrap gap-2 items-center">
            <input
              type="text"
              placeholder="Search…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1 text-xs w-32 focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
            <span className="text-xs text-gray-400">to</span>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
            <button
              onClick={() => { setDateFrom(daysAgoStr(2)); setDateTo(todayStr()); }}
              className="text-xs text-blue-600 hover:underline"
            >
              Reset
            </button>
          </div>

          {filesError && (
            <div className="mx-4 mt-2 bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded text-xs">
              {filesError}
              <button
                onClick={() => setFilesError(null)}
                className="ml-2 text-red-400 hover:text-red-600"
              >
                ×
              </button>
            </div>
          )}

          {/* File list */}
          <div className="overflow-y-auto flex-1" style={{ maxHeight: "340px" }}>
            {staged.length >= MAX_STAGED && (
              <div className="px-4 py-2 text-xs text-amber-700 bg-amber-50 border-b border-amber-100">
                Staging area full ({MAX_STAGED}/{MAX_STAGED}) — remove a staged file to add more.
              </div>
            )}
            <table className="min-w-full text-xs divide-y divide-gray-100">
              <tbody className="divide-y divide-gray-100">
                {filteredFiles.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-violet-300">
                      {loadingFiles ? "Loading files…" : "No files found"}
                    </td>
                  </tr>
                ) : (
                  filteredFiles.map((file) => {
                    const isStaged = staged.some((s) => s.name === file.name);
                    const isResolving = resolvingFiles.has(file.name);
                    const isDisabled =
                      isExtracting ||
                      isResolving ||
                      (!isStaged && staged.length >= MAX_STAGED);

                    return (
                      <tr
                        key={file.name}
                        className={`hover:bg-gray-50 ${isStaged ? "bg-blue-50" : ""}`}
                      >
                        {/* Checkbox */}
                        <td className="px-3 py-2.5 w-8">
                          {isResolving ? (
                            <span className="text-blue-400 animate-pulse">⟳</span>
                          ) : (
                            <input
                              type="checkbox"
                              checked={isStaged}
                              disabled={isDisabled}
                              onChange={() => handleBrowseToggle(file)}
                              className="rounded"
                              title={
                                !isStaged && staged.length >= MAX_STAGED
                                  ? `Max ${MAX_STAGED} files in staging`
                                  : ""
                              }
                            />
                          )}
                        </td>
                        {/* Name */}
                        <td
                          className="px-2 py-2.5 font-mono text-gray-700 max-w-[160px] truncate"
                          title={file.name}
                        >
                          {basename(file.name)}
                        </td>
                        {/* Size */}
                        <td className="px-2 py-2.5 text-gray-400 whitespace-nowrap">
                          {formatBytes(file.size)}
                        </td>
                        {/* Date */}
                        <td className="px-2 py-2.5 text-gray-400 whitespace-nowrap">
                          {formatDate(file.updated)}
                        </td>
                        {/* Delete */}
                        <td className="px-2 py-2.5">
                          <button
                            onClick={() => handleDeleteStoredFile(file)}
                            disabled={isExtracting}
                            className="text-red-400 hover:text-red-600 disabled:opacity-40 text-xs"
                            title="Delete from storage"
                          >
                            Del
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
            <p className="px-4 py-2 text-xs text-gray-400">
              {filteredFiles.length} of {storedFiles.length} file
              {storedFiles.length !== 1 ? "s" : ""}
            </p>
          </div>
        </div>
      </div>

      {/* ── Staging area ─────────────────────────────────────────────────── */}
      {staged.length > 0 && (
        <div className="border border-indigo-200 rounded-xl overflow-hidden shadow-sm">
          <div className="px-4 py-3 staging-header flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-indigo-500 flex items-center justify-center flex-shrink-0">
                <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                </svg>
              </div>
              <div>
                <h3 className="text-sm font-semibold text-indigo-900">
                  Staging Area &mdash; {staged.length} / {MAX_STAGED} files
                </h3>
                <p className="text-xs text-indigo-600 mt-0.5">
                  {readyStagedCount} ready to extract
                </p>
              </div>
            </div>
            {hasDoneItems && !isExtracting && (
              <button
                onClick={clearDoneFromStaged}
                className="text-xs text-indigo-600 hover:underline font-medium"
              >
                Clear completed
              </button>
            )}
          </div>

          {/* Staged file list */}
          <div className="p-4 space-y-2 bg-indigo-50/60">
            {staged.map((item) => (
              <div
                key={item.fileId}
                className="flex items-center gap-3 bg-white border border-indigo-100 rounded-lg px-3 py-2.5 shadow-sm"
              >
                <StagedStatusIcon status={item.status} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-gray-700 truncate">
                      {basename(item.name)}
                    </p>
                    <span
                      className={`text-xs px-1.5 py-0.5 rounded-full flex-shrink-0 font-medium ${
                        item.source === "upload"
                          ? "bg-purple-100 text-purple-600"
                          : "bg-gray-100 text-gray-500"
                      }`}
                    >
                      {item.source === "upload" ? "new" : "stored"}
                    </span>
                  </div>

                  {/* Extraction progress bar */}
                  {item.status === "extracting" && item.progress?.stage && (
                    <div className="mt-1">
                      <div className="flex justify-between text-xs text-blue-600 mb-0.5">
                        <span>
                          {STAGE_LABELS[item.progress.stage] ?? "Processing…"}
                        </span>
                        <span>{item.progress.pct}%</span>
                      </div>
                      <div className="w-full bg-blue-100 rounded-full h-1">
                        <div
                          className="bg-blue-500 h-1 rounded-full transition-all duration-500"
                          style={{ width: `${item.progress.pct}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {/* Result message */}
                  {item.resultMsg && (
                    <p
                      className={`text-xs mt-0.5 ${
                        item.status === "error"
                          ? "text-red-500"
                          : item.status === "warning"
                          ? "text-amber-600"
                          : "text-green-600"
                      }`}
                    >
                      {item.resultMsg}
                    </p>
                  )}
                </div>

                {/* Remove button — only for ready items when not extracting */}
                {!isExtracting && item.status === "ready" && (
                  <button
                    onClick={() => removeFromStaged(item.fileId)}
                    className="flex-shrink-0 text-gray-300 hover:text-gray-500 text-xl leading-none"
                    title="Remove from staging"
                  >
                    ×
                  </button>
                )}
              </div>
            ))}
          </div>

          {/* Action buttons */}
          <div className="px-4 pb-4 bg-indigo-50/60">
            {!isExtracting && readyStagedCount > 0 && (
              <div className="flex flex-wrap gap-3">
                <button
                  onClick={handleExtractSeparately}
                  className="btn-extract px-5 py-2 text-white rounded-lg text-sm font-semibold disabled:opacity-50"
                  title="Extract tasks from each file independently"
                >
                  <span className="flex items-center gap-2">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                    Extract {readyStagedCount} File{readyStagedCount !== 1 ? "s" : ""} Separately
                  </span>
                </button>
                {readyStagedCount >= 2 && (
                  <button
                    onClick={handleMergeExtract}
                    className="btn-merge px-5 py-2 text-white rounded-lg text-sm font-semibold disabled:opacity-50"
                    title="Merge all file contents into one document before extracting — better for related files"
                  >
                    <span className="flex items-center gap-2">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16" />
                      </svg>
                      Merge {readyStagedCount} Files &amp; Extract as One
                    </span>
                  </button>
                )}
              </div>
            )}
            {isExtracting && (
              <button
                disabled
                className="flex items-center gap-2 px-5 py-2 bg-indigo-400 text-white rounded-lg text-sm font-medium cursor-not-allowed"
              >
                <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                </svg>
                Extracting…
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
