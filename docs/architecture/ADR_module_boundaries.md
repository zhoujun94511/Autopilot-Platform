# ADR：设计 API / IDE UI 模块边界

## 状态

Accepted — 大文件按职责拆模块；禁止一次性整文件重写。

## 原则

1. **新功能**优先进已有子模块，或新建内聚模块后由父入口 `include_router` / Mixin 组合。  
2. **每次只抽一个切片**；抽完须 import 冒烟 + 相关 pytest 绿。  
3. 文档写清「谁负责什么」，避免审计口号式标签。

## 当前拆分（Platform `platform/api`）

| 模块 | 职责 |
|------|------|
| `design.py` | 需求 / 逻辑用例 / 知识 / 文档 CRUD |
| `design_dashboard.py` | stats / stats export / batch export |
| `design_config.py` | `/design/config*` |
| `design_chat_routes.py` | Chat + experimental-actions |

## 当前拆分（IDE `ui/main_window`）

| 模块 | 职责 |
|------|------|
| `device.py` (`DeviceMixin`) | 检视、选机、插拔、定位符 |
| `device_mirror.py` (`DeviceMirrorMixin`) | 实时镜像会话与 AVF/MJPEG 回退 |
| `device_readiness.py` | 无 Qt 的在线/目标校验 |

## 下一步候选

- `design.py` 若再胀：文档分析 / 知识导入可再拆  
- `device.py`：定位符裁剪与 map 写入可再拆  
