"""Private local storage. Keys are generated internally, never derived from filenames."""
import re
import secrets
from pathlib import Path
from typing import Protocol
from ...config import settings


class Storage(Protocol):
    def put(self, organization_id: str, content: bytes) -> str: ...
    def path(self, organization_id: str, key: str) -> Path: ...
    def delete(self, organization_id: str, key: str) -> None: ...


class LocalStorage:
    def __init__(self, root=None):
        self.root = Path(root or settings.document_storage_path).resolve()

    def path(self, organization_id, key):
        if not re.fullmatch(r'[0-9a-f-]{36}', organization_id) or not re.fullmatch(r'[0-9a-f]{48}', key):
            raise ValueError('Invalid storage identifier')
        candidate = (self.root / organization_id / key).resolve()
        if not candidate.is_relative_to(self.root) or candidate.parent != self.root / organization_id:
            raise ValueError('Invalid storage identifier')
        return candidate

    def put(self, organization_id, content):
        key = secrets.token_hex(24)
        path = self.path(organization_id, key)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open('xb') as stream:
            stream.write(content)
        path.chmod(0o600)
        return key

    def delete(self, organization_id, key):
        self.path(organization_id, key).unlink(missing_ok=True)
