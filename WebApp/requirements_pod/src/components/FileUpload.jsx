import React, { useState, useRef, useEffect } from "react";
import { uploadFile, parseFile, parseMergedFiles, getFileProgress, listProjects } from "../api/client.js";

const STAGE_LABELS = {
  normalising:   "Reading & normalising",
  chunking:      "Splitting into chunks",
  extracting:    "Extracting tasks with AI",
  deduplicating: "Deduplicating",
  merging:       "Merging similar tasks",
  scoring:       "Scoring confidence",
  saving:        "Saving tasks",
  done:          "Complete!",
};

const ALLOWED_EXTENSIONS = ["pdf", "docx", "txt", "md", "vtt", "srt"];
const MAX_SIZE_MB = 50;

function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

// Per-file state shape: { file, status, uploadedRecord, error, parseProgress, parseStatus }
// status: idle | uploading | uploaded | upload_error | parsing | done | parse_error

export default function FileUpload({ onParsed, llmProvider }) {
  const [dragOver, setDragOver] = useState(false);
  const [fileQueue, setFileQueue] = useState([]); // array of per-file state objects
  const [projects, setProjects] = useState([]);
  const [projectName, setProjectName] = useState("");
  const [isNewProject, setIsNewProject] = useState(false);
  const [newProjectInput, setNewProjectInput] = useState("");
  const [globalError, setGlobalError] = useState(null);
  const [isExtracting, setIsExtracting] = useState(false);
  const fileInputRef = useRef(null);
  const pollRefs = useRef({});

  useEffect(() => {
    listProjects().then(setProjects).catch(() => {});
    return () => Object.values(pollRefs.current).forEach(clearInterval);
  }, []);

  const effectiveProject = isNewProject ? newProjectInput : projectName;

  function validateFile(file) {
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(ext))
      return `".${ext}" not allowed. Accepted: ${ALLOWED_EXTENSIONS.join(", ")}`;
    if (file.size > MAX_SIZE_MB * 1024 * 1024)
      return `Exceeds ${MAX_SIZE_MB} MB limit.`;
    return null;
  }

  function updateFile(name, patch) {
    setFileQueue((prev) => prev.map((f) => f.file.name === name ? { ...f, ...patch } : f));
  }

  async function addFiles(files) {
    const incoming = Array.from(files);
    const newEntries = [];
    for (const file of incoming) {
      const err = validateFile(file);
      newEntries.push({
        file,
        status: err ? "upload_error" : "idle",
        uploadedRecord: null,
        error: err,
        parseProgress: null,
        parseStatus: null,
      });
    }
    setFileQueue((prev) => {
      // skip duplicates by name
      const existingNames = new Set(prev.map((f) => f.file.name));
      return [...prev, ...newEntries.filter((e) => !existingNames.has(e.file.name))];
    });

    // auto-upload valid ones
    for (const entry of newEntries) {
      if (!entry.error) uploadOne(entry.file);
    }
  }

  async function uploadOne(file) {
    updateFile(file.name, { status: "uploading", error: null });
    try {
      const result = await uploadFile(file, null, effectiveProject);
      updateFile(file.name, { status: "uploaded", uploadedRecord: result });
    } catch (err) {
      updateFile(file.name, { status: "upload_error", error: err.message });
    }
  }

  function handleDrop(e) {
    e.preventDefault();
    setDragOver(false);
    addFiles(e.dataTransfer.files);
  }

  function handleInputChange(e) {
    addFiles(e.target.files);
    e.target.value = "";
  }

  function removeFile(name) {
    clearInterval(pollRefs.current[name]);
    delete pollRefs.current[name];
    setFileQueue((prev) => prev.filter((f) => f.file.name !== name));
  }

  function reset() {
    Object.values(pollRefs.current).forEach(clearInterval);
    pollRefs.current = {};
    setFileQueue([]);
    setGlobalError(null);
    setProjectName("");
    setIsNewProject(false);
    setNewProjectInput("");
  }

  async function handleExtractAll() {
    const toProcess = fileQueue.filter((f) => f.status === "uploaded" && f.uploadedRecord);
    if (toProcess.length === 0) return;

    setIsExtracting(true);
    setGlobalError(null);
    let allTasks = [];

    for (const entry of toProcess) {
      const { file, uploadedRecord } = entry;
      updateFile(file.name, { status: "parsing", parseProgress: { stage: null, pct: 0 } });

      // start progress poll
      const interval = setInterval(async () => {
        try {
          const data = await getFileProgress(uploadedRecord.id);
          if (data.stage) updateFile(file.name, { parseProgress: data });
        } catch { /* ignore */ }
      }, 800);
      pollRefs.current[file.name] = interval;

      try {
        const tasks = await parseFile(uploadedRecord.id, llmProvider);
        clearInterval(interval);
        delete pollRefs.current[file.name];

        if (tasks.length === 0) {
          updateFile(file.name, {
            status: "done",
            parseProgress: { stage: "done", pct: 100 },
            parseStatus: "warning",
          });
        } else {
          allTasks = [...allTasks, ...tasks];
          updateFile(file.name, {
            status: "done",
            parseProgress: { stage: "done", pct: 100 },
            parseStatus: `${tasks.length} tasks`,
          });
        }
      } catch (err) {
        clearInterval(interval);
        delete pollRefs.current[file.name];
        updateFile(file.name, {
          status: "parse_error",
          parseProgress: null,
          error: err.message,
        });
      }
    }

    setIsExtracting(false);
    if (allTasks.length > 0) {
      await new Promise((r) => setTimeout(r, 700));
      onParsed(allTasks);
    }
  }

  async function handleMergeExtract() {
    const toProcess = fileQueue.filter((f) => f.status === "uploaded" && f.uploadedRecord);
    if (toProcess.length === 0) return;

    setIsExtracting(true);
    setGlobalError(null);

    // Mark all as parsing
    for (const entry of toProcess) {
      updateFile(entry.file.name, { status: "parsing", parseProgress: { stage: null, pct: 0 } });
    }

    // Poll progress on the primary (first) file
    const primaryEntry = toProcess[0];
    const interval = setInterval(async () => {
      try {
        const data = await getFileProgress(primaryEntry.uploadedRecord.id);
        if (data.stage) {
          for (const entry of toProcess) {
            updateFile(entry.file.name, { parseProgress: data });
          }
        }
      } catch { /* ignore */ }
    }, 800);
    pollRefs.current["__merged__"] = interval;

    try {
      const fileIds = toProcess.map((e) => e.uploadedRecord.id);
      const tasks = await parseMergedFiles(fileIds, llmProvider);
      clearInterval(interval);
      delete pollRefs.current["__merged__"];

      const perFile = tasks.length > 0
        ? `merged (${tasks.length} tasks total)`
        : "warning";

      for (const entry of toProcess) {
        updateFile(entry.file.name, {
          status: "done",
          parseProgress: { stage: "done", pct: 100 },
          parseStatus: perFile,
        });
      }

      setIsExtracting(false);
      if (tasks.length > 0) {
        await new Promise((r) => setTimeout(r, 700));
        onParsed(tasks);
      }
    } catch (err) {
      clearInterval(interval);
      delete pollRefs.current["__merged__"];
      for (const entry of toProcess) {
        updateFile(entry.file.name, {
          status: "parse_error",
          parseProgress: null,
          error: err.message,
        });
      }
      setIsExtracting(false);
    }
  }

  const uploadedCount = fileQueue.filter((f) => f.status === "uploaded").length;
  const hasUploaded = uploadedCount > 0;
  const allDone = fileQueue.length > 0 && fileQueue.every((f) => ["done", "parse_error", "upload_error"].includes(f.status));

  return (
    <div className="max-w-3xl mx-auto">
      <h2 className="text-xl font-semibold text-gray-800 mb-4">Upload Requirements Documents</h2>

      {/* Project selector */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-1">Project / Product</label>
        {!isNewProject ? (
          <select
            value={projectName}
            onChange={(e) => {
              if (e.target.value === "__new__") { setIsNewProject(true); setProjectName(""); }
              else setProjectName(e.target.value);
            }}
            disabled={fileQueue.some((f) => f.status === "uploading") || isExtracting}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-gray-50"
          >
            <option value="">— Select a project —</option>
            {projects.map((p) => <option key={p} value={p}>{p}</option>)}
            <option value="__new__">+ Add new project...</option>
          </select>
        ) : (
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="Enter new project name..."
              value={newProjectInput}
              onChange={(e) => { setNewProjectInput(e.target.value); setProjectName(e.target.value); }}
              autoFocus
              className="flex-1 border border-blue-400 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            />
            <button
              onClick={() => { setIsNewProject(false); setNewProjectInput(""); setProjectName(""); }}
              className="px-3 py-2 text-sm border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        )}
        <p className="text-xs text-gray-400 mt-1">
          Storage path: <span className="font-mono">{effectiveProject || "<project>"} / date / file</span>
        </p>
      </div>

      {/* Drop zone */}
      <div
        onDrop={handleDrop}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onClick={() => fileInputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
          dragOver ? "border-blue-500 bg-blue-50" : "border-gray-300 bg-white hover:border-blue-400 hover:bg-blue-50"
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ALLOWED_EXTENSIONS.map((e) => `.${e}`).join(",")}
          className="hidden"
          onChange={handleInputChange}
        />
        <div className="text-gray-400 text-4xl mb-2">&#8679;</div>
        <p className="text-gray-600 font-medium">Drag & drop files here, or click to browse</p>
        <p className="text-sm text-gray-400 mt-1">
          Multiple files allowed · {ALLOWED_EXTENSIONS.join(", ")} · Max {MAX_SIZE_MB} MB each
        </p>
      </div>

      {/* File queue */}
      {fileQueue.length > 0 && (
        <div className="mt-4 border border-gray-200 rounded-xl overflow-hidden">
          <div className="bg-gray-50 px-4 py-2 flex items-center justify-between border-b border-gray-200">
            <span className="text-xs font-medium text-gray-500">
              {fileQueue.length} file{fileQueue.length !== 1 ? "s" : ""} · {uploadedCount} ready
            </span>
            {!isExtracting && (
              <button onClick={reset} className="text-xs text-gray-400 hover:text-gray-600">
                Clear all
              </button>
            )}
          </div>
          <ul className="divide-y divide-gray-100">
            {fileQueue.map((entry) => {
              const { file, status, error, parseProgress, parseStatus } = entry;
              return (
                <li key={file.name} className="px-4 py-3 flex items-center gap-3">
                  {/* Status icon */}
                  <span className="text-lg flex-shrink-0">
                    {status === "uploading" && <span className="text-blue-500 animate-pulse">⟳</span>}
                    {status === "uploaded" && <span className="text-green-500">✓</span>}
                    {status === "upload_error" && <span className="text-red-500">✗</span>}
                    {status === "parsing" && <span className="text-blue-500 animate-pulse">⟳</span>}
                    {status === "done" && parseStatus !== "warning" && <span className="text-green-600">✓</span>}
                    {status === "done" && parseStatus === "warning" && <span className="text-amber-500">⚠</span>}
                    {status === "parse_error" && <span className="text-red-500">✗</span>}
                    {status === "idle" && <span className="text-gray-300">○</span>}
                  </span>

                  {/* Name + size */}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-700 truncate">{file.name}</p>
                    <p className="text-xs text-gray-400">{formatBytes(file.size)}</p>
                    {error && <p className="text-xs text-red-500 mt-0.5">{error}</p>}
                    {parseProgress && parseProgress.stage && status === "parsing" && (
                      <div className="mt-1">
                        <div className="flex justify-between text-xs text-blue-600 mb-0.5">
                          <span>{STAGE_LABELS[parseProgress.stage] ?? "Processing…"}</span>
                          <span>{parseProgress.pct}%</span>
                        </div>
                        <div className="w-full bg-blue-100 rounded-full h-1">
                          <div
                            className="bg-blue-500 h-1 rounded-full transition-all duration-500"
                            style={{ width: `${parseProgress.pct}%` }}
                          />
                        </div>
                      </div>
                    )}
                    {status === "done" && parseStatus && parseStatus !== "warning" && (
                      <p className="text-xs text-green-600 mt-0.5">Extracted {parseStatus}</p>
                    )}
                    {status === "done" && parseStatus === "warning" && (
                      <p className="text-xs text-amber-600 mt-0.5">No tasks found in this file</p>
                    )}
                  </div>

                  {/* Remove button */}
                  {!isExtracting && (
                    <button
                      onClick={() => removeFile(file.name)}
                      className="text-gray-300 hover:text-gray-500 text-lg flex-shrink-0"
                    >
                      &times;
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {globalError && (
        <div className="mt-3 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
          {globalError}
        </div>
      )}

      {/* Actions */}
      <div className="mt-4 flex flex-wrap gap-3">
        {hasUploaded && !isExtracting && !allDone && (
          <>
            <button
              onClick={handleExtractAll}
              className="px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors"
              title="Extract tasks from each file independently, then combine results"
            >
              Extract from {uploadedCount} File{uploadedCount !== 1 ? "s" : ""} Separately
            </button>
            {uploadedCount > 1 && (
              <button
                onClick={handleMergeExtract}
                className="px-5 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
                title="Merge all file contents into one document before extraction — better for related files"
              >
                Merge {uploadedCount} Files &amp; Extract as One
              </button>
            )}
          </>
        )}
        {isExtracting && (
          <button disabled className="px-5 py-2 bg-blue-400 text-white rounded-lg text-sm font-medium cursor-not-allowed">
            Extracting...
          </button>
        )}
        {allDone && (
          <button
            onClick={reset}
            className="px-4 py-2 border border-gray-300 text-gray-600 rounded-lg text-sm hover:bg-gray-50 transition-colors"
          >
            Upload more files
          </button>
        )}
      </div>
    </div>
  );
}
