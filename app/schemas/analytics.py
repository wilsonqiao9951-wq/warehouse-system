from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AnalyticsPeriodRead(BaseModel):
    from_date: date
    to_date: date
    previous_from_date: date
    previous_to_date: date
    days: int = Field(ge=1)
    grain: str
    timezone: str = "UTC"


class AnalyticsFilterOption(BaseModel):
    value: str
    label: str


class AnalyticsFilterRead(BaseModel):
    engineer_id: int | None = None
    job_type: str | None = None
    engineers: list[AnalyticsFilterOption] = Field(default_factory=list)
    job_types: list[AnalyticsFilterOption] = Field(default_factory=list)


class AnalyticsKpiRead(BaseModel):
    code: str
    label: str
    value: float | None = None
    unit: str
    previous_value: float | None = None
    delta_percent: float | None = None
    definition: str


class AnalyticsTrendPointRead(BaseModel):
    bucket_start: date
    label: str
    created_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    first_time_fix_rate: float | None = Field(default=None, ge=0, le=1)
    rework_rate: float | None = Field(default=None, ge=0, le=1)
    average_repair_minutes: float | None = Field(default=None, ge=0)
    revenue: float
    contribution: float


class AnalyticsEngineerRowRead(BaseModel):
    engineer_id: int | None = None
    engineer_name: str
    completed_count: int = Field(ge=0)
    first_time_fix_rate: float | None = Field(default=None, ge=0, le=1)
    first_time_fix_coverage: float = Field(ge=0, le=1)
    rework_rate: float = Field(ge=0, le=1)
    average_repair_minutes: float | None = Field(default=None, ge=0)
    parts_cost: float
    revenue: float
    contribution: float


class AnalyticsJobTypeRowRead(BaseModel):
    job_type: str
    completed_count: int = Field(ge=0)
    first_time_fix_rate: float | None = Field(default=None, ge=0, le=1)
    rework_rate: float = Field(ge=0, le=1)
    average_repair_minutes: float | None = Field(default=None, ge=0)
    contribution: float


class AnalyticsRegionRowRead(BaseModel):
    region_id: int
    region_code: str
    region_name: str
    warehouse_count: int = Field(ge=0)
    stock_quantity: int
    stock_value: float
    low_stock_sku_count: int = Field(ge=0)
    completed_work_orders_with_usage: int = Field(ge=0)
    consumed_quantity: int = Field(ge=0)
    consumed_parts_cost: float


class AnalyticsDataQualityRead(BaseModel):
    completed_work_orders: int = Field(ge=0)
    first_time_fix_labeled: int = Field(ge=0)
    first_time_fix_coverage: float = Field(ge=0, le=1)
    repair_duration_labeled: int = Field(ge=0)
    repair_duration_coverage: float = Field(ge=0, le=1)
    engineer_attributed: int = Field(ge=0)
    engineer_attribution_coverage: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)


class AnalyticsSourceFreshnessRead(BaseModel):
    work_orders_updated_at: datetime | None = None
    work_order_parts_updated_at: datetime | None = None
    inventory_transactions_updated_at: datetime | None = None


class EnterpriseAnalyticsRead(BaseModel):
    generated_at: datetime
    period: AnalyticsPeriodRead
    filters: AnalyticsFilterRead
    kpis: list[AnalyticsKpiRead]
    trend: list[AnalyticsTrendPointRead]
    engineers: list[AnalyticsEngineerRowRead]
    job_types: list[AnalyticsJobTypeRowRead]
    regions: list[AnalyticsRegionRowRead]
    data_quality: AnalyticsDataQualityRead
    source_freshness: AnalyticsSourceFreshnessRead


class ProfitSnapshotSummaryRead(BaseModel):
    completed_work_orders: int = Field(ge=0)
    snapshot_count: int = Field(ge=0)
    missing_snapshot_count: int = Field(ge=0)
    coverage_rate: float = Field(ge=0, le=1)
    revenue: float
    labor_cost: float
    parts_cost: float
    profit: float
    margin_rate: float | None = None


class ProfitSnapshotDailyRead(BaseModel):
    snapshot_date: date
    completed_count: int = Field(ge=0)
    revenue: float
    labor_cost: float
    parts_cost: float
    profit: float


class ProfitSnapshotRankingRead(BaseModel):
    dimension: Literal["engineer", "region", "machine_type"]
    key: str
    label: str
    completed_count: int = Field(ge=0)
    revenue: float
    labor_cost: float
    parts_cost: float
    profit: float
    margin_rate: float | None = None


class ProfitSnapshotDashboardRead(BaseModel):
    generated_at: datetime
    from_date: date
    to_date: date
    summary: ProfitSnapshotSummaryRead
    daily: list[ProfitSnapshotDailyRead]
    engineers: list[ProfitSnapshotRankingRead]
    regions: list[ProfitSnapshotRankingRead]
    machine_types: list[ProfitSnapshotRankingRead]
    last_captured_at: datetime | None = None


class ProfitSnapshotBackfillRequest(BaseModel):
    from_date: date | None = None
    to_date: date | None = None
    after_work_order_id: int | None = Field(default=None, ge=1)
    limit: int = Field(default=500, ge=1, le=1000)
    account_password: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_period(self):
        if self.from_date and self.to_date and self.to_date < self.from_date:
            raise ValueError("to_date must be on or after from_date")
        if self.from_date and self.to_date and (self.to_date - self.from_date).days + 1 > 3660:
            raise ValueError("Profit snapshot backfill range cannot exceed 3660 days")
        return self


class ProfitSnapshotBackfillRead(BaseModel):
    scanned: int = Field(ge=0)
    created: int = Field(ge=0)
    existing: int = Field(ge=0)
    conflicts: int = Field(ge=0)
    next_after_work_order_id: int | None = None


class AnalyticsExportRequest(BaseModel):
    from_date: date
    to_date: date
    engineer_id: int | None = Field(default=None, gt=0)
    job_type: str | None = Field(default=None, max_length=120)
    account_password: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_period(self):
        if self.to_date < self.from_date:
            raise ValueError("to_date must be on or after from_date")
        if (self.to_date - self.from_date).days + 1 > 366:
            raise ValueError("Analytics export range cannot exceed 366 days")
        return self
