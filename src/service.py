"""赛事联审事件溯源服务。

所有状态变更都表现为追加事件；当前状态由事件重放得到。关键规则：

- 临时换馆 / 联合承办 / 延期 / 材料更正：只重算受影响的方案，
  其余方案保持原版本；重算结果无实质变化不产生新版本；
- 公示（DECISION_PUBLISHED）只能由 COMPETENT_AUTHORITY 凭文号作出，
  SYSTEM 与其他角色一律拒绝——系统只测算、不批准；
- 公示所依据的方案版本整包留存，事后可逐版回看。
"""
from __future__ import annotations

import copy
import json
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from src.contracts import validate_event
from src.domain import ResourceRegistry
from src.engine import evaluate
from src.planner import generate_candidates

CST = timezone(timedelta(hours=8))

# 更正字段 -> 受影响的资源维度（用于标注 reevaluated_fields）
FIELD_DIMENSIONS = {
    "time_requirement": "时间窗",
    "venue_requirement": "场馆",
    "expected_attendance": "人流/警力/交通",
    "funding_structure": "财政",
    "event_level": "警力级别系数",
    "safety_responsibility": "安保",
    "market_development": "市场回报",
    "legacy_plan": "群众普及",
    "applicant": "履约主体",
}


class ServiceError(Exception):
    """业务拒绝（非法命令、重复事件、越权批准等）。"""


def _now() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


def _new_event_id() -> str:
    return f"evt-{uuid.uuid4().hex[:16]}"


def deep_merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def changed_top_fields(changed_fields: list[str]) -> list[str]:
    return sorted({f.split(".", 1)[0] for f in changed_fields})


