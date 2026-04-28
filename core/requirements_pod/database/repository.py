import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from core.requirements_pod.database.models import SourceFile, Task
from core.requirements_pod.database.schemas.task import TaskUpdate
from core.requirements_pod.database.schemas.file import FileStatus


def create_source_file(
    db: Session,
    filename: str,
    file_path: str,
    storage_location: str,
    uploaded_by: Optional[str],
    file_size: Optional[int],
    mime_type: Optional[str],
) -> SourceFile:
    file_record = SourceFile(
        id=str(uuid.uuid4()),
        filename=filename,
        file_path=file_path,
        storage_location=storage_location,
        uploaded_by=uploaded_by,
        upload_time=datetime.utcnow(),
        status=FileStatus.uploaded.value,
        file_size=file_size,
        mime_type=mime_type,
    )
    db.add(file_record)
    db.commit()
    db.refresh(file_record)
    return file_record


def get_source_file(db: Session, file_id: str) -> Optional[SourceFile]:
    return db.get(SourceFile, file_id)


def get_source_file_by_path(db: Session, path: str) -> Optional[SourceFile]:
    return db.execute(
        select(SourceFile).where(SourceFile.file_path == path)
    ).scalar_one_or_none()


def update_source_file_status(db: Session, file_id: str, status: str) -> Optional[SourceFile]:
    file_record = db.get(SourceFile, file_id)
    if file_record is None:
        return None
    file_record.status = status
    db.commit()
    db.refresh(file_record)
    return file_record


def get_next_task_id(db: Session) -> str:
    """Return the next SRC-NNN id by reading the current MAX from the DB."""
    result = db.execute(
        select(func.max(Task.task_id)).where(Task.task_id.like("SRC-%"))
    ).scalar()
    if result:
        try:
            current_num = int(result.split("-")[1])
        except (ValueError, IndexError):
            current_num = 0
    else:
        current_num = 0
    return f"SRC-{current_num + 1:03d}"


def create_task(
    db: Session,
    task_heading: str,
    description: Optional[str],
    task_type: str,
    user_name: Optional[str],
    task_source: Optional[str],
    source_file_id: Optional[str],
    location: Optional[str],
    raw_llm_json: Optional[str] = None,
    priority: Optional[str] = None,
    reporter: Optional[str] = None,
    sprint: Optional[str] = None,
    fix_version: Optional[str] = None,
    story_points: Optional[int] = None,
    acceptance_criteria: Optional[str] = None,
    confidence_score: Optional[float] = None,
    schedule_interval: Optional[str] = None,
    assignee: Optional[str] = None,
    start_date: Optional[datetime] = None,
    due_date: Optional[datetime] = None,
) -> Task:
    """Create a task, retrying up to 5 times if a concurrent insert steals the ID."""
    for attempt in range(5):
        task_id = get_next_task_id(db)
        now = datetime.utcnow()
        task = Task(
            id=str(uuid.uuid4()),
            task_id=task_id,
            task_heading=task_heading,
            description=description,
            task_type=task_type,
            user_name=user_name,
            task_source=task_source,
            source_file_id=source_file_id,
            location=location,
            created_at=now,
            updated_at=now,
            status="extracted",
            raw_llm_json=raw_llm_json,
            priority=priority,
            reporter=reporter,
            sprint=sprint,
            fix_version=fix_version,
            story_points=story_points,
            acceptance_criteria=acceptance_criteria,
            confidence_score=confidence_score,
            schedule_interval=schedule_interval,
            assignee=assignee,
            start_date=start_date,
            due_date=due_date,
        )
        db.add(task)
        try:
            db.commit()
            db.refresh(task)
            return task
        except IntegrityError:
            db.rollback()
            if attempt == 4:
                raise
    raise RuntimeError("Failed to generate a unique task ID after 5 attempts")


def get_task(db: Session, task_id: str) -> Optional[Task]:
    return db.execute(select(Task).where(Task.task_id == task_id)).scalar_one_or_none()


def list_tasks(
    db: Session,
    source_file: Optional[str] = None,
    user_name: Optional[str] = None,
    status: Optional[str] = None,
) -> list[Task]:
    query = select(Task)
    if source_file:
        query = query.where(Task.source_file_id == source_file)
    if user_name:
        query = query.where(Task.user_name == user_name)
    if status:
        query = query.where(Task.status == status)
    else:
        query = query.where(Task.status != "deleted")
    result = db.execute(query).scalars().all()
    return list(result)


def update_task(db: Session, task_id: str, data: TaskUpdate) -> Optional[Task]:
    task = get_task(db, task_id)
    if task is None:
        return None
    update_data = data.model_dump(exclude_unset=True)
    changed = False
    for field, value in update_data.items():
        if getattr(task, field, None) != value:
            setattr(task, field, value)
            changed = True
    if changed and task.status not in ("pushed", "deleted", "modified"):
        task.status = "modified"
    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task


def soft_delete_task(db: Session, task_id: str) -> Optional[Task]:
    task = get_task(db, task_id)
    if task is None:
        return None
    task.status = "deleted"
    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task


def bulk_get_tasks(db: Session, task_ids: list[str]) -> list[Task]:
    result = db.execute(select(Task).where(Task.task_id.in_(task_ids))).scalars().all()
    return list(result)


def delete_source_file(db: Session, file_id: str) -> None:
    """Hard-delete a source file record, nullifying FK on associated tasks first."""
    from sqlalchemy import update as sql_update
    db.execute(sql_update(Task).where(Task.source_file_id == file_id).values(source_file_id=None))
    file_record = db.get(SourceFile, file_id)
    if file_record:
        db.delete(file_record)
    db.commit()


def clear_unpushed_tasks_for_file(db: Session, file_id: str) -> int:
    """Hard-delete all non-pushed tasks for a file before re-extraction. Returns count deleted."""
    tasks = db.execute(
        select(Task).where(Task.source_file_id == file_id, Task.status != "pushed")
    ).scalars().all()
    count = len(tasks)
    for t in tasks:
        db.delete(t)
    db.commit()
    return count


def reset_gap_reports_for_file(db: Session, file_id: str) -> int:
    """Clear gap_report for all non-deleted tasks belonging to a file. Returns count updated."""
    from sqlalchemy import update as sql_update
    result = db.execute(
        sql_update(Task)
        .where(Task.source_file_id == file_id, Task.status != "deleted")
        .values(gap_report=None)
    )
    db.commit()
    return result.rowcount


def get_all_task_ids_for_file(db: Session, file_id: str) -> list[str]:
    """Return task_ids for all non-deleted tasks in a file (all types)."""
    tasks = db.execute(
        select(Task).where(Task.source_file_id == file_id, Task.status != "deleted")
    ).scalars().all()
    return [t.task_id for t in tasks]


def update_task_gap_report(db: Session, task_id: str, gap_report_json: str) -> Optional[Task]:
    task = get_task(db, task_id)
    if task is None:
        return None
    task.gap_report = gap_report_json
    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task


def update_source_file_coverage_gaps(db: Session, file_id: str, coverage_gaps_json: str) -> Optional[SourceFile]:
    file_record = db.get(SourceFile, file_id)
    if file_record is None:
        return None
    file_record.coverage_gaps = coverage_gaps_json
    db.commit()
    db.refresh(file_record)
    return file_record


def update_task_jira(db: Session, task_id: str, jira_id: str, jira_url: str) -> Optional[Task]:
    task = get_task(db, task_id)
    if task is None:
        return None
    task.jira_id = jira_id
    task.jira_url = jira_url
    task.status = "pushed"
    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task
