from enum import Enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class TaskType(str, Enum):
    bug = "bug"
    story = "story"
    task = "task"
    subtask = "subtask"


class TaskStatus(str, Enum):
    extracted = "extracted"
    modified = "modified"
    pushed = "pushed"
    deleted = "deleted"


class TaskBase(BaseModel):
    task_heading: str
    description: Optional[str] = None
    task_type: TaskType = TaskType.task
    user_name: Optional[str] = None
    location: Optional[str] = None
    priority: Optional[str] = None          # critical|high|medium|low
    reporter: Optional[str] = None
    assignee: Optional[str] = None          # developer implementing the task
    sprint: Optional[str] = None
    fix_version: Optional[str] = None
    start_date: Optional[datetime] = None   # sprint/task start date
    due_date: Optional[datetime] = None     # deadline/sprint end date
    story_points: Optional[int] = None
    acceptance_criteria: Optional[str] = None  # JSON-encoded list[str]
    schedule_interval: Optional[str] = None    # hourly|daily|weekly|on-demand


class TaskCreate(TaskBase):
    task_source: Optional[str] = None
    source_file_id: Optional[str] = None


class TaskUpdate(BaseModel):
    task_heading: Optional[str] = None
    description: Optional[str] = None
    task_type: Optional[TaskType] = None
    user_name: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[str] = None
    reporter: Optional[str] = None
    assignee: Optional[str] = None
    sprint: Optional[str] = None
    fix_version: Optional[str] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    story_points: Optional[int] = None
    acceptance_criteria: Optional[str] = None
    schedule_interval: Optional[str] = None


class TaskOut(TaskBase):
    id: str
    task_id: str
    task_source: Optional[str] = None
    source_file_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    status: TaskStatus
    jira_id: Optional[str] = None
    jira_url: Optional[str] = None
    confidence_score: Optional[float] = None
    gap_report: Optional[str] = None              # JSON gap analysis report

    model_config = {"from_attributes": True}