class ReviewService:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self._seen_event_ids: set[str] = set()
        self._versions: dict[str, int] = defaultdict(int)
        # 重放期间只折叠状态，不再派生新事件（派生事件本就在日志中）
        self._replaying: bool = False
        # 物化状态
        self.applications: dict[str, dict] = {}
        self.registry = ResourceRegistry()
        # scenario_code -> {version: payload}
        self.scenario_versions: dict[str, dict[int, dict]] = defaultdict(dict)
        # scenario_code -> 生成参数（plan_type/assignments/note），供增量重算
        self.scenario_specs: dict[str, dict] = {}
        self.scenario_apps: dict[str, list[str]] = {}
        self.opinions: dict[str, list[dict]] = defaultdict(list)
        self.decisions: dict[str, dict] = {}          # decision_ref -> decision event
        self.release_index: dict[str, str] = {}       # scenario_code -> decision_ref（当前公示）
        # 更正后不再成立的旧方案代码（内容仍可回看，列表中标记为已失效）
        self.inactive_scenarios: set[str] = set()

    # ------------------------------------------------------------------
    # 事件追加与重放
    # ------------------------------------------------------------------
    def append(self, event: dict, *, external: bool = False) -> dict:
        errors = validate_event(event)
        if errors:
            raise ServiceError("事件不符合契约：" + "；".join(errors))
        if event["event_id"] in self._seen_event_ids:
            raise ServiceError(f"事件已存在（幂等拦截）：{event['event_id']}")
        self._seen_event_ids.add(event["event_id"])
        self.events.append(event)
        self._apply(event)
        return event

    def _next_version(self, aggregate_id: str) -> int:
        self._versions[aggregate_id] += 1
        return self._versions[aggregate_id]

    def _make_event(self, event_type: str, aggregate_type: str, aggregate_id: str,
                    summary: str, payload: dict, actor: dict | None = None,
                    source_system: str | None = None, source_ref: str | None = None,
                    correlation_id: str | None = None, causation_id: str | None = None) -> dict:
        event = {
            "event_id": _new_event_id(),
            "event_type": event_type,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "occurred_at": _now(),
            "version": self._next_version(aggregate_id),
            "summary": summary,
            "payload": payload,
        }
        if actor:
            event["actor"] = actor
        if source_system:
            event["source_system"] = source_system
        if source_ref:
            event["source_ref"] = source_ref
        if correlation_id:
            event["correlation_id"] = correlation_id
        if causation_id:
            event["causation_id"] = causation_id
        return event

    def _apply(self, event: dict) -> None:
        et = event["event_type"]
        p = event.get("payload", {})
        if et in ("APPLICATION_RECEIVED", "APPLICATION_AMENDED"):
            self.applications[p["application_code"]] = copy.deepcopy(p)
        elif et == "CONSTRAINT_REGISTERED":
            self.registry.apply(event)
            if not self._replaying:
                self._reevaluate_after_constraint(event)
        elif et == "SCENARIO_EVALUATED":
            code = p["scenario_code"]
            self.scenario_versions[code][event["version"]] = copy.deepcopy(p)
            # 重放/补录场景：从载荷重建方案规格，保证后续增量重算可用
            if "assignments" in p:
                self.scenario_specs.setdefault(
                    code,
                    {
                        "scenario_code": code,
                        "plan_type": p["plan_type"],
                        "assignments": copy.deepcopy(p["assignments"]),
                        "note": p.get("note", ""),
                    },
                )
                self.scenario_apps.setdefault(code, sorted(p["assignments"].keys()))
        elif et == "OPINION_RECORDED":
            self.opinions[p["scenario_code"]].append(event)
        elif et == "DECISION_PUBLISHED":
            self.decisions[p["decision_ref"]] = event
            self.release_index[p["scenario_code"]] = p["decision_ref"]

    # ------------------------------------------------------------------
    # 申请方命令
    # ------------------------------------------------------------------
    def submit_application(self, payload: dict, actor_name: str = "") -> dict:
        code = payload["application_code"]
        if code in self.applications:
            raise ServiceError(f"申请已存在：{code}，请使用材料更正/变更命令")
        event = self._make_event(
            "APPLICATION_RECEIVED", "hosting_application", code,
            f"收到承办申请：{payload.get('event_name', code)}",
            payload, actor={"role": "APPLICANT", "name": actor_name},
        )
        return self.append(event)

    def amend_application(self, code: str, amendment_type: str, patch: dict,
                          changed_fields: list[str], reason: str = "", actor_name: str = "") -> dict:
        if code not in self.applications:
            raise ServiceError(f"申请不存在：{code}")
        new_payload = deep_merge(self.applications[code], patch)
        new_payload["amendment"] = {
            "amendment_type": amendment_type,
            "changed_fields": changed_fields,
            "reason": reason,
        }
        label = {
            "VENUE_CHANGE": "临时换馆",
            "CO_HOSTING": "联合承办",
            "POSTPONEMENT": "延期",
            "MATERIAL_CORRECTION": "材料更正",
        }[amendment_type]
        event = self._make_event(
            "APPLICATION_AMENDED", "hosting_application", code,
            f"{label}：{self.applications[code]['event_name']}（{reason or '未填理由'}）",
            new_payload, actor={"role": "APPLICANT", "name": actor_name},
        )
        self.append(event)
        if not self._replaying:
            self._reevaluate_after_amendment(event, changed_fields)
        return event

    # ------------------------------------------------------------------
    # 外部资源系统喂送（沿用稳定事件契约：CONSTRAINT_REGISTERED）
    # ------------------------------------------------------------------
    def ingest_external(self, event: dict) -> dict:
        if event["event_type"] != "CONSTRAINT_REGISTERED":
            raise ServiceError("外部喂送当前只接收 CONSTRAINT_REGISTERED 事件")
        event.setdefault("actor", {"role": "RESOURCE_SYSTEM"})
        return self.append(event, external=True)

    # ------------------------------------------------------------------
    # 评估
    # ------------------------------------------------------------------
    def evaluate_combinations(self, application_codes: list[str]) -> list[dict]:
        apps = [self.applications[c] for c in application_codes]
        candidates = generate_candidates(apps, self.registry)
        produced = []
        for cand in candidates:
            produced.append(self._store_evaluation(cand, trigger_event_id=None, reevaluated_fields=None))
        return produced

    def _store_evaluation(self, cand: dict, trigger_event_id: str | None,
                          reevaluated_fields: list[str] | None) -> dict:
        code = cand["scenario_code"]
        self.scenario_specs.setdefault(code, cand)
        self.scenario_apps.setdefault(code, sorted(cand["assignments"].keys()))
        apps = [self.applications[c] for c in sorted(cand["assignments"].keys())]
        based = [trigger_event_id] if trigger_event_id else []
        payload = evaluate(
            applications=apps,
            assignments=cand["assignments"],
            registry=self.registry,
            plan_type=cand["plan_type"],
            reevaluated_fields=reevaluated_fields or [],
            based_on_event_ids=based,
        )
        payload["scenario_code"] = code
        payload["assignments"] = cand["assignments"]
        payload["note"] = cand.get("note", "")

        if code in self.scenario_specs and self.scenario_versions[code]:
            prev_version = max(self.scenario_versions[code])
            prev = self.scenario_versions[code][prev_version]
            if _content_fingerprint(prev) == _content_fingerprint(payload):
                # 无实质变化：不产生新版本
                return self._scenario_view(code, prev_version, changed=False)

        event = self._make_event(
            "SCENARIO_EVALUATED", "review_scenario", code,
            f"方案测算 v{self._versions[code] + 1}：{cand['plan_type']}，结论 {payload['verdict']}",
            payload, actor={"role": "SYSTEM", "name": "联审测算引擎"},
            causation_id=trigger_event_id,
        )
        self.append(event)
        return self._scenario_view(code, event["version"], changed=True)

    def _reevaluate_after_amendment(self, trigger: dict, changed_fields: list[str]) -> None:
        """申请更正/换馆/联办/延期：只重新生成涉及该申请的组合。

        窗口或场馆变化会产生新方案代码，旧方案冻结留痕；
        纯材料更正在同一方案代码上按内容指纹决定是否升版。
        """
        app_code = trigger["payload"]["application_code"]
        tags = [FIELD_DIMENSIONS.get(f, f) for f in changed_top_fields(changed_fields)]
        combos: dict[tuple[str, ...], set[str]] = defaultdict(set)
        for code, app_list in self.scenario_apps.items():
            combos[tuple(app_list)].add(code)
        for app_tuple, old_codes in combos.items():
            if app_code not in app_tuple:
                continue
            new_codes = self._regenerate_combo(list(app_tuple), trigger["event_id"], tags)
            # 已公示版本封存：不退休、不覆盖
            retired = {c for c in old_codes - new_codes if c not in self.release_index}
            self.inactive_scenarios.update(retired)

    def _regenerate_combo(self, app_codes: list[str], trigger_event_id: str | None,
                          tags: list[str]) -> set[str]:
        apps = [self.applications[c] for c in app_codes]
        candidates = generate_candidates(apps, self.registry)
        new_codes: set[str] = set()
        for cand in candidates:
            new_codes.add(cand["scenario_code"])
            if cand["scenario_code"] in self.release_index:
                continue  # 已公示方案冻结，不再重算
            self._store_evaluation(cand, trigger_event_id, tags)
        return new_codes

    def _reevaluate_after_constraint(self, trigger: dict) -> None:
        p = trigger["payload"]
        rtype, rcode = p["resource_type"], p["resource_code"]
        tags = [f"外部资源更新:{rtype}/{rcode}"]
        # 共享资源更新只重算现存且未公示的方案；冻结与历史方案保持原样可回看
        for code, spec in list(self.scenario_specs.items()):
            if code in self.inactive_scenarios or code in self.release_index:
                continue
            affected = False
            if rtype in ("POLICE", "TRAFFIC", "BUDGET", "HISTORY"):
                affected = True
            elif rtype == "VENUE":
                affected = any(
                    (asg.get("venue_override") or
                     self.applications[c]["venue_requirement"]["primary_venue_code"]) == rcode
                    for c, asg in spec["assignments"].items()
                )
            if affected:
                self._store_evaluation(spec, trigger["event_id"], tags)

    # ------------------------------------------------------------------
    # 专家意见
    # ------------------------------------------------------------------
    def record_opinion(self, scenario_code: str, expert: dict, dimension: str,
                       statement: str, weight_suggestion: float | None = None) -> dict:
        if scenario_code not in self.scenario_specs and scenario_code not in self.scenario_versions:
            raise ServiceError(f"方案不存在：{scenario_code}")
        version = max(self.scenario_versions[scenario_code]) if self.scenario_versions[scenario_code] else None
        payload = {
            "scenario_code": scenario_code,
            "scenario_version": version,
            "expert": expert,
            "dimension": dimension,
            "statement": statement,
            "evidence_class": "EXPERT",
        }
        if weight_suggestion is not None:
            payload["weight_suggestion"] = weight_suggestion
        event = self._make_event(
            "OPINION_RECORDED", "review_scenario", scenario_code,
            f"专家意见：{expert.get('name', '')} 就 {dimension} 发表意见",
            payload, actor={"role": "EXPERT", "name": expert.get("name", "")},
        )
        return self.append(event)

    # ------------------------------------------------------------------
    # 有权部门公示（系统不代批）
    # ------------------------------------------------------------------
    def publish_decision(self, actor: dict, scenario_code: str, decision: str,
                         decision_ref: str, rationale: str = "",
                         conditions: list[str] | None = None,
                         published: bool = True) -> dict:
        if actor.get("role") != "COMPETENT_AUTHORITY":
            raise ServiceError(
                "只有有权部门（COMPETENT_AUTHORITY）可以作出批准决定；"
                "系统测算结论不是批准，系统角色被禁止发布决定"
            )
        if scenario_code not in self.scenario_versions or not self.scenario_versions[scenario_code]:
            raise ServiceError(f"方案不存在：{scenario_code}")
        version = max(self.scenario_versions[scenario_code])
        payload = {
            "scenario_code": scenario_code,
            "scenario_version": version,
            "deciding_authority": actor.get("name", "") or actor.get("title", "有权部门"),
            "decision_ref": decision_ref,
            "decision": decision,
            "conditions": conditions or [],
            "rationale": rationale,
            "published": published,
        }
        event = self._make_event(
            "DECISION_PUBLISHED", "decision_release", decision_ref,
            f"{actor.get('name', '有权部门')} {decision_ref}：{decision}（方案 {scenario_code} v{version}）",
            payload, actor=actor,
        )
        return self.append(event)

    # ------------------------------------------------------------------
    # 视图
    # ------------------------------------------------------------------
    def _scenario_view(self, code: str, version: int, changed: bool) -> dict:
        payload = self.scenario_versions[code][version]
        return {
            "scenario_code": code,
            "version": version,
            "changed": changed,
            "payload": payload,
        }

    def get_scenario(self, code: str, version: int | None = None) -> dict:
        if code not in self.scenario_versions:
            raise ServiceError(f"方案不存在：{code}")
        v = version or max(self.scenario_versions[code])
        if v not in self.scenario_versions[code]:
            raise ServiceError(f"方案 {code} 不存在 v{v}（现有版本：{sorted(self.scenario_versions[code])}）")
        view = self._scenario_view(code, v, changed=False)
        ref = self.release_index.get(code)
        if ref:
            dec = self.decisions[ref]["payload"]
            if dec["scenario_version"] == v:
                view["published"] = {"decision_ref": ref, **{k: val for k, val in dec.items()
                                                             if k not in ("scenario_code", "scenario_version")}}
        return view

    def scenario_history(self, code: str) -> list[dict]:
        return [
            {
                "version": v,
                "verdict": p["verdict"],
                "plan_type": p["plan_type"],
                "window": p["window"],
                "reevaluated_fields": p.get("reevaluated_fields", []),
                "published": any(
                    d["payload"]["scenario_code"] == code and d["payload"]["scenario_version"] == v
                    for d in self.decisions.values()
                ),
                "decision_ref": next(
                    (d["payload"]["decision_ref"] for d in self.decisions.values()
                     if d["payload"]["scenario_code"] == code and d["payload"]["scenario_version"] == v),
                    None,
                ),
            }
            for v, p in sorted(self.scenario_versions[code].items())
        ]

    def list_scenarios(self, include_inactive: bool = False) -> list[dict]:
        out = []
        for code in sorted(self.scenario_versions):
            if code in self.inactive_scenarios and not include_inactive:
                continue
            v = max(self.scenario_versions[code])
            p = self.scenario_versions[code][v]
            out.append(
                {
                    "scenario_code": code,
                    "version": v,
                    "active": code not in self.inactive_scenarios,
                    "plan_type": p["plan_type"],
                    "verdict": p["verdict"],
                    "window": p["window"],
                    "scores": p["scores"],
                    "note": p.get("note", ""),
                    "decision_ref": self.release_index.get(code),
                }
            )
        return out

    def event_log(self) -> list[dict]:
        return [{"event_id": e["event_id"], "event_type": e["event_type"],
                 "aggregate_type": e["aggregate_type"], "aggregate_id": e["aggregate_id"],
                 "version": e["version"], "occurred_at": e["occurred_at"], "summary": e["summary"],
                 "source_system": e.get("source_system"), "source_ref": e.get("source_ref")}
                for e in self.events]

    # ------------------------------------------------------------------
    # 留痕与重建：事件日志即真相，状态随时可重放
    # ------------------------------------------------------------------
    def save_events(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            for e in self.events:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")

    @classmethod
    def replay(cls, path: str) -> "ReviewService":
        svc = cls()
        svc._replaying = True
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        svc.append(json.loads(line))
        finally:
            svc._replaying = False
        return svc


def _content_fingerprint(payload: dict) -> str:
    """剔除溯源元信息后的内容指纹：溯源字段变化不构成新版本。"""
    clone = copy.deepcopy(payload)
    clone.pop("based_on_event_ids", None)
    clone.pop("reevaluated_fields", None)
    return json.dumps(clone, ensure_ascii=False, sort_keys=True, default=str)
