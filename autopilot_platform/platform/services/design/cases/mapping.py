"""Logical case services."""
from __future__ import annotations
from typing import Any, cast
from autopilot_platform.platform.design.design_models import LogicalCaseRow
from autopilot_platform.platform.design.design_schemas import LogicalCaseCreate, LogicalCaseOut
from autopilot_platform.platform.design.intent_normalize import texts_to_intent_steps

def _case_out(row: LogicalCaseRow) -> LogicalCaseOut:
    intents = list(getattr(row, 'intent_steps', None) or [])
    if not intents and row.logical_steps:
        intents = texts_to_intent_steps(row.logical_steps, row.expected_results)
    return LogicalCaseOut(schema_version='2.0', logical_case_id=row.id, case_key=row.case_key, project_id=row.project_id, revision_id=row.revision_id, title=row.title, description=row.description, preconditions=row.preconditions, logical_steps=row.logical_steps, intent_steps=intents, expected_results=row.expected_results, priority=row.priority, tags=row.tags, test_type=row.test_type, module=row.module, source_requirement_ids=row.source_requirement_ids, review_status=cast(Any, row.review_status), automatability=cast(Any, row.automatability), automation_status=cast(Any, row.automation_status), generation_metadata=row.generation_metadata, created_by=row.created_by, created_at=row.created_at, updated_at=row.updated_at)

def _ensure_intent_steps(body: LogicalCaseCreate) -> list[dict]:
    if body.intent_steps:
        return [s.model_dump() if hasattr(s, 'model_dump') else dict(s) for s in body.intent_steps]
    return texts_to_intent_steps(body.logical_steps, body.expected_results)
