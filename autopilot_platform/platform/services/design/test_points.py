"""测试点列表查询（文档分析落库后可查 / 注入生成上下文）。"""
from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.orm import Session
from autopilot_platform.platform.design.design_models import TestPointRow
from autopilot_platform.platform.design.design_schemas import TestPointListPage, TestPointOut
from autopilot_platform.platform.services.shared.pagination import clamp_page, paginate

def _to_out(row: TestPointRow) -> TestPointOut:
    return TestPointOut(id=row.id, project_id=row.project_id, requirement_id=row.requirement_id, title=row.title or '', description=row.description or '', risk=row.risk or 'medium', created_at=row.created_at)

def list_test_points(db: Session, *, project_id: str, page: int=1, page_size: int=50) -> TestPointListPage:
    pid = (project_id or '').strip()
    if not pid:
        raise ValueError('project_id 不能为空')
    safe_page, safe_page_size = clamp_page(page, page_size)
    page = int(safe_page or 1)
    page_size = int(safe_page_size or 50)
    q = select(TestPointRow).where(TestPointRow.project_id == pid).order_by(TestPointRow.created_at.desc())
    items, total = paginate(db, q, page=page, page_size=page_size)
    return TestPointListPage(items=[_to_out(r) for r in items], total=int(total or 0), page=page, page_size=page_size)
