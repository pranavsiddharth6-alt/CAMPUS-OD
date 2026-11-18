"""Private local file storage service abstraction.

Sri Krishna Arts and Science College (SKASC) - Campus OD
Ensures uploaded files are safely stored outside public static directories
with SHA-256 checksum integrity.
"""
import os
import uuid
import hashlib
from typing import Tuple, Optional
from app.core.config import settings


class LocalStorageService:
    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir or os.path.join(settings.STORAGE_DIR, "uploads")
        os.makedirs(self.base_dir, exist_ok=True)

    def _generate_storage_key(self, filename: str) -> str:
        """Generate a collision-resistant unique storage key preserving extension."""
        ext = os.path.splitext(filename)[1].lower()
        unique_id = uuid.uuid4().hex
        return f"{unique_id}{ext}"

    def save_file(
        self,
        file_bytes: bytes,
        original_filename: str,
        content_type: str,
        uploaded_by_user_id: Optional[str] = None,
    ) -> dict:
        """Save binary file to private storage directory and return metadata."""
        if len(file_bytes) > settings.MAX_UPLOAD_SIZE_BYTES:
            raise ValueError(
                f"File size exceeds institutional limit of {settings.MAX_UPLOAD_SIZE_BYTES / (1024 * 1024):.1f} MB."
            )

        storage_key = self._generate_storage_key(original_filename)
        file_path = os.path.join(self.base_dir, storage_key)

        sha256 = hashlib.sha256(file_bytes).hexdigest()

        with open(file_path, "wb") as f:
            f.write(file_bytes)

        return {
            "storage_key": storage_key,
            "original_filename": original_filename,
            "content_type": content_type,
            "file_size_bytes": len(file_bytes),
            "sha256_checksum": sha256,
            "uploaded_by_user_id": uploaded_by_user_id,
            "storage_path": file_path,
        }

    def get_file(self, storage_key: str) -> Tuple[bytes, str]:
        """Retrieve binary file from private storage. Returns (bytes, file_path)."""
        file_path = os.path.join(self.base_dir, storage_key)
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Stored file with key '{storage_key}' not found.")

        with open(file_path, "rb") as f:
            content = f.read()

        return content, file_path

    def delete_file(self, storage_key: str) -> bool:
        """Delete file from private local storage."""
        file_path = os.path.join(self.base_dir, storage_key)
        if os.path.isfile(file_path):
            os.remove(file_path)
            return True
        return False


# Singleton instance of storage service
storage_service = LocalStorageService()
