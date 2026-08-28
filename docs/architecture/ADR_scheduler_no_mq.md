# ADR：调度不引入独立 MQ（AUD-2026-13）

## 状态

**RISK ACCEPTED** — 在出现明确多实例吞吐 / 跨区排队需求前，**不**引入 Celery / Redis Queue / Kafka 等独立消息中间件。

| 审计 ID | 说明 |
|---------|------|
| AUD-2026-13 | 无 MQ、进程内 schedule tick；多实例靠 DB 租约 |

## 背景

审计指出：调度为进程内守护线程 + DB 扫描，无独立队列，扩展性在「多活 Platform + 高并发计划触发」场景受限。

## 当前架构（保留）

```text
create_app lifespan
  → start_schedule_loop()          # 可选 MC_SCHEDULE_ENABLED=0
  → 线程 mc-schedule-tick
       → try_acquire_scheduler_lease (ops_locks.schedule_loop)
       → tick_due_schedules / reclaim_stale_jobs / purge / fleet_alerts
Runner
  → 长轮询 claim Job（非 MQ 消费）
```

缓解手段（已有，非本轮新造）：

1. **DB leader 租约**（`scheduler_lock.py` / AUD-P1-006）— 同库仅一进程跑 tick  
2. **计划单拍 claim**（`_claim_schedule_fire`）— 避免重复建 Job  
3. **运维开关** — 跟随节点 `MC_SCHEDULE_ENABLED=0`  
4. **多写 HA** — 文档要求 PostgreSQL，SQLite 仅联调  

## 决策

1. **接受**「单库单活调度 + Job 长轮询」为当前产品默认。  
2. **禁止**在无产品需求时为「架构整齐」引入 MQ（运维面、一致性、本地开发成本上升）。  
3. **重开条件**（任一满足再单独立项）：  
   - 多活 Platform 上计划触发延迟 / 丢拍不可接受  
   - 需要跨区域或跨库的任务扇出  
   - Runner 领取模型要改为推送式队列且 DB claim 证明不够  
4. 切 MQ 时须另写 ADR（broker 选型、幂等、毒消息、与现有 `ops_locks` / job claim 共存策略）。

## 后果

- 多副本部署文档必须写清：单活调度或依赖租约；SQLite 不适合多写。  
- 门禁：`tests/test_scheduler_no_mq.py` 锁定「无硬依赖 MQ + ADR 声明」。
