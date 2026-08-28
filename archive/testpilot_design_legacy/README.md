# TestPilot 设计域遗留源码归档

**AUD-2026-18**：本目录保持排除；**禁止**接入 Platform 运行时 / setuptools / CI 类型检查。

从 `autopilot_platform/design/` 迁出的 Flask/LangChain **只读参考**实现。

目录约定：

- `ai/` — 原 `design/ai`（agent / business / models_util / quality）
- `knowledge/` — 原 `design/knowledge`
- `documents/` — 原 `design/documents`

## 重要（别当正式代码修）

- **不参与** AutoPilot Platform 运行时；不要 `pip install langchain` 来「修」这里的红线。
- 顶层 import（`config.settings` / `utils.*` / `models.models`）属于旧 TestPilot 包布局，**在本仓故意不存在**。
- 正式能力：`autopilot_platform.platform.*`（`ai_case_generator` / `rag` / `api/design`）。
- 说明占位：`autopilot_platform/design/LEGACY.md`。

### IDE 红线怎么消

这些「未解析的引用 / 项目未列出 langchain」是 **归档被当成源码根索引** 的噪音，不是漏移植：

1. **PyCharm / IDEA**：右键本目录 `archive` → *Mark Directory as* → *Excluded*
2. **VS Code / Cursor / Pylance**：已在仓库 `.vscode/settings.json` 排除 `archive/**`
3. **ruff / basedpyright**：`pyproject.toml` 已 `exclude` / `extend-exclude` 本目录

若不再需要对照旧实现，可直接删除整个 `archive/testpilot_design_legacy/`（不影响 Platform 运行）。
