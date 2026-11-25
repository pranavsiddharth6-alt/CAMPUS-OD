from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import UUID

from app.database.session import Base


class AdminAudit(Base):
    __tablename__ = "admin_audit"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    entity = Column(String(32), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    action = Column(String(16), nullable=False)
    details = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


def record_admin_change(db, actor_id, entity, entity_id, action, **details):
    db.add(AdminAudit(actor_id=actor_id, entity=entity, entity_id=entity_id, action=action, details=details))
