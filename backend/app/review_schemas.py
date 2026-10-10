from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Versioned(Strict):
    version: int = Field(ge=1)


class AssignException(Versioned):
    user_id: str


class ExceptionAction(Versioned):
    reason: str = Field(min_length=3, max_length=2000)


class ApprovalAction(Versioned):
    reason: str | None = Field(default=None, max_length=2000)


class CommentInput(Strict):
    entity_type: Literal['exception', 'invoice']
    entity_id: str
    body: str = Field(min_length=1, max_length=4000)


class PolicyInput(Strict):
    segregation_of_duties: bool = False


class RoleFilter(Strict):
    role: Literal['member', 'organization_admin', 'procurement_reviewer', 'finance_approver', 'viewer']
