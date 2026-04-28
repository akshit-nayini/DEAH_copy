import React, { useState } from "react";
import FileManager from "./components/FileManager.jsx";
import TaskTable from "./components/TaskTable.jsx";

const TABS = [
  { id: "files", label: "Files" },
  { id: "tasks", label: "Tasks" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("files");
  const [taskRefreshKey, setTaskRefreshKey] = useState(0);
  const [selectedTasks, setSelectedTasks] = useState([]);
  const [llmProvider, setLlmProvider] = useState("claude-sdk");
  const [currentFileIds, setCurrentFileIds] = useState([]);

  function handleParsed(fileIds = []) {
    setCurrentFileIds(fileIds);
    setTaskRefreshKey((k) => k + 1);
    setActiveTab("tasks");
  }

  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between h-14">
          <span className="text-base font-semibold text-gray-800">
            TaskFlow AI — Requirements Agent
          </span>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">LLM:</span>
            <select
              value={llmProvider}
              onChange={(e) => setLlmProvider(e.target.value)}
              className="text-xs border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
            >
              <option value="claude-sdk">Claude SDK</option>
              <option value="claude">Claude (API)</option>
              <option value="mock">Mock</option>
            </select>
          </div>
        </div>
      </header>

      {/* Tab navigation */}
      <nav className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex space-x-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`py-3 px-5 text-sm font-medium border-b-2 transition-colors focus:outline-none ${
                activeTab === tab.id
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </nav>

      {/* Tab content */}
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
          />
        )}
      </main>
    </div>
  );
}
