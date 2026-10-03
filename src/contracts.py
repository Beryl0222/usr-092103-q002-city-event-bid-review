"""领域事件契约：信封与载荷校验。

仅依赖标准库；外部系统可直接对照 contracts/domain.schema.json，
本模块提供同等的运行期最小校验，保持对早期 validate_event 的兼容。
"""
from __future__ import annotations

from datetime import date, datetime

REQUIRED = (
    "event_id",
    "event_type",
    "aggregate_type",
    "aggregate_id",
    "occurred_at",
    "version",
    "summary",
)

EVENT_TYPES = (
    "APPLICATION_RECEIVED",
    "APPLICATION_AMENDED",
    "CONSTRAINT_REGISTERED",
    "SCENARIO_EVALUATED",
    "OPINION_RECORDED",
    "DECISION_PUBLISHED",
)

AGGREGATE_TYPES = (
    "hosting_application",
    "resource_constraint",
    "review_scenario",
    "decision_release",
)

ACTOR_ROLES = (
    "APPLICANT",
    "EXPERT",
    "COMPETENT_AUTHORITY",
    "RESOURCE_SYSTEM",
    "SYSTEM",
)

EVENT_LEVELS = (
    "PRO_LEAGUE",
    "MASS_PARTICIPATION",
    "INTERNATIONAL_INVITATIONAL",
    "OTHER",
)

FLEXIBILITY = ("FIXED", "WEEKEND_FLEXIBLE", "WINDOW_FLEXIBLE")

RESOURCE_TYPES = ("VENUE", "POLICE", "TRAFFIC", "BUDGET", "HISTORY")

VERDICTS = ("FEASIBLE", "CONDITIONAL", "INFEASIBLE")

AMENDMENT_TYPES = (
    "VENUE_CHANGE",
    "CO_HOSTING",
    "POSTPONEMENT",
    "MATERIAL_CORRECTION",
)

# event_type -> 合法 aggregate_type
EVENT_AGGREGATE = {
    "APPLICATION_RECEIVED": "hosting_application",
    "APPLICATION_AMENDED": "hosting_application",
    "CONSTRAINT_REGISTERED": "resource_constraint",
    "SCENARIO_EVALUATED": "review_scenario",
    "OPINION_RECORDED": "review_scenario",
    "DECISION_PUBLISHED": "decision_release",
}

APPLICATION_REQUIRED = (
    "application_code",
    "event_name",
    "event_level",
    "time_requirement",
    "venue_requirement",
    "expected_attendance",
    "funding_structure",
    "safety_responsibility",
    "market_development",
    "legacy_plan",
)

CONSTRAINT_REQUIRED = ("resource_type", "resource_code")

SCENARIO_REQUIRED = (
    "scenario_code",
    "application_codes",
    "window",
    "fiscal_year",
    "verdict",
    "metrics",
    "assumptions",
    "conflicts",
    "scores",
)

OPINION_REQUIRED = ("scenario_code", "expert", "dimension", "statement")

DECISION_REQUIRED = (
    "scenario_code",
    "scenario_version",
    "deciding_authority",
    "decision_ref",
    "decision",
)


