const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api/v1";

async function request(method, path, options = {}) {
  const { body, params, isFormData } = options;
  let url = `${API_BASE}${path}`;

  if (params) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
    ).toString();
    if (qs) url += `?${qs}`;
  }

  const headers = {};
  let requestBody;

  if (isFormData) {
    requestBody = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    requestBody = JSON.stringify(body);
  }

  const response = await fetch(url, {
    method,
    headers,
    body: requestBody,
  });

  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    let code = null;
    try {
      const errJson = await response.json();
      message = errJson.detail?.detail || errJson.detail || message;
      code = errJson.detail?.code || null;
    } catch {
      // ignore parse failure
    }
    const err = new Error(message);
    err.code = code;
    err.status = response.status;
    err.endpoint = `${method} ${path}`;
    throw err;
  }

  return response;
}

async function requestJson(method, path, options = {}) {
  const response = await request(method, path, options);
  return response.json();
}

async function requestBlob(method, path, options = {}) {
  const response = await request(method, path, options);
  return response.blob();
}

// ── Files ──────────────────────────────────────────────────────────────────

export async function listProjects() {
  return requestJson("GET", "/files/projects");
}

export async function uploadFile(file, userName, projectName) {
  const formData = new FormData();
  formData.append("file", file);
  if (userName) formData.append("user_name", userName);
  if (projectName) formData.append("project_name", projectName);
  return requestJson("POST", "/files/upload", { body: formData, isFormData: true });
}

export async function listFiles(projectName = "") {
  return requestJson("GET", "/files/list", { params: { project_name: projectName } });
}

export async function findFileByPath(path) {
  return requestJson("GET", "/files/find", { params: { path } });
}

export async function registerFile(filePath, userName, fileSize, storageLocation = "gcs") {
  return requestJson("POST", "/files/register", {
    body: { file_path: filePath, storage_location: storageLocation, user_name: userName || null, file_size: fileSize || null },
  });
}

export async function parseFile(fileId, llmProvider) {
  const params = llmProvider ? { llm_provider: llmProvider } : {};
  return requestJson("POST", `/files/${fileId}/parse`, { params });
}

export async function parseMergedFiles(fileIds, llmProvider) {
  const params = llmProvider ? { llm_provider: llmProvider } : {};
  return requestJson("POST", "/files/parse-merged", { body: { file_ids: fileIds }, params });
}

export async function getFileStatus(fileId) {
  return requestJson("GET", `/files/${fileId}/status`);
}

export async function getFileProgress(fileId) {
  return requestJson("GET", `/files/${fileId}/progress`);
}

export async function deleteFile(storagePath) {
  return request("DELETE", "/files/storage", { params: { path: storagePath } });
}

// ── Tasks ──────────────────────────────────────────────────────────────────

export async function listTasks(filters = {}) {
  return requestJson("GET", "/tasks", { params: filters });
}

export async function getTask(taskId) {
  return requestJson("GET", `/tasks/${taskId}`);
}

export async function updateTask(taskId, data) {
  return requestJson("PATCH", `/tasks/${taskId}`, { body: data });
}

export async function deleteTask(taskId) {
  return requestJson("DELETE", `/tasks/${taskId}`);
}

export async function exportTasks(taskIds, format = "json") {
  return requestBlob("POST", "/tasks/export", { body: { task_ids: taskIds, format } });
}

export async function pushToJira(taskIds) {
  return requestJson("POST", "/tasks/jira-push", { body: { task_ids: taskIds } });
}

export async function pushToJiraLinked(storyTaskId, taskIds) {
  return requestJson("POST", "/tasks/jira-push-linked", {
    body: { story_task_id: storyTaskId, task_ids: taskIds },
  });
}

// ── Gap Analysis ───────────────────────────────────────────────────────────────

export async function getTaskGaps(taskId) {
  return requestJson("GET", `/tasks/${taskId}/gaps`);
}

export async function applyGapSuggestion(taskId, field, value) {
  return requestJson("POST", `/tasks/${taskId}/gaps/apply`, { body: { field, value } });
}

export async function getFileCoverageGaps(fileId) {
  return requestJson("GET", `/files/${fileId}/coverage-gaps`);
}

export async function getGapProgress(fileId) {
  return requestJson("GET", `/files/${fileId}/gap-progress`);
}

export async function reanalyzeGaps(fileId) {
  return requestJson("POST", `/files/${fileId}/gaps/reanalyze`);
}
