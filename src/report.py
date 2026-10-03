"""中文报告：申请方材料核对、联审会方案说明与组合取舍。

报告中每一项结论都标注证据类别：
【客观指标】来自申报材料/资源台账，可溯源到文号与事件ID；
【测算假设】引擎口径与系数，列出原文供质疑替换；
【专家意见】仅摘自 OPINION_RECORDED。
"""
from __future__ import annotations

from src.domain import material_gaps, EVENT_LEVEL_LABELS
from src.planner import PLAN_LABELS

VERDICT_LABELS = {
    "FEASIBLE": "可同时兑现（测算可行）",
    "CONDITIONAL": "有条件可行（须先满足下列条件）",
    "INFEASIBLE": "现有资源下不可同时兑现",
}

DIMENSION_LABELS = {
    "VENUE": "场馆",
    "POLICE": "警力",
    "TRAFFIC": "交通",
    "BUDGET": "财政",
    "HISTORY": "履约记录",
    "MATERIAL": "申报材料",
}

SEVERITY_LABELS = {"BLOCKER": "阻断", "WARNING": "警示", "INFO": "提示"}

EVIDENCE_LABELS = {"OBJECTIVE": "客观指标", "ASSUMPTION": "测算假设", "EXPERT": "专家意见"}

SCORE_LABELS = {
    "mass_participation": "群众普及",
    "fiscal_safety": "财政安全",
    "traffic_smoothness": "交通顺畅",
    "market_return": "市场回报",
}


# ---------------------------------------------------------------------------
# 申请方：材料缺口 + 约束来源
# ---------------------------------------------------------------------------

def applicant_gap_report(service, application_code: str) -> dict:
    app = service.applications[application_code]
    gaps = material_gaps(app)
    # 与该申请相关的约束来源
    sources: list[dict] = []
    venue_code = app["venue_requirement"]["primary_venue_code"]
    venue = service.registry.venue(venue_code)
    if venue:
        for b in venue.blocked:
            sources.append({
                "dimension": "VENUE",
                "source_system": b.source_system,
                "source_ref": b.source_ref,
                "event_id": b.event_id,
                "detail": f"{venue.resource_name} 日历占用 {b.start}~{b.end}：{b.reason}",
            })
    tr = app["time_requirement"]["preferred_windows"][0]
    for rtype, label in (("POLICE", "警力"), ("TRAFFIC", "交通")):
        for res in service.registry.all(rtype):
            for b in service.registry.blocking_within(rtype, res.resource_code, tr["start"], tr["end"]):
                sources.append({
                    "dimension": rtype,
                    "source_system": b.source_system,
                    "source_ref": b.source_ref,
                    "event_id": b.event_id,
                    "detail": f"{res.resource_name}：{b.reason}（{b.start}~{b.end}）",
                })
    applicant_code = (app.get("applicant") or {}).get("credit_code") or application_code
    for rec in service.registry.history(applicant_code):
        sources.append({
            "dimension": "HISTORY",
            "source_system": "履约台账",
            "source_ref": rec.source_ref,
            "event_id": rec.event_id,
            "detail": f"{rec.year} 年《{rec.event_name}》{rec.performance}：{rec.note}",
        })
    return {
        "application_code": application_code,
        "event_name": app["event_name"],
        "event_level": EVENT_LEVEL_LABELS.get(app["event_level"], app["event_level"]),
        "gaps": gaps,
        "constraint_sources": sources,
    }