def _is_datetime(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


def _is_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _check_window(win: object, path: str, errors: list[str]) -> None:
    if not isinstance(win, dict):
        errors.append(f"{path} 必须是时间窗对象")
        return
    for key in ("start", "end"):
        if not _is_date(win.get(key)):
            errors.append(f"{path}.{key} 必须是 YYYY-MM-DD 日期")
    if _is_date(win.get("start")) and _is_date(win.get("end")):
        if date.fromisoformat(win["start"]) > date.fromisoformat(win["end"]):
            errors.append(f"{path} 的 start 晚于 end")


def validate_event(record: dict) -> list[str]:
    """校验事件公共字段；存在 payload 时同时校验载荷。返回错误信息列表。"""
    errors: list[str] = [
        f"缺少字段：{name}" for name in REQUIRED if name not in record
    ]
    if errors:
        return errors

    if record["event_type"] not in EVENT_TYPES:
        errors.append(f"event_type 非法：{record['event_type']}")
    if record["aggregate_type"] not in AGGREGATE_TYPES:
        errors.append(f"aggregate_type 非法：{record['aggregate_type']}")
    if not isinstance(record["event_id"], str) or not record["event_id"]:
        errors.append("event_id 必须是非空字符串")
    if not isinstance(record["aggregate_id"], str) or not record["aggregate_id"]:
        errors.append("aggregate_id 必须是非空字符串")
    if not _is_datetime(record["occurred_at"]):
        errors.append("occurred_at 必须是 ISO date-time")
    if not isinstance(record["version"], int) or isinstance(record["version"], bool) or record["version"] < 1:
        errors.append("version 必须是正整数")
    if not isinstance(record["summary"], str) or not record["summary"]:
        errors.append("summary 必须是非空字符串")

    event_type = record.get("event_type")
    aggregate_type = record.get("aggregate_type")
    expected_agg = EVENT_AGGREGATE.get(event_type)
    if expected_agg and aggregate_type != expected_agg:
        errors.append(
            f"{event_type} 的 aggregate_type 必须是 {expected_agg}，实际为 {aggregate_type}"
        )

    actor = record.get("actor")
    if actor is not None:
        if not isinstance(actor, dict) or actor.get("role") not in ACTOR_ROLES:
            errors.append("actor.role 非法")

    payload = record.get("payload")
    if payload is not None:
        errors.extend(_validate_payload(event_type, payload))
    return errors


def _validate_payload(event_type: str, payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return ["payload 必须是对象"]
    if event_type in ("APPLICATION_RECEIVED", "APPLICATION_AMENDED"):
        return _validate_application(event_type, payload)
    if event_type == "CONSTRAINT_REGISTERED":
        return _validate_constraint(payload)
    if event_type == "SCENARIO_EVALUATED":
        return _validate_scenario(payload)
    if event_type == "OPINION_RECORDED":
        return _validate_opinion(payload)
    if event_type == "DECISION_PUBLISHED":
        return _validate_decision(payload)
    return []


def _validate_application(event_type: str, p: dict) -> list[str]:
    errors = [
        f"payload 缺少字段：{name}"
        for name in APPLICATION_REQUIRED
        if name not in p
    ]
    if errors:
        return errors
    if p["event_level"] not in EVENT_LEVELS:
        errors.append(f"event_level 非法：{p['event_level']}")

    tr = p["time_requirement"]
    if not isinstance(tr, dict) or "preferred_windows" not in tr or "flexibility" not in tr:
        errors.append("time_requirement 需要 preferred_windows 与 flexibility")
    else:
        if tr["flexibility"] not in FLEXIBILITY:
            errors.append(f"flexibility 非法：{tr['flexibility']}")
        windows = tr["preferred_windows"]
        if not isinstance(windows, list) or not windows:
            errors.append("preferred_windows 至少一个时间窗")
        else:
            for i, win in enumerate(windows):
                _check_window(win, f"preferred_windows[{i}]", errors)

    vr = p["venue_requirement"]
    if not isinstance(vr, dict) or not vr.get("primary_venue_code"):
        errors.append("venue_requirement.primary_venue_code 必填")

    att = p["expected_attendance"]
    if not isinstance(att, dict) or not isinstance(att.get("single_day_peak"), int) or att["single_day_peak"] < 0:
        errors.append("expected_attendance.single_day_peak 必须是非负整数")

    fs = p["funding_structure"]
    for name in ("total_budget_cny", "government_request_cny"):
        if not isinstance(fs, dict) or not isinstance(fs.get(name), (int, float)) or fs[name] < 0:
            errors.append(f"funding_structure.{name} 必须是非负数")

    sr = p["safety_responsibility"]
    if not isinstance(sr, dict) or not sr.get("responsible_party"):
        errors.append("safety_responsibility.responsible_party 必填")

    for name in ("market_development", "legacy_plan"):
        if not isinstance(p.get(name), dict):
            errors.append(f"{name} 必须是对象")

    if event_type == "APPLICATION_AMENDED":
        amend = p.get("amendment")
        if not isinstance(amend, dict):
            errors.append("APPLICATION_AMENDED 必须携带 amendment")
        else:
            if amend.get("amendment_type") not in AMENDMENT_TYPES:
                errors.append("amendment.amendment_type 非法")
            if not isinstance(amend.get("changed_fields"), list) or not amend["changed_fields"]:
                errors.append("amendment.changed_fields 至少一个字段")
    return errors


def _validate_constraint(p: dict) -> list[str]:
    errors = [
        f"payload 缺少字段：{name}"
        for name in CONSTRAINT_REQUIRED
        if name not in p
    ]
    if errors:
        return errors
    if p["resource_type"] not in RESOURCE_TYPES:
        errors.append(f"resource_type 非法：{p['resource_type']}")
    for i, win in enumerate(p.get("blocked_windows", [])):
        _check_window(win, f"blocked_windows[{i}]", errors)
    for i, rec in enumerate(p.get("records", [])):
        if not isinstance(rec, dict) or not rec.get("applicant_code") or not rec.get("performance"):
            errors.append(f"records[{i}] 需要 applicant_code 与 performance")
    return errors


def _validate_scenario(p: dict) -> list[str]:
    errors = [
        f"payload 缺少字段：{name}"
        for name in SCENARIO_REQUIRED
        if name not in p
    ]
    if errors:
        return errors
    if p["verdict"] not in VERDICTS:
        errors.append(f"verdict 非法：{p['verdict']}")
    _check_window(p.get("window"), "window", errors)
    if not isinstance(p.get("application_codes"), list) or not p["application_codes"]:
        errors.append("application_codes 至少一个申请")
    for i, c in enumerate(p.get("conflicts", [])):
        if not isinstance(c, dict) or c.get("evidence_class") not in (
            "OBJECTIVE",
            "ASSUMPTION",
            "EXPERT",
        ):
            errors.append(f"conflicts[{i}].evidence_class 必须是 OBJECTIVE/ASSUMPTION/EXPERT")
    return errors


def _validate_opinion(p: dict) -> list[str]:
    errors = [
        f"payload 缺少字段：{name}" for name in OPINION_REQUIRED if name not in p
    ]
    if errors:
        return errors
    if not isinstance(p["expert"], dict) or not p["expert"].get("name"):
        errors.append("expert.name 必填")
    return errors


def _validate_decision(p: dict) -> list[str]:
    return [
        f"payload 缺少字段：{name}" for name in DECISION_REQUIRED if name not in p
    ]
