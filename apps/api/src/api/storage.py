from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class ArtifactStorage(ABC):
    @abstractmethod
    def write_text(self, artifact_dir: str, relative_path: str, content: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def list_files(self, artifact_dir: str) -> list[str]:
        raise NotImplementedError


class LocalFilesystemStorage(ArtifactStorage):
    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def write_text(self, artifact_dir: str, relative_path: str, content: str) -> str:
        target_dir = self.base_dir / artifact_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target)

    def list_files(self, artifact_dir: str) -> list[str]:
        target_dir = self.base_dir / artifact_dir
        if not target_dir.exists():
            return []
        return [str(p.relative_to(target_dir)) for p in target_dir.rglob("*") if p.is_file()]


class S3CompatibleStorage(ArtifactStorage):
    """Placeholder interface for future object storage support."""

    def __init__(self, bucket: str, endpoint_url: str | None = None) -> None:
        self.bucket = bucket
        self.endpoint_url = endpoint_url

    def write_text(self, artifact_dir: str, relative_path: str, content: str) -> str:
        raise NotImplementedError("S3 storage is not implemented yet")

    def list_files(self, artifact_dir: str) -> list[str]:
        raise NotImplementedError("S3 storage is not implemented yet")
