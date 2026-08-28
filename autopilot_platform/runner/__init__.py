"""TestRunner Agent（Console 产品附带的执行节点）。

与 Platform 仅 HTTP；执行核为仓内完整拷贝 ``autopilot_platform.ap``（见 ``[runner]`` extra）。
Platform / Web **不** import 本包。
"""

from .agent import RunnerAgent, run_forever

__all__ = ["RunnerAgent", "run_forever"]
