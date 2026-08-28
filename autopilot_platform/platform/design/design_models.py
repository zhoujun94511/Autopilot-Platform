"""设计域 ORM：需求 / 测试点 / 逻辑用例 / 文档（挂靠 projects）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base
from ..core.models import new_id


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DesignDocumentRow(Base):
    """上传的需求/规格文档元数据。"""

    __tablename__ = "design_documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    filename: Mapped[str] = mapped_column(String(512), default="")
    stored_path: Mapped[str] = mapped_column(Text, default="")
    content_text: Mapped[str] = mapped_column(Text, default="")
    file_type: Mapped[str] = mapped_column(String(32), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RequirementRow(Base):
    """结构化需求（可来自文档解析或手工录入）。"""

    __tablename__ = "design_requirements"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    req_key: Mapped[str] = mapped_column(String(128), default="", index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    req_type: Mapped[str] = mapped_column(String(64), default="functional")
    priority: Mapped[str] = mapped_column(String(32), default="medium")
    status: Mapped[str] = mapped_column(String(32), default="active")
    source_document_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_excerpt: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class TestPointRow(Base):
    """测试点：连接需求与逻辑用例。"""

    __tablename__ = "design_test_points"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    requirement_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    risk: Mapped[str] = mapped_column(String(32), default="medium")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class LogicalCaseRow(Base):
    """逻辑测试用例（与执行框架无关；自动化真源在 IDE）。"""

    __tablename__ = "design_logical_cases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    case_key: Mapped[str] = mapped_column(String(128), default="", index=True)
    revision_id: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    preconditions_json: Mapped[str] = mapped_column(Text, default="[]")
    logical_steps_json: Mapped[str] = mapped_column(Text, default="[]")
    intent_steps_json: Mapped[str] = mapped_column(Text, default="[]")
    expected_results_json: Mapped[str] = mapped_column(Text, default="[]")
    priority: Mapped[str] = mapped_column(String(32), default="P2")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    test_type: Mapped[str] = mapped_column(String(64), default="")
    module: Mapped[str] = mapped_column(String(128), default="")
    source_requirement_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    review_status: Mapped[str] = mapped_column(String(32), default="AI_DRAFT", index=True)
    automatability: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    automation_status: Mapped[str] = mapped_column(String(32), default="LOGICAL_ONLY")
    generation_metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    @staticmethod
    def _loads_list(raw: str) -> list:
        try:
            val = json.loads(raw or "[]")
            return list(val) if isinstance(val, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    @staticmethod
    def _dumps_list(value: list | None) -> str:
        return json.dumps(list(value or []), ensure_ascii=False)

    @property
    def preconditions(self) -> list[str]:
        return [str(x) for x in self._loads_list(self.preconditions_json)]

    @preconditions.setter
    def preconditions(self, value: list[str]) -> None:
        self.preconditions_json = self._dumps_list(value)

    @property
    def logical_steps(self) -> list[str]:
        return [str(x) for x in self._loads_list(self.logical_steps_json)]

    @logical_steps.setter
    def logical_steps(self, value: list[str]) -> None:
        self.logical_steps_json = self._dumps_list(value)

    @property
    def intent_steps(self) -> list[dict]:
        try:
            val = json.loads(self.intent_steps_json or "[]")
            return list(val) if isinstance(val, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    @intent_steps.setter
    def intent_steps(self, value: list[dict] | None) -> None:
        self.intent_steps_json = json.dumps(list(value or []), ensure_ascii=False)

    @property
    def expected_results(self) -> list[str]:
        return [str(x) for x in self._loads_list(self.expected_results_json)]

    @expected_results.setter
    def expected_results(self, value: list[str]) -> None:
        self.expected_results_json = self._dumps_list(value)

    @property
    def tags(self) -> list[str]:
        return [str(x) for x in self._loads_list(self.tags_json)]

    @tags.setter
    def tags(self, value: list[str]) -> None:
        self.tags_json = self._dumps_list(value)

    @property
    def source_requirement_ids(self) -> list[str]:
        return [str(x) for x in self._loads_list(self.source_requirement_ids_json)]

    @source_requirement_ids.setter
    def source_requirement_ids(self, value: list[str]) -> None:
        self.source_requirement_ids_json = self._dumps_list(value)

    @property
    def generation_metadata(self) -> dict:
        try:
            val = json.loads(self.generation_metadata_json or "{}")
            return dict(val) if isinstance(val, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    @generation_metadata.setter
    def generation_metadata(self, value: dict | None) -> None:
        self.generation_metadata_json = json.dumps(dict(value or {}), ensure_ascii=False)


class KnowledgeItemRow(Base):
    """知识条目元数据（向量内容由 knowledge 存储后端管理）。"""

    __tablename__ = "design_knowledge_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    category: Mapped[str] = mapped_column(String(64), default="other", index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(256), default="")
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class DesignAnalysisHistoryRow(Base):
    """文档分析历史记录。"""

    __tablename__ = "design_analysis_history"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    document_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    analysis_type: Mapped[str] = mapped_column(String(64), default="requirements")
    requirement_count: Mapped[int] = mapped_column(Integer, default=0)
    mode: Mapped[str] = mapped_column(String(32), default="heuristic")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    detail_json: Mapped[str] = mapped_column(Text, default="{}")

    @property
    def detail(self) -> dict:
        try:
            val = json.loads(self.detail_json or "{}")
            return dict(val) if isinstance(val, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    @detail.setter
    def detail(self, value: dict | None) -> None:
        self.detail_json = json.dumps(dict(value or {}), ensure_ascii=False)


class DesignChatSessionRow(Base):
    """设计域 AI 对话会话。"""

    __tablename__ = "design_chat_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    title: Mapped[str] = mapped_column(String(256), default="新对话")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class DesignChatMessageRow(Base):
    """设计域 AI 对话消息。"""

    __tablename__ = "design_chat_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    role: Mapped[str] = mapped_column(String(32), default="user")
    content: Mapped[str] = mapped_column(Text, default="")
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    model_name: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
