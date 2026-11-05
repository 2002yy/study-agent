"""Requests and responses for text-only local skill management."""

from pydantic import BaseModel, StrictBool


class SkillImportRequest(BaseModel):
    content: str


class SkillEnabledRequest(BaseModel):
    enabled: StrictBool


class SkillResponse(BaseModel):
    id: str
    name: str
    description: str
    content: str
    enabled: bool


class SkillListResponse(BaseModel):
    skills: list[SkillResponse]
