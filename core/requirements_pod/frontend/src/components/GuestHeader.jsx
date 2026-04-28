import React, { useState, useRef, useEffect } from "react";

export default function GuestHeader({ guestName, onNameChange, llmProvider, onLlmProviderChange }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(guestName);
  const inputRef = useRef(null);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  function startEdit() {
    setDraft(guestName);
    setEditing(true);
  }

  function commitEdit() {
    const trimmed = draft.trim();
    if (trimmed) {
      onNameChange(trimmed);
    }
    setEditing(false);
  }

  function handleKeyDown(e) {
    if (e.key === "Enter") commitEdit();
    if (e.key === "Escape") setEditing(false);
  }

  return (
    <header className="bg-blue-700 text-white shadow-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-2xl font-bold tracking-tight">TaskFlow AI</span>
          <span className="hidden sm:inline text-blue-200 text-sm">Requirements Extraction</span>
        </div>

        <div className="flex items-center gap-4">
          {/* LLM provider toggle */}
          <div className="flex items-center gap-2 text-sm">
            <span className="text-blue-200 hidden sm:inline">LLM:</span>
            <div className="flex rounded-full overflow-hidden border border-blue-400 text-xs font-medium">
              <button
                onClick={() => onLlmProviderChange("claude")}
                className={`px-3 py-1 transition-colors ${
                  llmProvider === "claude"
                    ? "bg-white text-blue-700"
                    : "bg-transparent text-blue-200 hover:text-white"
                }`}
              >
                Claude
              </button>
              <button
                onClick={() => onLlmProviderChange("mock")}
                className={`px-3 py-1 transition-colors ${
                  llmProvider === "mock"
                    ? "bg-white text-blue-700"
                    : "bg-transparent text-blue-200 hover:text-white"
                }`}
              >
                Mock
              </button>
            </div>
          </div>

          <div className="flex items-center gap-2 text-sm">
          <span className="text-blue-200">Signed in as:</span>
          {editing ? (
            <input
              ref={inputRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commitEdit}
              onKeyDown={handleKeyDown}
              className="bg-blue-600 border border-blue-400 rounded px-2 py-1 text-white placeholder-blue-300 focus:outline-none focus:ring-2 focus:ring-blue-300 w-40"
              placeholder="Enter your name"
            />
          ) : (
            <button
              onClick={startEdit}
              title="Click to edit your name"
              className="font-semibold underline decoration-dotted hover:text-blue-100 transition-colors cursor-pointer focus:outline-none"
            >
              {guestName || "Guest (click to set name)"}
            </button>
          )}
          </div>
        </div>
      </div>
    </header>
  );
}
