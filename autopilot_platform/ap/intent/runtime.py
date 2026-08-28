"""IntentRuntime：Binding 命中 → 解析 → 自愈 → 调用现有关键字。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..keywords.registry import REGISTRY, KeywordError
from .bindings import (
    confirm_step_binding,
    note_step_run,
    load_binding,
    rollback_step_binding,
    upsert_step_binding,
)
from .config import heal_budget_ms, heal_candidate_timeout_ms
from .heal_attr import classify_intent_failure
from .resolve import detect_platform, effective_channel, normalize_channel, resolve_candidates
from .risk import assert_intent_keyword_allowed

MAX_HEAL_TRIES = 3


def _is_assert_action(action: str) -> bool:
    return (action or "").strip().lower() in {"assert", "verify", "expect", "check"}


def _strategy_from_resolver(resolver: str, *, healing: bool) -> str:
    r = (resolver or "").strip().lower()
    if r == "vision":
        return "vision"
    if healing:
        return "heal"
    if r in {
        "heuristic",
        "accessibility",
        "dom",
        "cache",
        "http_heuristic",
        "http_cache",
    }:
        return r
    return r or "heuristic"


@dataclass
class IntentOutcome:
    intent_id: str
    binding_hit: str  # cache | resolved | healed | failed | rolled_back
    heal_applied: bool = False
    keyword_id: str = ""
    message: str = ""
    fail_reason: str = ""
    fail_reason_label: str = ""
    rolled_back: bool = False
    resolve_strategy: str = ""
    candidate_count: int = 0
    perception_platform: str = ""
    perception_element_count: int = 0
    perception_used_screenshot: bool = False
    latency_ms: int = 0
    vision_tokens: int = 0
    verification_status: str = ""  # passed | failed | skipped | missing
    extra: dict[str, Any] = field(default_factory=dict)


class IntentRuntime:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    def _project_dir(self) -> str:
        return str(self.ctx.get_var("__project_path__") or "").strip() or "."

    def _logical_case_id(self) -> str:
        return str(
            self.ctx.get_var("__logical_case_id__")
            or self.ctx.get_var("logical_case_id")
            or ""
        ).strip()

    def _invoke(self, keyword_id: str, params: dict[str, Any]) -> None:

        assert_intent_keyword_allowed(keyword_id, source="intent")
        kwdef = REGISTRY.get(keyword_id)
        if kwdef is None:
            raise KeywordError(f"意图解析到未知关键字: {keyword_id}")
        resolved: dict[str, Any] = {}
        for k, v in (params or {}).items():
            if isinstance(v, str):
                resolved[k] = self.ctx.resolve(v)
            else:
                resolved[k] = v
        kwdef.func(self.ctx, **resolved)

    def _invoke_follow_ups(self, follow_ups: list[dict[str, Any]] | None) -> None:
        for step in follow_ups or []:
            if not isinstance(step, dict):
                continue
            kid = str(step.get("keyword_id") or "").strip()
            if not kid:
                continue
            self._invoke(kid, dict(step.get("params") or {}))

    @staticmethod
    def _cache_matches(cached: dict[str, Any] | None, *, channel: str, ui_plat: str) -> bool:
        if not isinstance(cached, dict) or not cached.get("keyword_id"):
            return False
        if channel == "http":
            cch = str(cached.get("channel") or "").strip().lower()
            plat = str(cached.get("platform") or "").strip().lower()
            return cch == "http" or plat == "http" or str(
                cached.get("keyword_id") or ""
            ).startswith("http_")
        # ui：要求 platform 与当前 UI 平台一致，且非纯 HTTP Binding
        cch = str(cached.get("channel") or "").strip().lower()
        plat = str(cached.get("platform") or "").strip().lower()
        if cch == "http" or plat == "http":
            return False
        return plat == ui_plat

    @staticmethod
    def _with_short_timeout(params: dict[str, Any], timeout_ms: int) -> dict[str, Any]:
        out = dict(params or {})
        # 多数查找类关键字认 timeout（毫秒字符串）
        out["timeout"] = str(timeout_ms)
        return out

    def _vision_tokens(self) -> int:
        raw = self.ctx.get_var("__last_vision_usage__")
        if not isinstance(raw, dict):
            return 0
        try:
            return max(0, int(raw.get("total_tokens") or 0))
        except (TypeError, ValueError):
            return 0

    def _perception_snapshot(self, plat: str) -> tuple[int, bool]:
        """尽量轻量：优先读上下文已有摘要，避免二次全量采集。"""
        count = 0
        raw_n = self.ctx.get_var("__last_ui_elements_count__")
        if raw_n is not None:
            try:
                count = max(0, int(raw_n))
            except (TypeError, ValueError):
                count = 0
        if count <= 0:
            elems = self.ctx.get_var("__last_ui_elements__")
            if isinstance(elems, list):
                count = len(elems)
        shot = bool(self.ctx.get_var("__last_vision_used_screenshot__"))
        _ = plat
        return count, shot

    def _fill_trace(
        self,
        out: IntentOutcome,
        *,
        plat: str,
        t0: float,
        candidate_count: int = 0,
        resolve_strategy: str = "",
        used_screenshot: bool | None = None,
        action: str = "",
        success: bool = True,
    ) -> IntentOutcome:
        el_count, shot_ctx = self._perception_snapshot(plat)
        out.perception_platform = plat
        out.perception_element_count = el_count
        out.perception_used_screenshot = (
            bool(used_screenshot) if used_screenshot is not None else shot_ctx
        )
        out.candidate_count = max(0, int(candidate_count))
        out.resolve_strategy = resolve_strategy or out.resolve_strategy
        out.latency_ms = max(0, int((time.monotonic() - t0) * 1000))
        out.vision_tokens = self._vision_tokens()
        if out.binding_hit == "failed":
            out.verification_status = "skipped"
        elif success and _is_assert_action(action):
            out.verification_status = "passed"
        elif success:
            # 非断言动作：缺独立验证点时软标记（不改变 PASS）
            out.verification_status = out.verification_status or "missing"
        else:
            out.verification_status = "failed" if _is_assert_action(action) else "skipped"
        return out

    def _run_http(
        self,
        *,
        iid: str,
        lid: str,
        action: str,
        target: str,
        value: str,
        text: str,
        revision_id: str,
        project_dir: str,
        cached: dict[str, Any] | None,
        intent_blob: str,
        t0: float,
    ) -> IntentOutcome:
        """HTTP 通道：Binding cache → 启发式候选 → follow_ups → upsert。"""
        plat = "http"

        def _fail_http(
            msg: str,
            *,
            had_candidates: bool,
            fail_errors: list[str] | None = None,
        ) -> None:
            attr = classify_intent_failure(
                fail_errors,
                message=msg,
                had_candidates=had_candidates,
                intent_text=intent_blob,
                channel="http",
            )
            fail_out = IntentOutcome(
                intent_id=iid,
                binding_hit="failed",
                message=attr["detail"],
                fail_reason=attr["code"],
                fail_reason_label=attr["label"],
            )
            self._fill_trace(
                fail_out,
                plat=plat,
                t0=t0,
                candidate_count=len(fail_errors or []) if had_candidates else 0,
                resolve_strategy="http_heuristic",
                action=action,
                success=False,
            )
            self._publish_meta(fail_out)
            raise KeywordError(fail_out.message)

        # 1) cache
        if self._cache_matches(cached, channel="http", ui_plat=""):
            try:
                self._invoke(str(cached["keyword_id"]), dict(cached.get("params") or {}))
                self._invoke_follow_ups(
                    cached.get("follow_ups")
                    if isinstance(cached.get("follow_ups"), list)
                    else None
                )
                if lid and cached.get("provisional"):
                    confirm_step_binding(project_dir, lid, iid)
                if lid:
                    note_step_run(project_dir, lid, iid, success=True, healed=False)
                hit = IntentOutcome(
                    intent_id=iid,
                    binding_hit="cache",
                    keyword_id=str(cached["keyword_id"]),
                )
                self._fill_trace(
                    hit,
                    plat=plat,
                    t0=t0,
                    candidate_count=1,
                    resolve_strategy="http_cache",
                    action=action,
                    success=True,
                )
                if _is_assert_action(action) or (
                    isinstance(cached.get("follow_ups"), list) and cached.get("follow_ups")
                ):
                    hit.verification_status = "passed"
                self._publish_meta(hit)
                return hit
            except (KeywordError, RuntimeError, OSError, TypeError, ValueError) as cache_exc:
                if lid:
                    note_step_run(project_dir, lid, iid, success=False)
                if lid and cached.get("provisional") and isinstance(cached.get("previous"), dict):
                    rolled = rollback_step_binding(
                        project_dir, lid, iid, reason=str(cache_exc)[:240]
                    )
                    if rolled and rolled.get("keyword_id"):
                        try:
                            self._invoke(
                                str(rolled["keyword_id"]),
                                dict(rolled.get("params") or {}),
                            )
                            self._invoke_follow_ups(
                                rolled.get("follow_ups")
                                if isinstance(rolled.get("follow_ups"), list)
                                else None
                            )
                            rolled_out = IntentOutcome(
                                intent_id=iid,
                                binding_hit="rolled_back",
                                keyword_id=str(rolled["keyword_id"]),
                                rolled_back=True,
                                message="误愈已回滚并采用上一版 Binding",
                            )
                            self._fill_trace(
                                rolled_out,
                                plat=plat,
                                t0=t0,
                                candidate_count=1,
                                resolve_strategy="rolled_back",
                                action=action,
                                success=True,
                            )
                            self._publish_meta(rolled_out)
                            return rolled_out
                        except (KeywordError, RuntimeError, OSError, TypeError, ValueError):
                            pass
                # cache 失败后直接启发式解析，无需再读 Binding

        act = (action or "custom").strip().lower()
        tgt = target or text
        risk_blocked: list[str] = []
        candidates = resolve_candidates(
            action=act,
            target=tgt,
            value=value,
            platform=plat,
            ctx=self.ctx,
            channel="http",
            text=text,
            blocked_out=risk_blocked,
        )
        if not candidates:
            if risk_blocked:
                # 唯一候选被风险闸门拦掉时，报风险原因而不是含糊的“解析失败”

                assert_intent_keyword_allowed(risk_blocked[0], source="intent_http")
            _fail_http(
                f"无法解析 HTTP 意图: {text or target or iid}",
                had_candidates=False,
            )

        attempt_errors: list[str] = []
        for cand in candidates:
            if not isinstance(cand, dict):
                continue
            kid = str(cand.get("keyword_id") or "").strip()
            params = dict(cand.get("params") or {})
            if not kid:
                continue
            try:
                self._invoke(kid, params)
                follow_ups = (
                    list(cand.get("follow_ups") or [])
                    if isinstance(cand.get("follow_ups"), list)
                    else []
                )
                self._invoke_follow_ups(follow_ups)
                if lid:
                    upsert_step_binding(
                        project_dir,
                        lid,
                        iid,
                        platform="http",
                        keyword_id=kid,
                        params=params,
                        candidates=candidates,
                        resolver=str(cand.get("resolver") or "http_heuristic"),
                        revision_id=revision_id,
                        provisional=False,
                        channel="http",
                        method=str(cand.get("method") or ""),
                        path=str(cand.get("path") or params.get("url") or ""),
                        assert_spec=(
                            dict(cand.get("assert") or {})
                            if isinstance(cand.get("assert"), dict)
                            else None
                        ),
                        follow_ups=follow_ups or None,
                    )
                resolved = IntentOutcome(
                    intent_id=iid,
                    binding_hit="resolved",
                    keyword_id=kid,
                )
                self._fill_trace(
                    resolved,
                    plat=plat,
                    t0=t0,
                    candidate_count=len(candidates),
                    resolve_strategy="http_heuristic",
                    action=action,
                    success=True,
                )
                if follow_ups or _is_assert_action(action):
                    resolved.verification_status = "passed"
                self._publish_meta(resolved)
                return resolved
            except (KeywordError, RuntimeError, OSError, TypeError, ValueError) as exc:
                attempt_errors.append(f"{kid}: {exc}")
                continue

        _fail_http(
            "; ".join(attempt_errors[:3]) or f"HTTP 意图执行失败: {text or target}",
            had_candidates=True,
            fail_errors=attempt_errors,
        )
        raise AssertionError("unreachable")  # pragma: no cover

    def run(
        self,
        *,
        intent_id: str,
        action: str,
        target: str = "",
        value: str = "",
        text: str = "",
        logical_case_id: str = "",
        revision_id: str = "",
        channel: str = "ui",
    ) -> IntentOutcome:

        iid = (intent_id or "").strip() or "s1"
        lid = (logical_case_id or self._logical_case_id()).strip()
        plat = detect_platform(self.ctx)
        project_dir = self._project_dir()
        doc = load_binding(project_dir, lid) if lid else {"steps": {}}
        steps = doc.get("steps") if isinstance(doc.get("steps"), dict) else {}
        cached = steps.get(iid) if isinstance(steps.get(iid), dict) else None
        budget_ms = heal_budget_ms()
        cand_timeout = heal_candidate_timeout_ms()
        t0 = time.monotonic()
        intent_blob = " ".join(
            x for x in (text, action, target, value) if x
        ).strip()
        eff = effective_channel(
            normalize_channel(channel),
            cached=cached,
            intent_text=intent_blob,
            action=action,
            target=target,
            value=value,
        )
        if eff == "http":
            return self._run_http(
                iid=iid,
                lid=lid,
                action=action,
                target=target,
                value=value,
                text=text,
                revision_id=revision_id,
                project_dir=project_dir,
                cached=cached,
                intent_blob=intent_blob,
                t0=t0,
            )

        # 1) cache
        cache_failed = False
        if self._cache_matches(cached, channel="ui", ui_plat=plat):
            # noinspection PyBroadException
            try:
                self._invoke(str(cached["keyword_id"]), dict(cached.get("params") or {}))
                if lid and cached.get("provisional"):
                    confirm_step_binding(project_dir, lid, iid)
                if lid:
                    note_step_run(project_dir, lid, iid, success=True, healed=False)
                out = IntentOutcome(
                    intent_id=iid,
                    binding_hit="cache",
                    keyword_id=str(cached["keyword_id"]),
                )
                self._fill_trace(
                    out,
                    plat=plat,
                    t0=t0,
                    candidate_count=1,
                    resolve_strategy="cache",
                    action=action,
                    success=True,
                )
                self._publish_meta(out)
                return out
            except Exception as cache_exc:  # noqa: BLE001
                cache_failed = True
                if lid:
                    note_step_run(project_dir, lid, iid, success=False)
                # 误愈：provisional 缓存失败 → 回滚上一版再试一次
                if lid and cached.get("provisional") and isinstance(cached.get("previous"), dict):
                    rolled = rollback_step_binding(
                        project_dir,
                        lid,
                        iid,
                        reason=str(cache_exc)[:240],
                    )
                    if rolled and rolled.get("keyword_id"):
                        # noinspection PyBroadException
                        try:
                            self._invoke(
                                str(rolled["keyword_id"]),
                                dict(rolled.get("params") or {}),
                            )
                            out = IntentOutcome(
                                intent_id=iid,
                                binding_hit="rolled_back",
                                keyword_id=str(rolled["keyword_id"]),
                                rolled_back=True,
                                message="误愈已回滚并采用上一版 Binding",
                            )
                            self._fill_trace(
                                out,
                                plat=plat,
                                t0=t0,
                                candidate_count=1,
                                resolve_strategy="rolled_back",
                                action=action,
                                success=True,
                            )
                            self._publish_meta(out)
                            return out
                        except Exception:  # noqa: BLE001
                            pass
                # fall through to heal / resolve
                cached = load_binding(project_dir, lid).get("steps", {}).get(iid) if lid else cached
                if not isinstance(cached, dict):
                    cached = None

        # 自愈预算从「开始换候选」起算，不把 cache 失败耗时算进去
        heal_t0 = time.monotonic()
        _ = cache_failed  # 语义标记：进入自愈/解析路径
        act = (action or "custom").strip().lower()
        tgt = target or text
        candidates = resolve_candidates(
            action=act,
            target=tgt,
            value=value,
            platform=plat,
            ctx=self.ctx,
            channel="ui",
        )
        # 自愈时优先新鲜候选；跳过与失败 cache locator 相同的项
        if cached and isinstance(cached.get("candidates"), list):
            failed_loc = str((cached.get("params") or {}).get("locator") or "")
            merged = list(candidates) + list(cached.get("candidates") or [])
            seen: set[str] = set()
            uniq: list[dict[str, Any]] = []
            for c in merged:
                if not isinstance(c, dict):
                    continue
                loc = str(c.get("locator") or (c.get("params") or {}).get("locator") or "")
                if failed_loc and loc == failed_loc:
                    continue
                key = f"{c.get('keyword_id')}|{loc}"
                if key in seen:
                    continue
                seen.add(key)
                uniq.append(c)
            candidates = uniq

        if not candidates:
            candidates = resolve_candidates(
                action=act,
                target=tgt,
                value=value,
                platform=plat,
                ctx=self.ctx,
                include_vision=True,
                channel="ui",
            )

        if not candidates:
            attr = classify_intent_failure(
                had_candidates=False,
                message=f"无法解析意图: {text or target or iid}",
                intent_text=intent_blob,
                channel="ui",
            )
            out = IntentOutcome(
                intent_id=iid,
                binding_hit="failed",
                message=attr["detail"],
                fail_reason=attr["code"],
                fail_reason_label=attr["label"],
            )
            self._fill_trace(
                out,
                plat=plat,
                t0=t0,
                candidate_count=0,
                resolve_strategy="heuristic",
                action=action,
                success=False,
            )
            self._publish_meta(out)
            raise KeywordError(out.message)

        errors: list[str] = []
        heal_count = int((cached or {}).get("heal_count") or 0)
        tried: set[str] = set()
        budget_exhausted = False
        vision_shot_used = False

        def _elapsed_ms() -> int:
            return int((time.monotonic() - heal_t0) * 1000)

        def _attempt(cands: list[dict[str, Any]], *, healing: bool) -> IntentOutcome | None:
            nonlocal heal_count, budget_exhausted, vision_shot_used
            for cand in cands[: MAX_HEAL_TRIES + 1]:
                if healing and _elapsed_ms() >= budget_ms:
                    budget_exhausted = True
                    errors.append(f"heal_budget_exceeded:{budget_ms}ms")
                    break
                kid = str(cand.get("keyword_id") or "").strip()
                params = dict(cand.get("params") or {})
                if not kid:
                    continue
                try_key = f"{kid}|{cand.get('locator')}"
                if try_key in tried:
                    continue
                tried.add(try_key)
                invoke_params = (
                    self._with_short_timeout(params, cand_timeout) if healing else params
                )
                # noinspection PyBroadException
                try:
                    self._invoke(kid, invoke_params)
                    hit_kind = "healed" if (cached or len(tried) > 1) else "resolved"
                    resolver = str(cand.get("resolver") or "heuristic")
                    if resolver == "vision":
                        vision_shot_used = bool(
                            self.ctx.get_var("__last_vision_used_screenshot__")
                        )
                    if lid:
                        upsert_step_binding(
                            project_dir,
                            lid,
                            iid,
                            platform=plat,
                            keyword_id=kid,
                            params=params,
                            candidates=cands,
                            resolver=resolver,
                            heal_count=heal_count + (1 if hit_kind == "healed" else 0),
                            revision_id=revision_id,
                            provisional=(hit_kind == "healed"),
                        )
                        note_step_run(
                            project_dir,
                            lid,
                            iid,
                            success=True,
                            healed=(hit_kind == "healed"),
                        )
                    outcome = IntentOutcome(
                        intent_id=iid,
                        binding_hit=hit_kind,
                        heal_applied=hit_kind == "healed",
                        keyword_id=kid,
                    )
                    self._fill_trace(
                        outcome,
                        plat=plat,
                        t0=t0,
                        candidate_count=len(cands),
                        resolve_strategy=_strategy_from_resolver(
                            resolver, healing=hit_kind == "healed"
                        ),
                        used_screenshot=vision_shot_used if resolver == "vision" else False,
                        action=action,
                        success=True,
                    )
                    self._publish_meta(outcome)
                    return outcome
                except Exception as exc:  # noqa: BLE001  关键字失败需试下一候选
                    errors.append(f"{kid}: {exc}")
                    continue
            return None

        attempt_hit = _attempt(candidates, healing=bool(cached))
        if attempt_hit is not None:
            return attempt_hit

        try:
            from .config import vision_when  # 延迟：仅 Vision 回退
            from .vision import vision_enabled

            if vision_enabled() and vision_when() == "fallback" and _elapsed_ms() < budget_ms:
                for enh in (False, True):
                    if _elapsed_ms() >= budget_ms:
                        budget_exhausted = True
                        break
                    boosted = resolve_candidates(
                        action=act,
                        target=tgt,
                        value=value,
                        platform=plat,
                        ctx=self.ctx,
                        include_vision=True,
                        vision_enhanced=enh,
                        channel="ui",
                    )
                    extra = [
                        c
                        for c in boosted
                        if isinstance(c, dict)
                        and str(c.get("resolver") or "") == "vision"
                        and f"{c.get('keyword_id')}|{c.get('locator')}" not in tried
                    ]
                    if not extra:
                        continue
                    attempt_hit = _attempt(extra, healing=True)
                    if attempt_hit is not None:
                        return attempt_hit
                    if enh:
                        break
        except (ImportError, OSError, RuntimeError, TypeError, ValueError, AttributeError):
            pass

        attr = classify_intent_failure(
            errors,
            message="; ".join(errors[:3]) or f"意图执行失败: {text or target}",
            had_candidates=True,
            intent_text=intent_blob,
            channel="ui",
        )
        if budget_exhausted and attr["code"] not in ("timeout",):
            attr = {
                "code": "timeout",
                "label": "超时",
                "detail": f"自愈预算用尽({budget_ms}ms); {attr['detail']}"[:240],
            }
        if lid:
            note_step_run(project_dir, lid, iid, success=False)
        out = IntentOutcome(
            intent_id=iid,
            binding_hit="failed",
            heal_applied=False,
            message=attr["detail"],
            fail_reason=attr["code"],
            fail_reason_label=attr["label"],
        )
        self._fill_trace(
            out,
            plat=plat,
            t0=t0,
            candidate_count=len(candidates),
            resolve_strategy="heal" if cached else "heuristic",
            used_screenshot=vision_shot_used,
            action=action,
            success=False,
        )
        self._publish_meta(out)
        raise KeywordError(out.message)

    def _publish_meta(self, out: IntentOutcome) -> None:
        self.ctx.set_var(
            "__last_intent_meta__",
            {
                "intent_id": out.intent_id,
                "binding_hit": out.binding_hit,
                "heal_applied": out.heal_applied,
                "keyword_id": out.keyword_id,
                "fail_reason": out.fail_reason,
                "fail_reason_label": out.fail_reason_label,
                "rolled_back": out.rolled_back,
                "resolve_strategy": out.resolve_strategy,
                "candidate_count": out.candidate_count,
                "perception_platform": out.perception_platform,
                "perception_element_count": out.perception_element_count,
                "perception_used_screenshot": out.perception_used_screenshot,
                "latency_ms": out.latency_ms,
                "vision_tokens": out.vision_tokens,
                "verification_status": out.verification_status,
            },
        )


def run_intent_act(ctx: Any, **params: Any) -> None:
    IntentRuntime(ctx).run(
        intent_id=str(params.get("intent_id") or ""),
        action=str(params.get("action") or "custom"),
        target=str(params.get("target") or ""),
        value=str(params.get("value") or ""),
        text=str(params.get("text") or ""),
        logical_case_id=str(params.get("logical_case_id") or ""),
        revision_id=str(params.get("revision_id") or ""),
        channel=str(params.get("channel") or "ui"),
    )
