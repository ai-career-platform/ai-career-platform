"""Private storage boundary with the user-approved dedicated directory adapter.

put must atomically create a private quarantined object, never overwrite one.
delete must be idempotent. Adapters must translate provider errors to AppError
without logging object keys, filenames or contents. No public URL API exists.
"""
from typing import Protocol
import os
import re
from pathlib import Path

from app.core.errors import AppError, ErrorCode


class DocumentStorage(Protocol):
    def put(self, key: str, content: bytes) -> None: ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class UnavailableDocumentStorage:
    def put(self, key, content):
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)

    def read(self, key):
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)

    def delete(self, key):
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)


class DirectoryDocumentStorage:
    """Dedicated private directory. Requires a noexec volume in deployment.

    Directory fd + O_NOFOLLOW prevent symlink traversal. Object names are never
    derived from uploaded filenames. A partial write is removed before return.
    """
    def __init__(self, root: str):
        path = Path(root)
        if not path.is_absolute() or path.is_symlink():
            raise ValueError("DOCUMENT_STORAGE_ROOT must be an absolute private directory")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not path.is_dir() or path.stat().st_mode & 0o077:
            raise ValueError("DOCUMENT_STORAGE_ROOT must have mode 0700")
        self.root = path

    def _directory(self):
        return os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    @staticmethod
    def _key(key):
        if not re.fullmatch(r"[0-9a-f]{32,64}", key):
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
        return key

    def put(self, key, content):
        key = self._key(key)
        try:
            directory = self._directory()
            try:
                fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
                except BaseException:
                    os.unlink(key, dir_fd=directory)
                    raise
            finally:
                os.close(directory)
        except OSError:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from None

    def read(self, key):
        key = self._key(key)
        try:
            directory = self._directory()
            try:
                fd = os.open(key, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                with os.fdopen(fd, "rb") as stream:
                    return stream.read(10 * 1024 * 1024 + 1)
            finally:
                os.close(directory)
        except OSError:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from None

    def delete(self, key):
        key = self._key(key)
        try:
            directory = self._directory()
            try:
                try:
                    os.unlink(key, dir_fd=directory)
                except FileNotFoundError:
                    pass
            finally:
                os.close(directory)
        except OSError:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from None


class DocumentDerivativePurger(Protocol):
    def purge(self, document_id) -> None:
        """Idempotently purge analyses/chunks/index/citations before metadata removal."""
        ...
