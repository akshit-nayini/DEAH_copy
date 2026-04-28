import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text, BigInteger, Float
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def generate_uuid() -> str:
    return str(uuid.uuid4())


class SourceFile(Base):
    __tablename__ = "req_agent_input"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    filename = Column(String(512), nullable=False)
    file_path = Column(String(1024), nullable=False)          # full path within the storage system
    storage_location = Column(String(64), nullable=False, default="gcs")  # gcs | local | drive
    uploaded_by = Column(String(256), nullable=True)
    upload_time = Column(DateTime, default=datetime.utcnow, nullable=False)
    status = Column(String(32), default="uploaded", nullable=False)  # uploaded | parsed | error
    file_size = Column(BigInteger, nullable=True)
    mime_type = Column(String(256), nullable=True)

    coverage_gaps = Column(Text, nullable=True)            # JSON coverage gap analysis
    tasks = relationship("Task", back_populates="source_file", lazy="select")


class Task(Base):
    __tablename__ = "req_agent_tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(32), unique=True, nullable=False)  # SRC-001 format
    task_heading = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    task_type = Column(String(32), nullable=False, default="task")  # bug|story|task|subtask
    user_name = Column(String(256), nullable=True)
    task_source = Column(String(512), nullable=True)
    source_file_id = Column(String(36), ForeignKey("req_agent_input.id"), nullable=True)
    location = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    status = Column(String(32), default="extracted", nullable=False)  # extracted|modified|pushed|deleted
    jira_id = Column(String(64), nullable=True)
    jira_url = Column(String(1024), nullable=True)
    raw_llm_json = Column(Text, nullable=True)

    # Structured Jira fields extracted during AI processing
    priority = Column(String(32), nullable=True)           # critical|high|medium|low
    reporter = Column(String(256), nullable=True)
    assignee = Column(String(256), nullable=True)          # developer assigned to implement
    sprint = Column(String(256), nullable=True)
    fix_version = Column(String(256), nullable=True)
    start_date = Column(DateTime, nullable=True)           # sprint/task start date
    due_date = Column(DateTime, nullable=True)             # deadline/sprint end date
    story_points = Column(Integer, nullable=True)
    acceptance_criteria = Column(Text, nullable=True)      # JSON-encoded list[str]
    confidence_score = Column(Float, nullable=True)        # 0.0–1.0 extraction confidence
    schedule_interval = Column(String(32), nullable=True)  # hourly|daily|weekly|on-demand

    gap_report = Column(Text, nullable=True)              # JSON gap analysis report

    source_file = relationship("SourceFile", back_populates="tasks")
