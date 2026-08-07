from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.analytics import AnalyticsFilterOption


EnterpriseAgentIntent = Literal[
    "daily_brief",
    "backlog_risk",
    "service_quality",
    "inventory_risk",
    "integration_health",
]


class EnterpriseAgentRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    intent: EnterpriseAgentIntent | None = None
    from_date: date | None = None
    to_date: date | None = None
    engineer_id: int | None = Field(default=None, gt=0)
    job_type: str | None = Field(default=None, max_length=120)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("question must contain at least three non-space characters")
        return normalized

    @model_validator(mode="after")
    def validate_period(self):
        if (self.from_date is None) != (self.to_date is None):
            raise ValueError("from_date and to_date must be provided together")
        if self.from_date and self.to_date:
            if self.to_date < self.from_date:
                raise ValueError("to_date must be on or after from_date")
            if (self.to_date - self.from_date).days + 1 > 366:
                raise ValueError("Agent analysis range cannot exceed 366 days")
        return self


class EnterpriseAgentEvidenceRead(BaseModel):
    code: str
    label: str
    value: int | float | str
    unit: str
    source: str
    definition: str


class EnterpriseAgentFindingRead(BaseModel):
    code: str
    severity: Literal["info", "warning", "critical"]
    title: str
    summary: str
    recommendation: str
    evidence: list[EnterpriseAgentEvidenceRead] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)


class EnterpriseAgentFilterRead(BaseModel):
    from_date: date
    to_date: date
    engineer_id: int | None = None
    job_type: str | None = None
    engineers: list[AnalyticsFilterOption] = Field(default_factory=list)
    job_types: list[AnalyticsFilterOption] = Field(default_factory=list)


class EnterpriseAgentGuardrailsRead(BaseModel):
    read_only: bool = True
    mutations_performed: list[str] = Field(default_factory=list)
    raw_question_retained: bool = False
    cross_tenant_access: bool = False
    external_model_called: bool = False


class EnterpriseAgentResponse(BaseModel):
    run_id: int
    generated_at: datetime
    mode: Literal["deterministic_evidence"] = "deterministic_evidence"
    intent: EnterpriseAgentIntent
    summary: str
    priority: Literal["normal", "warning", "critical"]
    confidence: float = Field(ge=0, le=1)
    filters: EnterpriseAgentFilterRead
    findings: list[EnterpriseAgentFindingRead] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    guardrails: EnterpriseAgentGuardrailsRead = Field(
        default_factory=EnterpriseAgentGuardrailsRead
    )


class EnterpriseAgentRunRead(BaseModel):
    id: int
    user_id: int | None = None
    intent: EnterpriseAgentIntent
    question_sha256: str
    question_length: int
    filters: dict
    tools_used: list[str]
    finding_count: int
    duration_ms: int
    status: str
    error_code: str | None = None
    created_at: datetime


class EnterpriseAgentOptionsRead(BaseModel):
    intents: list[dict[str, str]]
    engineers: list[AnalyticsFilterOption] = Field(default_factory=list)
    job_types: list[AnalyticsFilterOption] = Field(default_factory=list)
