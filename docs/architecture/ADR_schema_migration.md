# ADR：Schema 迁移（AUD-2026-07 / AUD-P2-004）

## 状态

**Accepted（已切流）** — `init_db()` 经 `platform.core.alembic_align.apply_schema_cutover` 接入 Alembic。

| 审计 ID | 仓内标签 | 说明 |
|---------|----------|------|
| AUD-2026-07 | AUD-P2-004 | Prepare + **cutover**（安全双路径） |

## 背景

历史用 SQLAlchemy `create_all` + 手工 `ALTER TABLE`。无版本化迁移历史，多环境/回滚困难。

## 决策（切流后）

1. **空库**：`alembic upgrade head`，再跑 `migrate_schema`（预订索引等数据修复）。  
2. **已有库**：保持 `create_all` + `migrate_schema`（幂等），然后：  
   - 无 `alembic_version` → `alembic stamp head`（**禁止**对已有表重跑 baseline DDL）  
   - 已有版本表 → `alembic upgrade head`（后续 revision）  
3. **新变更**：优先 `alembic revision`；`SCHEMA_ADDS` 为兼容补列层，非唯一真源。  
4. alembic 进入主依赖；`.[migrate]` extra 保留兼容。

## 日常改库

```text
改 ORM models
  → alembic revision --autogenerate（人工审）
  → 如需旧库无 revision 也能补列：可选追加 schema_adds.py
  → 测试：init_db 空库 / 旧库缺列 / scratch upgrade+downgrade
```

现网首次升级到本切流版本：启动即 `stamp head`（表已存在时），无需手工操作。

## 切流条件

- [x] `alembic upgrade head` 在空库 scratch SQLite 通过（CI + 单测）  
- [x] CI 迁移 dry-run + rollback 演练（upgrade → downgrade base → upgrade）  
- [x] 回滚演练文档（见下；scratch 由 CI 覆盖）  
- [ ] 现网 SQLite / PG 抽样（运维窗口；代码路径已支持 stamp/upgrade）

## 回滚演练

1. **切流后二进制回退**：恢复旧版本代码；旧 `init_db` 仍 `create_all`+`migrate_schema`；多出的 `alembic_version` 表可忽略。  
2. **误 upgrade 损坏**：停写 → DB 备份恢复 → 再启动让 `stamp`/`upgrade` 对齐。  
3. **scratch 演练**（CI）：`upgrade head` → `downgrade base` → `upgrade head`。  
4. **勿**在无备份时对生产 `downgrade`。

## 后果

- 空库可版本化建表；旧库零停机 stamp。  
- baseline 之后的 DDL 可审计回放。  
- `SCHEMA_ADDS` 短期仍承担缺列补齐与预订索引修复。
