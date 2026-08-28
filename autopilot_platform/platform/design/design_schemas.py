"""设计域 Pydantic DTO（对外 API / IDE 契约）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from autopilot_platform.core.job_platforms import (
    BACKEND_MODE_MAX_LEN,
    apply_deviceless_run_target,
    normalize_stored_backend_mode,
)
from autopilot_platform.core.schemas import normalize_web_engine


# AI 输入上限：避免单请求塞入超大上下文 / 超长列表打爆 token 与调用次数
MAX_CHAT_MESSAGE_CHARS = 20000
MAX_CHAT_HISTORY_ITEMS = 40
MAX_BATCH_REQUIREMENTS = 50

ReviewStatus = Literal["AI_DRAFT", "HUMAN_REVIEWED", "APPROVED", "REJECTED"]
Automatability = Literal["AUTOMATABLE", "PARTIAL", "MANUAL_ONLY", "NEEDS_DESIGN", "UNKNOWN"]
AutomationStatus = Literal[
    "LOGICAL_ONLY",
    "INTENT_READY",
    "PENDING_VERIFY",
    "BINDING_PARTIAL",
    "DRAFT_AUTOMATION",
    "MAPPING_REQUIRED",
    "DEBUGGING",
    "EXECUTABLE",
    "PUBLISHED",
    "DEPRECATED",
]


class RequirementCreate(BaseModel):
    project_id: str
    title: str
    content: str = ""
    req_key: str = ""
    req_type: str = "functional"
    priority: str = "medium"
    source_document_id: str | None = None
    source_excerpt: str = ""


class RequirementUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    req_key: str | None = None
    req_type: str | None = None
    priority: str | None = None
    status: str | None = None


class RequirementOut(BaseModel):
    id: str
    project_id: str
    req_key: str
    title: str
    content: str
    req_type: str
    priority: str
    status: str
    source_document_id: str | None = None
    source_excerpt: str = ""
    created_by: str = ""
    created_at: datetime
    updated_at: datetime


class RequirementListPage(BaseModel):
    items: list[RequirementOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class IntentStep(BaseModel):
    id: str
    action: str = "custom"
    target: str = ""
    value: str = ""
    platform_hint: str = "any"
    text: str = ""


class LogicalCaseCreate(BaseModel):
    project_id: str
    title: str
    case_key: str = ""
    description: str = ""
    preconditions: list[str] = Field(default_factory=list)
    logical_steps: list[str] = Field(default_factory=list)
    intent_steps: list[IntentStep] = Field(default_factory=list)
    expected_results: list[str] = Field(default_factory=list)
    priority: str = "P2"
    tags: list[str] = Field(default_factory=list)
    test_type: str = ""
    module: str = ""
    source_requirement_ids: list[str] = Field(default_factory=list)
    review_status: ReviewStatus = "AI_DRAFT"
    automatability: Automatability = "UNKNOWN"
    automation_status: AutomationStatus | None = None
    generation_metadata: dict[str, Any] = Field(default_factory=dict)


class LogicalCaseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    preconditions: list[str] | None = None
    logical_steps: list[str] | None = None
    intent_steps: list[IntentStep] | None = None
    expected_results: list[str] | None = None
    priority: str | None = None
    tags: list[str] | None = None
    test_type: str | None = None
    module: str | None = None
    source_requirement_ids: list[str] | None = None
    review_status: ReviewStatus | None = None
    automatability: Automatability | None = None
    automation_status: AutomationStatus | None = None
    generation_metadata: dict[str, Any] | None = None


class LogicalCaseOut(BaseModel):
    schema_version: str = "2.0"
    logical_case_id: str
    case_key: str
    project_id: str
    revision_id: str
    title: str
    description: str = ""
    preconditions: list[str] = Field(default_factory=list)
    logical_steps: list[str] = Field(default_factory=list)
    intent_steps: list[dict[str, Any]] = Field(default_factory=list)
    expected_results: list[str] = Field(default_factory=list)
    priority: str = "P2"
    tags: list[str] = Field(default_factory=list)
    test_type: str = ""
    module: str = ""
    source_requirement_ids: list[str] = Field(default_factory=list)
    review_status: ReviewStatus
    automatability: Automatability
    automation_status: AutomationStatus
    generation_metadata: dict[str, Any] = Field(default_factory=dict)
    created_by: str = ""
    created_at: datetime
    updated_at: datetime


class LogicalCaseListPage(BaseModel):
    items: list[LogicalCaseOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class LogicalCaseGenerateIn(BaseModel):
    """从需求文本批量生成逻辑用例草稿（不产出底层关键字）。"""

    project_id: str
    requirement_text: str
    requirement_ids: list[str] = Field(default_factory=list)
    max_cases: int = Field(default=8, ge=1, le=50)
    module: str = ""
    use_rag: bool = False
    # 半自动 APPROVED：质量分 ≥ 阈值且 risk!=high 时直接 APPROVED（默认关）
    auto_approve: bool = False
    auto_approve_min_quality: float = Field(default=0.85, ge=0.0, le=1.0)
    confirmed_only: bool = False
    score_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="None 时用 AP_RAG_SCORE_THRESHOLD",
    )


class LogicalCaseBatchGenerateIn(BaseModel):
    """多条需求文本批量生成（对齐 TestPilot batch-generate）。"""

    project_id: str
    # 每条需求 = 1 次 LLM 调用；限条数与单条长度，防单请求打爆 token
    requirements: list[str] = Field(
        default_factory=list,
        max_length=MAX_BATCH_REQUIREMENTS,
    )
    case_count_per_req: int = Field(default=3, ge=1, le=20)
    process_mode: Literal["sequential", "parallel"] = "sequential"
    module: str = ""
    use_rag: bool = False
    auto_approve: bool = False
    auto_approve_min_quality: float = Field(default=0.85, ge=0.0, le=1.0)
    confirmed_only: bool = False
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class LogicalCaseEnqueueJobIn(BaseModel):
    """APPROVED 用例 → 创建批跑 Job（需已上传含 logical_case_id 的制品）。"""

    project_id: str
    artifact_id: str
    logical_case_ids: list[str] = Field(
        default_factory=list,
        description="空=项目内全部 APPROVED；否则须均为 APPROVED",
    )
    name: str = ""
    app_build_id: str | None = None
    platform: str = "android"
    web_engine: str = Field(
        default="selenium",
        description="platform=web 时：selenium|playwright",
    )
    device_udids: list[str] = Field(default_factory=list)
    preferred_runner_id: str | None = None
    webhook_url: str = ""
    backend_mode: str = Field(default="auto", max_length=BACKEND_MODE_MAX_LEN)
    wda_bundle: str = ""
    parallel: bool = False
    parallel_workers: int = 0

    @model_validator(mode="after")
    def _norm_web_engine(self) -> "LogicalCaseEnqueueJobIn":
        from autopilot_platform.core.webhook_security import validate_webhook_url

        self.web_engine = normalize_web_engine(self.web_engine, self.platform)
        apply_deviceless_run_target(self)
        self.backend_mode = normalize_stored_backend_mode(self.backend_mode)
        self.webhook_url = validate_webhook_url(self.webhook_url, resolve=False)
        return self


class KnowledgeSearchIn(BaseModel):
    project_id: str
    query: str
    top_k: int = Field(default=10, ge=1, le=50)
    score_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    confirmed_only: bool = False


class KnowledgeSearchHit(BaseModel):
    id: str
    title: str
    content: str
    score: float
    category: str = ""
    source: str = ""
    confirmed: bool = False


class KnowledgeSearchOut(BaseModel):
    query: str
    engine: str = ""
    total: int = 0
    documents: list[KnowledgeSearchHit] = Field(default_factory=list)


class KnowledgeBatchDeleteIn(BaseModel):
    item_ids: list[str] = Field(default_factory=list)


class RequirementBatchDeleteIn(BaseModel):
    item_ids: list[str] = Field(default_factory=list)


class DocumentBatchDeleteIn(BaseModel):
    item_ids: list[str] = Field(default_factory=list)


class KnowledgeRebuildIn(BaseModel):
    project_id: str
    clear_all: bool = True


class DesignListPageMeta(BaseModel):
    """通用分页壳；各端点用具体 items 类型包装。"""

    total: int = 0
    page: int = 1
    page_size: int = 20


class DocumentPreviewOut(BaseModel):
    id: str
    project_id: str
    filename: str
    file_type: str
    size_bytes: int
    content: str
    content_type: str = "text"
    is_truncated: bool = False


class AnalysisHistoryOut(BaseModel):
    id: str
    project_id: str
    document_id: str
    analysis_type: str
    requirement_count: int
    mode: str
    created_by: str
    created_at: datetime
    detail: dict[str, Any] = Field(default_factory=dict)


class AnalysisHistoryListPage(DesignListPageMeta):
    items: list[AnalysisHistoryOut] = Field(default_factory=list)


class ChatSessionCreate(BaseModel):
    project_id: str = ""
    title: str = "新对话"


class ChatSessionUpdate(BaseModel):
    title: str


class ChatSessionOut(BaseModel):
    id: str
    project_id: str
    title: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    preview: str = ""


class ChatSessionListPage(DesignListPageMeta):
    items: list[ChatSessionOut] = Field(default_factory=list)


class ChatMessageOut(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    tokens_used: int = 0
    model_name: str = ""
    created_at: datetime


class ChatMessageIn(BaseModel):
    session_id: str
    message: str = Field(max_length=MAX_CHAT_MESSAGE_CHARS)
    use_knowledge: bool = False
    temperature: float | None = None
    model: str | None = None
    max_tokens: int | None = None
    # 实验动作：mode=action 时优先走确认流；也可仅 require_confirmation
    mode: str | None = None
    require_confirmation: bool = False


class EphemeralChatIn(BaseModel):
    """无项目测试闲聊：不落设计域会话表、不注入知识库（人设仍为测试助手）。"""

    message: str = Field(max_length=MAX_CHAT_MESSAGE_CHARS)
    history: list[dict[str, str]] = Field(
        default_factory=list,
        max_length=MAX_CHAT_HISTORY_ITEMS,
    )
    temperature: float | None = None
    model: str | None = None
    max_tokens: int | None = None


class LogicalCaseExportBundle(BaseModel):
    schema_version: str = "2.0"
    project_id: str
    exported_at: datetime
    cases: list[LogicalCaseOut]


class KnowledgeItemCreate(BaseModel):
    project_id: str
    title: str
    content: str
    category: str = "other"
    source: str = ""
    confirmed: bool = False


class KnowledgeItemUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    category: str | None = None
    source: str | None = None
    confirmed: bool | None = None


class KnowledgeItemOut(BaseModel):
    id: str
    project_id: str
    title: str
    content: str
    category: str
    source: str
    confirmed: bool
    created_by: str
    created_at: datetime


class KnowledgeListPage(BaseModel):
    items: list[KnowledgeItemOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class TestPointOut(BaseModel):
    id: str
    project_id: str
    requirement_id: str | None = None
    title: str
    description: str = ""
    risk: str = "medium"
    created_at: datetime | None = None


class TestPointListPage(BaseModel):
    items: list[TestPointOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class DesignDocumentOut(BaseModel):
    id: str
    project_id: str
    filename: str
    file_type: str
    size_bytes: int
    uploaded_by: str
    created_at: datetime
    content_preview: str = ""


class DesignDocumentListPage(BaseModel):
    items: list[DesignDocumentOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
