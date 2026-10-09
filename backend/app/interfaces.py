"""Contracts reserved for later milestones. No engine or upload route is enabled."""
from typing import Protocol
from dataclasses import dataclass


@dataclass(frozen=True)
class MatchRequest:
    organization_id: str
    invoice_id: str
    requested_by: str


class MatchingEngine(Protocol):
    def run(self, request: MatchRequest) -> str:
        """Return the persisted, tenant-scoped MatchRun ID."""
        ...


class DocumentStorage(Protocol):
    def store(self, organization_id: str, filename: str, content: bytes) -> str:
        """Future implementations must validate magic bytes, allowlisted MIME, and size before storage."""
        ...
