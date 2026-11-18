from pydantic import BaseModel
from typing import Optional, List


class DatabaseHealthResponse(BaseModel):
    connected: bool
    database: str
    version: Optional[str] = None
    latency_ms: float
    error: Optional[str] = None


class SystemHealthResponse(BaseModel):
    status: str
    project: str
    tagline: str
    institution: str
    version: str
    environment: str
    database: DatabaseHealthResponse
    message: str
