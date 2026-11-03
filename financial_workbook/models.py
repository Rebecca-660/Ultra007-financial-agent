from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


def digest(value) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")).encode()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Column(StrictModel):
    column_id: str
    raw_header: str
    value_year: int
    role: Literal["current", "prior", "opening"]
    as_of: str | None


class StatementRow(StrictModel):
    row_id: str
    raw_label: str
    note: str = ""
    values: list[Decimal | None]
    raw_values: list[str]
    pdf_page: int
    bbox: list[float]
    canonical_metric: str | None = None
    warnings: list[str] = Field(default_factory=list)


class Statement(StrictModel):
    statement_id: str
    company_id: str
    report_set_id: str
    report_year: int
    kind: Literal["IS", "BS", "CF"]
    scope: Literal["consolidated"] = "consolidated"
    file_name: str
    file_hash: str
    pdf_pages: list[int]
    currency: str | None
    raw_unit: str
    scale: Decimal | None
    columns: list[Column]
    rows: list[StatementRow]
    checks: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def valid_table(self):
        if not 2 <= len(self.columns) <= 8:
            raise ValueError('主表需要 2–8 个年度栏。')
        current=[c for c in self.columns if c.role=='current']
        if len(current)!=1 or current[0].value_year!=self.report_year:
            raise ValueError('主表必须具有一个匹配报告年度的本年栏。')
        if len({c.column_id for c in self.columns})!=len(self.columns):
            raise ValueError('重复的列身份。')
        if not self.rows or len({r.row_id for r in self.rows})!=len(self.rows):
            raise ValueError('表体不能为空或含有重复行身份。')
        if any(len(r.values)!=len(self.columns) or len(r.raw_values)!=len(self.columns) or len(r.bbox)!=4 for r in self.rows):
            raise ValueError('原表行列数量或坐标不一致。')
        if any(r.pdf_page not in self.pdf_pages for r in self.rows):
            raise ValueError('表体行来自未声明的 PDF 页。')
        return self


class Dataset(StrictModel):
    schema_version: str = "annual-statements-v2"
    created_at: str = Field(default_factory=now)
    company_id: str
    report_set_id: str
    statements: list[Statement]
    conflicts: list[dict] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    extraction_profile: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def valid_scope(self):
        if not self.statements:
            raise ValueError('候选数据集不能为空。')
        if any(s.company_id!=self.company_id or s.report_set_id!=self.report_set_id for s in self.statements):
            raise ValueError('候选报表混入其他公司或报告集合。')
        if len({(s.report_year,s.kind) for s in self.statements})!=len(self.statements):
            raise ValueError('同年度同类报表有多份候选，不能静默覆盖。')
        if len({s.statement_id for s in self.statements})!=len(self.statements):
            raise ValueError('重复的报表身份。')
        return self

    @property
    def fingerprint(self) -> str:
        return digest(self)


class Correction(StrictModel):
    row_id: str
    column_id: str
    original: Decimal | None
    corrected: Decimal | None
    reason: str = Field(min_length=1)


class Decision(StrictModel):
    statement_id: str
    statement_digest: str
    decision: Literal["approved", "rejected"]
    reviewer: str = Field(min_length=1)
    reviewed_at: str = Field(default_factory=now)
    note: str = ""
    conflict_resolution: Literal["", "as_reported"] = ""
    corrections: list[Correction] = Field(default_factory=list)


class Review(StrictModel):
    dataset_fingerprint: str
    report_set_id: str
    decisions: list[Decision]


class SystemValidation(StrictModel):
    """Machine evidence, explicitly separate from a person's review decisions."""
    schema_version: Literal['finance-system-validation-v1'] = 'finance-system-validation-v1'
    method: Literal['system'] = 'system'
    status: Literal['validated'] = 'validated'
    dataset_fingerprint: str
    company_id: str
    report_set_id: str
    statement_digests: dict[str,str]
    comparative_policy: Literal['as_reported'] = 'as_reported'
    validated_at: str = Field(default_factory=now)
    checks: list[dict]
    warnings: list[str] = Field(default_factory=list)


class Locator(StrictModel):
    report_year: int
    kind: Literal["IS", "BS", "CF"]
    file_name: str
    file_hash: str
    pdf_pages: list[int]
    retrieval_evidence_ids: list[str] = Field(default_factory=list)


class Handoff(StrictModel):
    status: Literal["located", "extracted", "needs_human_review", "validated", "analyzed", "exported"]
    ids: list[str]
