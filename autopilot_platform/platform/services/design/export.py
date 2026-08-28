"""设计域 Excel/CSV 导出与模板。"""
from __future__ import annotations
import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Iterable
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from autopilot_platform.platform.design.design_schemas import LogicalCaseOut, RequirementOut
from autopilot_platform.platform.services.design.cases import crud as design_svc
from autopilot_platform.platform.services.design.requirements import crud as req_svc

def _stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')

def _cases_rows(cases: list[LogicalCaseOut]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for c in cases:
        intents = list(c.intent_steps or [])
        intent_ser = json.dumps([s.model_dump(mode='json') if hasattr(s, 'model_dump') else dict(s) for s in intents], ensure_ascii=False)
        rows.append({'logical_case_id': c.logical_case_id, 'case_key': c.case_key, 'title': c.title, 'priority': c.priority, 'review_status': c.review_status, 'automation_status': c.automation_status, 'module': c.module, 'preconditions': '\n'.join(c.preconditions or []), 'logical_steps': '\n'.join(c.logical_steps or []), 'intent_steps': intent_ser, 'expected_results': '\n'.join(c.expected_results or []), 'tags': ','.join(c.tags or [])})
    return rows

def _req_rows(reqs: list[RequirementOut]) -> list[dict[str, Any]]:
    return [{'id': r.id, 'req_key': r.req_key, 'title': r.title, 'content': r.content, 'req_type': r.req_type, 'priority': r.priority, 'status': r.status, 'source_document_id': r.source_document_id or ''} for r in reqs]

def _csv_bytes(rows: list[dict[str, Any]], fieldnames: Iterable[str]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(fieldnames), extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return ('\ufeff' + buf.getvalue()).encode('utf-8')

def _xlsx_bytes(rows: list[dict[str, Any]], sheet_name: str='Sheet1') -> bytes:
    from openpyxl import Workbook  # 延迟：可选 extra
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = sheet_name[:31] or 'Sheet1'
    if not rows:
        bio = io.BytesIO()
        wb.save(bio)
        return bio.getvalue()
    headers = list(rows[0].keys())
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h, '') for h in headers])
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()

def _file_response(data: bytes, *, filename: str, media: str) -> StreamingResponse:
    return StreamingResponse(io.BytesIO(data), media_type=media, headers={'Content-Disposition': f'attachment; filename="{filename}"'})

def export_logical_cases(db: Session, *, project_id: str | None, project_ids: list[str] | None, review_status: str | None, case_ids: list[str] | None, fmt: str) -> StreamingResponse:
    cases = design_svc.list_logical_cases(db, project_id=project_id, project_ids=project_ids, review_status=review_status)
    if case_ids:
        wanted = {x.strip() for x in case_ids if x and str(x).strip()}
        cases = [c for c in cases if c.logical_case_id in wanted]
    rows = _cases_rows(cases)
    fields = ('logical_case_id', 'case_key', 'title', 'priority', 'review_status', 'automation_status', 'module', 'preconditions', 'logical_steps', 'intent_steps', 'expected_results', 'tags')
    fmt_l = (fmt or 'csv').strip().lower()
    if fmt_l in {'json'}:
        payload = [c.model_dump(mode='json') for c in cases]
        data = (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        return _file_response(data, filename=f'logical_cases_{_stamp()}.json', media='application/json; charset=utf-8')
    if fmt_l == 'excel' or fmt_l == 'xlsx':
        data = _xlsx_bytes(rows, 'logical_cases')
        return _file_response(data, filename=f'logical_cases_{_stamp()}.xlsx', media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    data = _csv_bytes(rows, fields)
    return _file_response(data, filename=f'logical_cases_{_stamp()}.csv', media='text/csv; charset=utf-8')

def export_requirements(db: Session, *, project_id: str | None, project_ids: list[str] | None, source_document_id: str | None, req_ids: list[str] | None, fmt: str='excel') -> StreamingResponse:
    reqs = req_svc.list_requirements(db, project_id=project_id, project_ids=project_ids, source_document_id=source_document_id)
    if req_ids:
        wanted = {x.strip() for x in req_ids if x and str(x).strip()}
        reqs = [r for r in reqs if r.id in wanted]
    rows = _req_rows(reqs)
    fields = ('id', 'req_key', 'title', 'content', 'req_type', 'priority', 'status', 'source_document_id')
    fmt_l = (fmt or 'excel').strip().lower()
    if fmt_l in {'csv'}:
        data = _csv_bytes(rows, fields)
        return _file_response(data, filename=f'requirements_{_stamp()}.csv', media='text/csv; charset=utf-8')
    data = _xlsx_bytes(rows, 'requirements')
    return _file_response(data, filename=f'requirements_{_stamp()}.xlsx', media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

def cases_template(fmt: str='excel') -> StreamingResponse:
    sample = [{'case_key': 'LC-EXAMPLE', 'title': '示例用例标题', 'priority': 'P2', 'module': '登录', 'preconditions': '环境可用', 'logical_steps': '打开登录页\n输入账号密码\n点击登录', 'expected_results': '进入首页', 'tags': 'smoke,login'}]
    fmt_l = (fmt or 'excel').strip().lower()
    if fmt_l == 'csv':
        data = _csv_bytes(sample, sample[0].keys())
        return _file_response(data, filename='logical_cases_template.csv', media='text/csv; charset=utf-8')
    data = _xlsx_bytes(sample, 'template')
    return _file_response(data, filename='logical_cases_template.xlsx', media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
