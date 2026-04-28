from enum import Enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class FileStatus(str, Enum):
    uploaded = "uploaded"
    parsed = "parsed"
    error = "error"


class FileOut(BaseModel):
    id: str
    filename: str
    file_path: str
    storage_location: str
    uploaded_by: Optional[str] = None
    upload_time: datetime
    status: FileStatus
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    coverage_gaps: Optional[str] = None          # JSON coverage gap analysis

    model_config = {"from_attributes": True}
