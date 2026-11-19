"""Private bytes and transaction support shared by OD forms and evidence."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models.evidence import StoredFile
from app.services.storage import LocalStorageService

_logger = logging.getLogger(__name__)


class ApplicationError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class PrivateUpload:
    filename: str
    media_type: str
    content: bytes = field(repr=False)


@contextmanager
def write_with_uploads(
    sessions: sessionmaker[Session], storage: LocalStorageService,
) -> Iterator[tuple[Session, list[str]]]:
    keys: list[str] = []
    commit_started = False
    try:
        with sessions.begin() as db:
            yield db, keys
            commit_started = True
    except Exception as error:
        # Retain files if the database may have committed before the connection failed.
        if not commit_started or isinstance(error, IntegrityError):
            for key in keys:
                try:
                    storage.delete_file(key)
                except OSError:
                    _logger.warning("Could not clean up a private OD upload after rollback.")
        elif keys:
            _logger.warning("Private OD uploads retained after an uncertain database commit.")
        raise


def store_upload(storage: LocalStorageService, item: PrivateUpload, owner: UUID, keys: list[str]) -> StoredFile:
    saved = storage.save_file(item.content, item.filename, item.media_type, str(owner))
    keys.append(saved["storage_key"])
    return StoredFile(
        storage_key=saved["storage_key"], original_filename=item.filename, content_type=item.media_type,
        file_size_bytes=saved["file_size_bytes"], sha256_checksum=saved["sha256_checksum"],
        uploaded_by_user_id=owner,
    )


def read_upload(storage: LocalStorageService, row: StoredFile) -> PrivateUpload:
    try:
        content, _ = storage.get_file(row.storage_key)
    except FileNotFoundError:
        raise ApplicationError(404, "Document not found.") from None
    if len(content) != row.file_size_bytes or sha256(content).hexdigest() != row.sha256_checksum:
        raise ApplicationError(409, "The stored document failed its integrity check.")
    return PrivateUpload(row.original_filename, row.content_type, content)
