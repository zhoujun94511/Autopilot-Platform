"""DataConfig (.properties) 解析：增强版 Java Properties（保序 + 注释）。

格式（见 reverse/docs/file-format-spec.md）：
  key=value         普通变量
  !key:注释内容      该 key 的注释（格式约定）
  # 行注释 / ! 行注释
保序：用列表保存 (key,value,comment)，对外也提供 dict 视图。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DataConfig:
    entries: list[tuple[str, str]] = field(default_factory=list)   # 有序 (key,value)
    comments: dict[str, str] = field(default_factory=dict)         # key -> comment
    source_path: str = ""

    def as_dict(self) -> dict[str, str]:
        return {k: v for k, v in self.entries}

    def set(self, key: str, value: str) -> None:
        for i, (k, _) in enumerate(self.entries):
            if k == key:
                self.entries[i] = (key, value)
                return
        self.entries.append((key, value))


def loads(text: str) -> DataConfig:
    cfg = DataConfig()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # !key:comment —— 注释绑定到某 key（格式约定，需在 # 行注释之前判断）
        if line.startswith("!") and ":" in line[1:]:
            k, c = line[1:].split(":", 1)
            cfg.comments[k.strip()] = c.strip()
            continue
        if line.startswith("#") or line.startswith("!"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            cfg.entries.append((k.strip(), v.strip()))
    return cfg


def load(path: str) -> DataConfig:
    with open(path, "r", encoding="utf-8") as f:
        cfg = loads(f.read())
    cfg.source_path = path
    return cfg


def dump(cfg: DataConfig) -> str:
    lines: list[str] = []
    for k, v in cfg.entries:
        if k in cfg.comments:
            lines.append(f"!{k}:{cfg.comments[k]}")
        lines.append(f"{k}={v}")
    return "\n".join(lines) + "\n"


def save(cfg: DataConfig, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(dump(cfg))
