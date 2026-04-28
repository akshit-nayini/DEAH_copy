import React, { useState } from "react";
import FileManager from "./components/FileManager.jsx";
import TaskTable from "./components/TaskTable.jsx";

const TABS = [
  {
    id: "files",
    label: "Files & Upload",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
      </svg>
    ),
  },
  {
    id: "tasks",
    label: "Tasks & Review",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
      </svg>
    ),
  },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("files");
  const [taskRefreshKey, setTaskRefreshKey] = useState(0);
  const [selectedTasks, setSelectedTasks] = useState([]);
  const [extractedTaskIds, setExtractedTaskIds] = useState([]);
  const [llmProvider, setLlmProvider] = useState("claude-sdk");
  const [currentFileIds, setCurrentFileIds] = useState(() => {
    try {
      const saved = sessionStorage.getItem("currentFileIds");
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  function handleParsed(fileIds = [], taskIds = []) {
    sessionStorage.setItem("currentFileIds", JSON.stringify(fileIds));
    setCurrentFileIds(fileIds);
    setExtractedTaskIds(taskIds);
    setTaskRefreshKey((k) => k + 1);
    setActiveTab("tasks");
  }

  return (
    <div className="min-h-screen flex flex-col app-bg">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header className="header-gradient">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex items-center justify-between">
          {/* Brand */}
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-2xl brand-icon flex items-center justify-center shadow-xl flex-shrink-0">
              <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
                  d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
                />
              </svg>
            </div>
            <div>
              <h1 className="text-gray-900 text-xl font-bold tracking-tight">
                Requirement Agent
              </h1>
              <p className="text-gray-500 text-xs mt-0.5">
                Upload documents, extract requirements, and push directly to Jira
              </p>
            </div>
          </div>

          {/* AI Model selector */}
          <div className="flex items-center gap-3">
            <span className="text-gray-500 text-xs font-medium hidden sm:block">
              AI Model
            </span>
            <select
              value={llmProvider}
              onChange={(e) => setLlmProvider(e.target.value)}
              className="text-xs bg-gray-50 border border-gray-200 text-gray-700 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-400 cursor-pointer hover:bg-white/15 transition-colors"
            >
              <option value="claude-sdk">Claude SDK</option>
              <option value="claude">Claude (API)</option>
              <option value="mock">Mock</option>
            </select>
          </div>
        </div>
      </header>

      {/* ── Tab navigation ─────────────────────────────────────────────────── */}
      <nav className="bg-white/95 backdrop-blur-sm border-b border-gray-200 sticky top-0 z-30 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center gap-1 py-2">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 py-2 px-5 text-sm font-medium rounded-lg transition-all duration-200 focus:outline-none ${
                activeTab === tab.id
                  ? "tab-active"
                  : "text-gray-500 hover:text-gray-700 hover:bg-gray-100"
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>
      </nav>

      {/* ── Tab content ────────────────────────────────────────────────────── */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {activeTab === "files" && (
          <FileManager onParsed={handleParsed} llmProvider={llmProvider} />
        )}
        {activeTab === "tasks" && (
          <TaskTable
            key={taskRefreshKey}
            selectedTasks={selectedTasks}
            onSelectionChange={setSelectedTasks}
            currentFileIds={currentFileIds}
            extractedTaskIds={extractedTaskIds}
          />
        )}
      </main>
    </div>
  );
}
