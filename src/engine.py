"""联审测算引擎。

回答一个问题：给定赛事组合、时间窗与资源日历，场馆、警力、交通、年度财政
能否同时兑现。所有输出严格区分三类证据：

- OBJECTIVE  客观指标：直接来自申报材料或资源台账（含来源文号/事件ID）；
- ASSUMPTION 测算假设：引擎采用的系数、口径与基准，可被专家质疑替换；
- EXPERT     专家意见：仅来自 OPINION_RECORDED，引擎不代为生成。

裁定只有 FEASIBLE / CONDITIONAL / INFEASIBLE，是测算结论而非批准。
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from src.domain import material_gaps, to_date

# ---------------------------------------------------------------------------
# 测算假设（ASSUMPTION）。集中声明，报告中逐条列示，专家可要求替换后重算。
# ---------------------------------------------------------------------------
ASSUMPTIONS = {
    "SAFE_LOAD_RATIO": ("场馆安全承载率按核定容量的 90% 计（台账未另给时）", 0.90),
    "PEAK_COINCIDENCE": ("多赛事同日散场峰值重合系数 0.80（错峰散市口径）", 0.80),
    "POLICE_BASE": ("每场赛事基础警力 80 人（台账未另给时）", 80),
    "POLICE_PER_10K": ("每 1 万峰值人流增配 12 名警力（台账未另给时）", 12),
    "POLICE_LEVEL_FACTOR": ("警力级别系数：国际赛 1.5、职业联赛 1.2、群众赛 1.0、其他 1.0", None),
    "FISCAL_YEAR_SPLIT": ("财政资金按自然年口径；跨年赛事按占用天数比例分摊", None),
    "MASS_BENCHMARK": ("群众普及基准：5 万人次得参与分 60 分；遗产投入达总预算 10% 得 40 分", None),
    "FISCAL_SCORE": ("财政安全分=40+60×(1-申请额/年度可用额)；超预算即 0 分并阻断", None),
    "TRAFFIC_SCORE": ("交通顺畅分=100-100×(簇峰值需求/通道日容量)；超载即阻断", None),
    "MARKET_BENCHMARK": ("市场回报基准：直接+间接收入达到总预算 120% 得满分", 1.2),
}

LEVEL_FACTOR = {
    "PRO_LEAGUE": 1.2,
    "MASS_PARTICIPATION": 1.0,
    "INTERNATIONAL_INVITATIONAL": 1.5,
    "OTHER": 1.0,
}


def occupation_window(app: dict, win: dict) -> dict:
    """含搭建/拆除的实际占用窗。"""
    tr = app.get("time_requirement", {})
    start = to_date(win["start"]) - timedelta(days=int(tr.get("setup_days", 0) or 0))
    end = to_date(win["end"]) + timedelta(days=int(tr.get("teardown_days", 0) or 0))
    return {"start": start.isoformat(), "end": end.isoformat()}


def _fiscal_years_for(win: dict, gov_request: float) -> dict[int, float]:
    """按自然年、以占用天数比例分摊财政申请额（假设 FISCAL_YEAR_SPLIT）。"""
    start, end = to_date(win["start"]), to_date(win["end"])
    if start.year == end.year:
        return {start.year: gov_request}
    total_days = (end - start).days + 1
    out: dict[int, float] = {}
    year_start = start
    while year_start <= end:
        seg_end = min(end, date(year_start.year, 12, 31))
        days = (seg_end - year_start).days + 1
        out[year_start.year] = gov_request * days / total_days
        year_start = date(year_start.year + 1, 1, 1)
    return out


def _src_ref(obj) -> str:
    sid = getattr(obj, "source_system", "") or ""
    ref = getattr(obj, "source_ref", "") or ""
    eid = getattr(obj, "event_id", "") or ""
    return f"{sid + ':' if sid else ''}{ref + ' ' if ref else ''}(事件 {eid})".strip()


def _clusters(applications: list[dict], assignments: dict[str, dict]) -> list[list[str]]:
    """按赛期是否重叠，把赛事划分为同日并发簇（错峰 => 多簇）。"""
    ordered = sorted(applications, key=lambda a: assignments[a["application_code"]]["window"]["start"])
    clusters: list[list[dict]] = []
    for app in ordered:
        win = assignments[app["application_code"]]["window"]
        placed = False
        for cl in clusters:
            if any(
                to_date(win["start"]) <= to_date(assignments[c["application_code"]]["window"]["end"])
                and to_date(assignments[c["application_code"]]["window"]["start"]) <= to_date(win["end"])
                for c in cl
            ):
                cl.append(app)
                placed = True
                break
        if not placed:
            clusters.append([app])
    return [[a["application_code"] for a in cl] for cl in clusters]


def evaluate(
    applications: list[dict],
    assignments: dict[str, dict],
    registry,
    plan_type: str,
    reevaluated_fields: list[str] | None = None,
    based_on_event_ids: list[str] | None = None,
) -> dict:
    """评估一个赛事组合方案。

    assignments: application_code -> {"window": {start,end}, "venue_override": str|None}
    """
    apps = {a["application_code"]: a for a in applications}
    scenario_window = {
        "start": min(v["window"]["start"] for v in assignments.values()),
        "end": max(v["window"]["end"] for v in assignments.values()),
    }
    conflicts: list[dict] = []
    assumptions_used: list[dict] = [
        {"key": k, "statement": v[0]} for k, v in ASSUMPTIONS.items()
    ]
    metrics: dict[str, dict] = {}
    conditions: list[str] = []
    blocker_count = 0

    def conflict(code, dimension, severity, message, cls, refs=None):
        conflicts.append(
            {
                "code": code,
                "dimension": dimension,
                "severity": severity,
                "message": message,
                "evidence_class": cls,
                "source_refs": refs or [],
            }
        )

    # ---- 1. 材料缺口（客观核对） ---------------------------------------
    for app in applications:
        for gap in material_gaps(app):
            conflict(
                f"MAT-{app['application_code']}-{gap['code']}",
                "MATERIAL",
                gap["severity"],
                f"[{app['event_name']}] 材料缺口：{gap['label']}——{gap['detail']}",
                "OBJECTIVE",
            )
            if gap["severity"] == "BLOCKER":
                blocker_count += 1
                conditions.append(f"补齐“{app['event_name']}”的{gap['label']}后复核")

    # ---- 2. 场馆（逐赛事占用核对 + 同簇撞用） --------------------------
    cluster_lists = _clusters(applications, assignments)
    for app in applications:
        code = app["application_code"]
        win = assignments[code]["window"]
        occ = occupation_window(app, win)
        venue_code = assignments[code].get("venue_override") or app["venue_requirement"]["primary_venue_code"]
        venue = registry.venue(venue_code)
        peak = int(app["expected_attendance"]["single_day_peak"])

        if venue is None:
            conflict(
                f"VEN-{code}-NA", "VENUE", "WARNING",
                f"[{app['event_name']}] 资源日历中无场馆 {venue_code} 的登记，无法核对容量与占用",
                "OBJECTIVE",
            )
            conditions.append(f"补录场馆 {venue_code} 的核定容量与占用日历")
            continue

        hits = registry.blocking_within("VENUE", venue_code, occ["start"], occ["end"])
        for b in hits:
            conflict(
                f"VEN-{code}-BOOKED", "VENUE", "BLOCKER",
                f"[{app['event_name']}] {venue.resource_name}({venue_code}) 在 {b.start}~{b.end} 已被占用：{b.reason}",
                "OBJECTIVE", [_src_ref(b)],
            )
            blocker_count += 1

        approved = (venue.capacity or {}).get("approved_capacity")
        if approved:
            ratio = venue.capacity.get("safe_load_ratio", ASSUMPTIONS["SAFE_LOAD_RATIO"][1])
            safe_cap = int(approved * ratio)
            metrics[f"venue_{venue_code}_safe_capacity"] = {
                "value": safe_cap, "unit": "人次/日", "evidence_class": "OBJECTIVE",
                "source_refs": [f"{venue.source_system}:{venue.source_ref}".strip(":")],
            }
            if peak > safe_cap:
                conflict(
                    f"VEN-{code}-CAP", "VENUE", "BLOCKER",
                    f"[{app['event_name']}] 峰值 {peak:,} 人超过 {venue.resource_name} 安全容量 {safe_cap:,} 人"
                    f"（核定 {approved:,}×承载率 {ratio:.0%}）",
                    "ASSUMPTION",
                )
                blocker_count += 1

    if plan_type == "CO_HOSTED":
        # 联办：同馆合并峰值受安全容量约束
        merged: dict[str, int] = {}
        for app in applications:
            vc = assignments[app["application_code"]].get("venue_override") or app["venue_requirement"]["primary_venue_code"]
            merged[vc] = merged.get(vc, 0) + int(app["expected_attendance"]["single_day_peak"])
        for venue_code, combined in merged.items():
            venue = registry.venue(venue_code)
            if not venue or not (venue.capacity or {}).get("approved_capacity"):
                continue
            safe_cap = int(venue.capacity["approved_capacity"] * venue.capacity.get("safe_load_ratio", ASSUMPTIONS["SAFE_LOAD_RATIO"][1]))
            if combined > safe_cap:
                conflict(
                    "VEN-COHOST-CAP", "VENUE", "BLOCKER",
                    f"联合承办下同馆合并峰值 {combined:,} 人超过安全容量 {safe_cap:,} 人，分时入场也无法消化",
                    "ASSUMPTION",
                )
                blocker_count += 1
            else:
                conflict(
                    "VEN-COHOST-SPLIT", "VENUE", "INFO",
                    f"联合承办依赖分时入场/退场（合并峰值 {combined:,} ≤ 安全容量 {safe_cap:,}），承办方须提交联合动线方案",
                    "ASSUMPTION",
                )
    else:
        # 非联办：同簇赛事不得使用同一场馆
        for cl in cluster_lists:
            if len(cl) < 2:
                continue
            usage: dict[str, list[str]] = {}
            for code in cl:
                vc = assignments[code].get("venue_override") or apps[code]["venue_requirement"]["primary_venue_code"]
                usage.setdefault(vc, []).append(apps[code]["event_name"])
            for venue_code, users in usage.items():
                if len(users) > 1:
                    conflict(
                        "VEN-SHARE", "VENUE", "BLOCKER",
                        f"场馆 {venue_code} 同一比赛日被 {len(users)} 项赛事同时申请：{'、'.join(users)}；须错峰、换馆或联合承办",
                        "OBJECTIVE",
                    )
                    blocker_count += 1

    # ---- 3. 警力（按并发簇核对，既有勤务按台账系数折减容量） -----------
    police_resources = registry.police_resources()
    police_cap_full = sum(float((r.capacity or {}).get("daily_officer_capacity", 0)) for r in police_resources)
    first_cap = police_resources[0].capacity if police_resources else {}
    base = float(first_cap.get("officers_per_event_base", ASSUMPTIONS["POLICE_BASE"][1]))
    per10k = float(first_cap.get("officers_per_10k_attendance", ASSUMPTIONS["POLICE_PER_10K"][1]))

    def police_demand(codes: list[str]) -> int:
        total = 0
        for code in codes:
            app = apps[code]
            peak = int(app["expected_attendance"]["single_day_peak"])
            factor = LEVEL_FACTOR.get(app["event_level"], 1.0)
            total += math.ceil((base + per10k * peak / 10_000) * factor)
        return total

    if police_cap_full > 0:
        worst_demand = 0
        for i, cl in enumerate(cluster_lists):
            cl_win = {
                "start": min(assignments[c]["window"]["start"] for c in cl),
                "end": max(assignments[c]["window"]["end"] for c in cl),
            }
            cap = police_cap_full
            for r in police_resources:
                hits = registry.blocking_within("POLICE", r.resource_code, cl_win["start"], cl_win["end"])
                reduction = float((r.capacity or {}).get("blocked_reduction_ratio", 0) or 0)
                for b in hits:
                    cap -= float((r.capacity or {}).get("daily_officer_capacity", 0)) * reduction
                    conflict(
                        f"POL-BUSY-{i}", "POLICE", "WARNING",
                        f"{cl_win['start']}~{cl_win['end']} 警力资源 {r.resource_name} 已有勤务：{b.reason}，可调度量按台账系数折减 {reduction:.0%}",
                        "OBJECTIVE", [_src_ref(b)],
                    )
            demand = police_demand(cl)
            worst_demand = max(worst_demand, demand)
            if demand > cap:
                conflict(
                    f"POL-CAP-{i}", "POLICE", "BLOCKER",
                    f"{cl_win['start']}~{cl_win['end']} 该日簇需警力约 {demand} 人，"
                    f"超过折减后可调度上限 {int(cap)} 人（基础 {base:.0f}+每万人 {per10k:.0f}，含级别系数）",
                    "ASSUMPTION",
                )
                blocker_count += 1
        metrics["police_peak_daily_demand"] = {"value": worst_demand, "unit": "人次/日", "evidence_class": "ASSUMPTION"}
        metrics["police_daily_capacity_full"] = {"value": int(police_cap_full), "unit": "人次/日", "evidence_class": "OBJECTIVE"}
    else:
        conflict("POL-NA", "POLICE", "WARNING", "资源日历未登记警力日调度容量，警力维度无法客观核对", "OBJECTIVE")
        conditions.append("请警务部门登记可调度警力与既有勤务")

    # ---- 4. 交通（按并发簇；施工/管制按台账折减通道容量） --------------
    traffic_resources = registry.traffic_resources()

    def traffic_capacity_for(win: dict):
        cap = 0.0
        blocked = []
        for tr in traffic_resources:
            part = float((tr.capacity or {}).get("daily_person_capacity", 0))
            hits = registry.blocking_within("TRAFFIC", tr.resource_code, win["start"], win["end"])
            if hits:
                reduction = float((tr.capacity or {}).get("blocked_reduction_ratio", 1.0))
                part *= (1 - reduction)
                blocked.append((tr, hits))
            cap += part
        return cap, blocked

    traffic_cap_full = sum(float((r.capacity or {}).get("daily_person_capacity", 0)) for r in traffic_resources)
    if traffic_cap_full > 0:
        worst_ratio = 0.0
        for i, cl in enumerate(cluster_lists):
            cl_win = {
                "start": min(assignments[c]["window"]["start"] for c in cl),
                "end": max(assignments[c]["window"]["end"] for c in cl),
            }
            peak_sum = sum(int(apps[c]["expected_attendance"]["single_day_peak"]) for c in cl)
            coincidence = ASSUMPTIONS["PEAK_COINCIDENCE"][1] if len(cl) > 1 else 1.0
            demand = peak_sum * coincidence
            cap, blocked = traffic_capacity_for(cl_win)
            for tr, hits in blocked:
                for b in hits:
                    conflict(
                        f"TRF-BLOCK-{i}", "TRAFFIC", "WARNING",
                        f"{cl_win['start']}~{cl_win['end']} 通道 {tr.resource_name} 受影响：{b.reason}，容量已按台账折减",
                        "OBJECTIVE", [_src_ref(b)],
                    )
            metrics[f"traffic_{i}_daily_demand"] = {"value": int(demand), "unit": "人次/日", "evidence_class": "ASSUMPTION"}
            if demand > cap:
                conflict(
                    f"TRF-CAP-{i}", "TRAFFIC", "BLOCKER",
                    f"{cl_win['start']}~{cl_win['end']} 散场峰值约 {int(demand):,} 人次"
                    f"（簇峰值 {peak_sum:,}×重合系数 {coincidence}），超过折减后通道容量 {int(cap):,} 人次",
                    "ASSUMPTION",
                )
                blocker_count += 1
            worst_ratio = max(worst_ratio, demand / cap if cap else 1.0)
        metrics["traffic_daily_capacity_full"] = {"value": int(traffic_cap_full), "unit": "人次/日", "evidence_class": "OBJECTIVE"}
        traffic_score = round(max(0.0, 100 - 100 * worst_ratio), 1)
    else:
        conflict("TRF-NA", "TRAFFIC", "WARNING", "资源日历未登记交通通道日容量，交通维度无法客观核对", "OBJECTIVE")
        conditions.append("请交通部门登记主要通道集散容量与施工/管制日历")
        traffic_score = None

    # ---- 5. 年度财政 ---------------------------------------------------
    requested_by_year: dict[int, float] = {}
    for app in applications:
        win = assignments[app["application_code"]]["window"]
        gov = float(app["funding_structure"]["government_request_cny"])
        for yr, amount in _fiscal_years_for(win, gov).items():
            requested_by_year[yr] = requested_by_year.get(yr, 0.0) + amount
    fiscal_overrun = False
    for yr, requested in sorted(requested_by_year.items()):
        summary = registry.budget_summary(yr)
        metrics[f"budget_{yr}_requested"] = {"value": round(requested), "unit": "元", "evidence_class": "OBJECTIVE"}
        metrics[f"budget_{yr}_available"] = {
            "value": round(summary["available_cny"]), "unit": "元", "evidence_class": "OBJECTIVE",
            "source_refs": [f"预算台账 年度限额与已承诺事项（{yr}）"],
        }
        if requested > summary["available_cny"]:
            fiscal_overrun = True
            refs = [f"预算台账:{c.source_ref} (事件 {c.event_id})" for c in summary["commitments"]]
            conflict(
                "BUD-CAP", "BUDGET", "BLOCKER",
                f"{yr} 年度本组合申请财政资金 {requested:,.0f} 元，超过年度可用余额 {summary['available_cny']:,.0f} 元"
                f"（限额 {summary['cap_cny']:,.0f}，已承诺 {summary['committed_cny']:,.0f}）",
                "OBJECTIVE", refs,
            )
            blocker_count += 1
    primary_fy = min(requested_by_year, default=to_date(scenario_window["start"]).year)

    # ---- 6. 历史履约（客观记录；是否限制承办由有权部门判断） -----------
    breach = False
    for app in applications:
        applicant_code = (app.get("applicant") or {}).get("credit_code") or app["application_code"]
        records = registry.history(applicant_code)
        if not records:
            conflict(
                f"HIS-{app['application_code']}-NONE", "HISTORY", "INFO",
                f"[{app['event_name']}] 未查到申请方 {applicant_code} 的历史履约记录",
                "OBJECTIVE",
            )
            continue
        latest = records[-1]
        label = {"GOOD": "履约良好", "ACCEPTABLE": "履约合格", "POOR": "履约不佳", "BREACH": "有违约记录"}[latest.performance]
        if latest.performance in ("POOR", "BREACH"):
            conflict(
                f"HIS-{app['application_code']}", "HISTORY", "WARNING",
                f"[{app['event_name']}] 申请方 {latest.year} 年《{latest.event_name}》{label}：{latest.note or '（无备注）'}。"
                "记录为客观事实，是否限制承办由主管部门审定，系统不代为结论",
                "OBJECTIVE", [f"履约台账 (事件 {latest.event_id})"],
            )
            conditions.append(f"复核“{app['event_name']}”申请方散场组织预案并征求公安交管意见")
            if latest.performance == "BREACH":
                breach = True

    # ---- 7. 四维参考评分（测算分，非专家评分） -------------------------
    total_persons = sum(int(a["expected_attendance"].get("total") or a["expected_attendance"]["single_day_peak"]) for a in applications)
    total_budget = sum(float(a["funding_structure"]["total_budget_cny"]) for a in applications)
    mass_fund = sum(float((a.get("legacy_plan") or {}).get("mass_sports_funding_cny", 0) or 0) for a in applications)
    mass_score = min(60.0, total_persons / 50_000 * 60) + min(40.0, (mass_fund / total_budget if total_budget else 0) / 0.10 * 40)

    fy_request = requested_by_year.get(primary_fy, 0.0)
    fy_available = registry.budget_summary(primary_fy)["available_cny"]
    if fy_available <= 0 or fiscal_overrun:
        fiscal_score = 0.0
    else:
        fiscal_score = max(0.0, 40 + 60 * (1 - fy_request / fy_available))
        if breach:
            fiscal_score -= 20

    revenue = sum(
        float((a.get("market_development") or {}).get("expected_direct_revenue_cny", 0) or 0)
        + float((a.get("market_development") or {}).get("expected_indirect_revenue_cny", 0) or 0)
        for a in applications
    )
    market_score = min(100.0, (revenue / total_budget if total_budget else 0) / 1.2 * 100)

    scores = {
        "mass_participation": round(mass_score, 1),
        "fiscal_safety": round(max(0.0, fiscal_score), 1),
        "traffic_smoothness": traffic_score,
        "market_return": round(market_score, 1),
    }

    # ---- 8. 裁定 -------------------------------------------------------
    if blocker_count > 0:
        verdict = "INFEASIBLE"
    elif conflicts or conditions:
        verdict = "CONDITIONAL"
    else:
        verdict = "FEASIBLE"

    return {
        "application_codes": [a["application_code"] for a in applications],
        "window": scenario_window,
        "fiscal_year": primary_fy,
        "plan_type": plan_type,
        "verdict": verdict,
        "metrics": metrics,
        "assumptions": assumptions_used,
        "conflicts": conflicts,
        "scores": scores,
        "conditions": sorted(set(conditions)),
        "reevaluated_fields": reevaluated_fields or [],
        "based_on_event_ids": based_on_event_ids or [],
    }