def render_applicant_report(data: dict) -> str:
    lines = [
        f"承办申报材料核对单：{data['event_name']}（{data['application_code']}）",
        f"赛事级别：{data['event_level']}",
        "",
        f"一、材料缺口（共 {len(data['gaps'])} 项，均为客观核对结果）",
    ]
    if not data["gaps"]:
        lines.append("  无：八要素齐备且口径自洽。")
    for gap in data["gaps"]:
        lines.append(
            f"  [{SEVERITY_LABELS[gap['severity']]}] {gap['section']}｜{gap['label']}：{gap['detail']}"
        )
    lines += ["", "二、约束来源（资源日历与台账中的客观记录，冲突核对以此为准）"]
    if not data["constraint_sources"]:
        lines.append("  申报时段内未检索到场馆/警力/交通占用记录（无记录不代表已预留）。")
    for s in data["constraint_sources"]:
        lines.append(
            f"  · {DIMENSION_LABELS.get(s['dimension'], s['dimension'])}｜{s['detail']} "
            f"[来源 {s['source_system'] or '未注明系统'} 文号 {s['source_ref'] or '—'}，事件 {s['event_id']}]"
        )
    lines += ["", "提示：补齐阻断类材料后相关方案将自动重算；材料更正只影响与本赛事有关的组合。"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 单方案说明
# ---------------------------------------------------------------------------

def scenario_report(service, scenario_code: str, version: int | None = None) -> dict:
    view = service.get_scenario(scenario_code, version)
    p = view["payload"]
    opinions = [
        e["payload"] for e in service.opinions.get(scenario_code, [])
        if version is None or e["payload"].get("scenario_version") == version
    ]
    return {
        "view": view,
        "opinions": opinions,
        "applications": [service.applications[c] for c in p["application_codes"]],
    }


def render_scenario_report(data: dict) -> str:
    view = data["view"]
    p = view["payload"]
    apps = data["applications"]
    v = view["version"]
    lines = [
        f"联审方案说明 {p['scenario_code']}（版本 v{v}）",
        f"组合方式：{PLAN_LABELS.get(p['plan_type'], p['plan_type'])}",
        f"时间窗：{p['window']['start']} ~ {p['window']['end']}（主要计入 {p['fiscal_year']} 预算年度）",
        f"包含赛事：{'、'.join(a['event_name'] for a in apps)}",
        f"安排说明：{p.get('note', '')}",
        "",
        f"系统测算结论：{VERDICT_LABELS[p['verdict']]}",
        "※ 该结论仅为资源核对结果，不是批准；是否批准由有权部门凭文号另行公示。",
    ]
    if view.get("published"):
        pub = view["published"]
        lines.append(f"※ 本版本已经公示：{pub['decision_ref']}，决定 {pub['decision']}，"
                     f"作出机关 {pub['deciding_authority']}。公示版本封存可回看。")

    lines += ["", "一、客观指标（直接来自资源台账/申报材料）"]
    objective_metrics = {k: m for k, m in p["metrics"].items() if m.get("evidence_class") == "OBJECTIVE"}
    if objective_metrics:
        for key, m in objective_metrics.items():
            refs = "；".join(m.get("source_refs", []))
            lines.append(f"  · {key}: {m['value']} {m.get('unit', '')} {f'（{refs}）' if refs else ''}")
    else:
        lines.append("  （本方案暂无已登记的客观资源指标）")

    lines += ["", "二、测算假设（口径与系数，可被专家质疑后替换重算）"]
    seen = set()
    for a in p["assumptions"]:
        if a["key"] in seen:
            continue
        seen.add(a["key"])
        lines.append(f"  · [{a['key']}] {a['statement']}")
    derived = {k: m for k, m in p["metrics"].items() if m.get("evidence_class") == "ASSUMPTION"}
    for key, m in derived.items():
        lines.append(f"  ↳ 派生指标 {key}: {m['value']} {m.get('unit', '')}")

    lines += ["", "三、冲突与条件（按证据类别分列）"]
    for cls in ("OBJECTIVE", "ASSUMPTION", "EXPERT"):
        items = [c for c in p["conflicts"] if c["evidence_class"] == cls]
        if not items:
            continue
        lines.append(f"  【{EVIDENCE_LABELS[cls]}】")
        for c in sorted(items, key=lambda x: {"BLOCKER": 0, "WARNING": 1, "INFO": 2}[x["severity"]]):
            refs = f" 来源：{'；'.join(c.get('source_refs', []))}" if c.get("source_refs") else ""
            lines.append(f"  [{SEVERITY_LABELS[c['severity']]}][{DIMENSION_LABELS.get(c['dimension'], c['dimension'])}] {c['message']}{refs}")
    if p.get("conditions"):
        lines += ["", "  放行前必须满足的条件："]
        for cond in p["conditions"]:
            lines.append(f"  ▸ {cond}")

    lines += ["", "四、四维参考分（测算分，0-100，越高越好；非专家评分）"]
    for key, label in SCORE_LABELS.items():
        val = p["scores"].get(key)
        lines.append(f"  · {label}: {'未登记资源，无法测算' if val is None else val}")

    lines += ["", "五、专家意见（证据类别：专家意见，仅供决策参考）"]
    if not data["opinions"]:
        lines.append("  暂无专家意见记录。")
    for o in data["opinions"]:
        w = f"，建议权重 {o['weight_suggestion']}" if o.get("weight_suggestion") is not None else ""
        lines.append(f"  · {o['expert'].get('name', '')}（{o['expert'].get('title', '')}）[{o['dimension']}]{w}：{o['statement']}")

    if p.get("reevaluated_fields"):
        lines += ["", f"六、本版本变化触发因素：{'、'.join(p['reevaluated_fields'])}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 组合对比与取舍
# ---------------------------------------------------------------------------

def comparison_overview(service, scenario_codes: list[str]) -> dict:
    rows = []
    for code in scenario_codes:
        view = service.get_scenario(code)
        p = view["payload"]
        rows.append(
            {
                "scenario_code": code,
                "version": view["version"],
                "plan_type": p["plan_type"],
                "verdict": p["verdict"],
                "window": f"{p['window']['start']}~{p['window']['end']}",
                "scores": p["scores"],
                "blockers": [c for c in p["conflicts"] if c["severity"] == "BLOCKER"],
                "warnings": [c for c in p["conflicts"] if c["severity"] == "WARNING"],
                "conditions": p.get("conditions", []),
                "note": p.get("note", ""),
                "decision_ref": view.get("published", {}).get("decision_ref") if view.get("published") else None,
            }
        )
    return {"rows": rows}


def render_comparison(overview: dict, chosen: str | None = None, waived: list[str] | None = None) -> str:
    rows = overview["rows"]
    lines = ["联审会组合对比（同一赛事集合的不同摆法）", ""]
    header = f"{'方案':<14}{'组合':<8}{'测算结论':<10}{'群众':>5}{'财政':>6}{'交通':>6}{'市场':>6}  时间窗"
    lines.append(header)
    lines.append("-" * 78)
    for r in rows:
        s = r["scores"]
        def fmt(v):
            return "  — " if v is None else f"{v:5.1f}"
        mark = "★" if r["scenario_code"] == chosen else " "
        lines.append(
            f"{mark}{r['scenario_code']:<13}{PLAN_LABELS[r['plan_type']]:<8}"
            f"{VERDICT_LABELS[r['verdict']].split('（')[0]:<10}"
            f"{fmt(s['mass_participation']):>6}{fmt(s['fiscal_safety']):>6}"
            f"{fmt(s['traffic_smoothness']):>6}{fmt(s['market_return']):>6}  {r['window']}"
        )
    lines += ["", "取舍说明（客观阻断先行，分数仅作权衡参考）："]
    for r in rows:
        tag = "拟选" if r["scenario_code"] == chosen else ("放弃" if r["scenario_code"] in (waived or []) else "备选")
        lines.append(f"  [{tag}] {r['scenario_code']}（{r['note']}）")
        if r["blockers"]:
            lines.append("    放弃/不能通过的硬原因（客观指标或测算假设下超容）：")
            for c in r["blockers"]:
                lines.append(f"      - [{EVIDENCE_LABELS[c['evidence_class']]}][{DIMENSION_LABELS.get(c['dimension'], c['dimension'])}] {c['message']}")
        if r["conditions"]:
            lines.append("    需先落实：")
            for cond in r["conditions"][:4]:
                lines.append(f"      ▸ {cond}")
    lines += [
        "",
        "权衡口径：群众普及与市场回报衡量办赛收益，财政安全与交通顺畅衡量承载代价；",
        "四维分数均为系统测算分，专家可在会上记录不同权重与判断（OPINION_RECORDED）。",
        "最终批准/驳回/缓议只能由有权部门作出并带文号公示；本对比不构成批准。",
    ]
    return "\n".join(lines)
