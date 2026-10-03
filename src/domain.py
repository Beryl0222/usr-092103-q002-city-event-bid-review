"""领域模型：申报材料视图、材料清单核对与真实资源日历。

资源状态只由 CONSTRAINT_REGISTERED 事件物化而来（事件溯源），
每条占用/限额都保留来源系统、文号与事件 ID，供约束溯源。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# 申报八要素 -> 中文标签（材料缺口按此分组告知申请方）
MATERIAL_SECTIONS = {
    "event_level": "赛事级别",
    "time_requirement": "时间弹性",
    "venue_requirement": "场馆需求",
    "expected_attendance": "预期人流",
    "funding_structure": "资金结构",
    "safety_responsibility": "安全责任",
    "market_development": "市场开发",
    "legacy_plan": "赛事遗产计划",
}

EVENT_LEVEL_LABELS = {
    "PRO_LEAGUE": "职业联赛",
    "MASS_PARTICIPATION": "群众赛事",
    "INTERNATIONAL_INVITATIONAL": "国际邀请赛",
    "OTHER": "其他赛事",
}

FLEXIBILITY_LABELS = {
    "FIXED": "时间固定",
    "WEEKEND_FLEXIBLE": "同档周末可调",
    "WINDOW_FLEXIBLE": "时间窗内可调",
}

PERFORMANCE_LABELS = {
    "GOOD": "履约良好",
    "ACCEPTABLE": "履约合格",
    "POOR": "履约不佳",
    "BREACH": "有违约记录",
}


def to_date(value: str) -> date:
    return date.fromisoformat(value)


def windows_overlap(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    return to_date(a_start) <= to_date(b_end) and to_date(b_start) <= to_date(a_end)


@dataclass
class Blocking:
    """资源日历上的一段占用/封禁。"""

    start: str
    end: str
    reason: str
    source_ref: str
    event_id: str
    source_system: str = ""


@dataclass
class HistoryRecord:
    applicant_code: str
    year: int
    event_name: str
    performance: str
    note: str
    source_ref: str
    event_id: str


@dataclass
class BudgetCommitment:
    fiscal_year: int
    amount_cny: float
    reason: str
    source_ref: str
    event_id: str


@dataclass
class Resource:
    resource_type: str
    resource_code: str
    resource_name: str = ""
    capacity: dict = field(default_factory=dict)
    blocked: list[Blocking] = field(default_factory=list)
    annual_cap: dict[int, float] = field(default_factory=dict)
    commitments: list[BudgetCommitment] = field(default_factory=list)
    records: list[HistoryRecord] = field(default_factory=list)
    source_system: str = ""
    source_ref: str = ""


class ResourceRegistry:
    """由 CONSTRAINT_REGISTERED 事件物化的真实资源日历与台账。"""

    def __init__(self) -> None:
        self._resources: dict[tuple[str, str], Resource] = {}

    def apply(self, event: dict) -> None:
        p = event["payload"]
        key = (p["resource_type"], p["resource_code"])
        res = self._resources.setdefault(
            key,
            Resource(
                resource_type=p["resource_type"],
                resource_code=p["resource_code"],
                resource_name=p.get("resource_name", ""),
            ),
        )
        res.source_system = event.get("source_system", "")
        res.source_ref = event.get("source_ref", "")
        if isinstance(p.get("capacity"), dict):
            if p["resource_type"] == "BUDGET":
                cap = p["capacity"]
                if "annual_cap_cny" in cap:
                    rows = cap["annual_cap_cny"]
                else:
                    rows = {p.get("fiscal_year"): cap.get("cap_cny")}
                for year, amount in rows.items():
                    if year is not None and amount is not None:
                        res.annual_cap[int(year)] = float(amount)
                for c in cap.get("committed", []):
                    res.commitments.append(
                        BudgetCommitment(
                            fiscal_year=int(c["fiscal_year"]),
                            amount_cny=float(c["amount_cny"]),
                            reason=c.get("reason", ""),
                            source_ref=c.get("source_ref", event.get("source_ref", "")),
                            event_id=event["event_id"],
                        )
                    )
            else:
                res.capacity.update(p["capacity"])
        for win in p.get("blocked_windows", []):
            res.blocked.append(
                Blocking(
                    start=win["start"],
                    end=win["end"],
                    reason=win.get("reason") or p.get("blocked_reason", "已被占用"),
                    source_ref=event.get("source_ref", ""),
                    event_id=event["event_id"],
                    source_system=event.get("source_system", ""),
                )
            )
        for rec in p.get("records", []):
            res.records.append(
                HistoryRecord(
                    applicant_code=rec["applicant_code"],
                    year=int(rec["year"]),
                    event_name=rec.get("event_name", ""),
                    performance=rec["performance"],
                    note=rec.get("note", ""),
                    source_ref=event.get("source_ref", ""),
                    event_id=event["event_id"],
                )
            )

    def get(self, resource_type: str, code: str) -> Resource | None:
        return self._resources.get((resource_type, code))

    def all(self, resource_type: str | None = None) -> list[Resource]:
        return [
            r for r in self._resources.values() if resource_type is None or r.resource_type == resource_type
        ]

    def venue(self, code: str) -> Resource | None:
        return self.get("VENUE", code)

    def blocking_within(self, resource_type: str, code: str, start: str, end: str) -> list[Blocking]:
        res = self.get(resource_type, code)
        if res is None:
            return []
        return [b for b in res.blocked if windows_overlap(b.start, b.end, start, end)]

    def police_resources(self) -> list[Resource]:
        return self.all("POLICE")

    def traffic_resources(self) -> list[Resource]:
        return self.all("TRAFFIC")

    def budget_summary(self, fiscal_year: int) -> dict:
        cap = 0.0
        committed = 0.0
        detail: list[BudgetCommitment] = []
        for res in self.all("BUDGET"):
            cap += res.annual_cap.get(fiscal_year, 0.0)
            for c in res.commitments:
                if c.fiscal_year == fiscal_year:
                    committed += c.amount_cny
                    detail.append(c)
        return {
            "fiscal_year": fiscal_year,
            "cap_cny": cap,
            "committed_cny": committed,
            "available_cny": cap - committed,
            "commitments": detail,
        }

    def history(self, applicant_code: str) -> list[HistoryRecord]:
        out: list[HistoryRecord] = []
        for res in self.all("HISTORY"):
            out.extend(r for r in res.records if r.applicant_code == applicant_code)
        return sorted(out, key=lambda r: r.year)


# ---------------------------------------------------------------------------
# 材料缺口核对：申请方据此明确知道缺什么、约束来自哪里
# ---------------------------------------------------------------------------

def material_gaps(app: dict) -> list[dict]:
    """对申报视图做完整性核对，返回材料缺口列表。

    每条缺口都是客观核对结果（evidence_class=OBJECTIVE）：
    要么材料里没有，要么材料内部数字对不上；不掺入测算假设或专家判断。
    """
    gaps: list[dict] = []

    def add(field_path: str, label: str, detail: str, severity: str) -> None:
        gaps.append(
            {
                "code": f"MAT-{len(gaps) + 1:03d}",
                "field": field_path,
                "section": next(
                    (v for k, v in MATERIAL_SECTIONS.items() if field_path.startswith(k)),
                    "主体信息",
                ),
                "label": label,
                "detail": detail,
                "severity": severity,  # BLOCKER / WARNING / INFO
                "evidence_class": "OBJECTIVE",
            }
        )

    applicant = app.get("applicant") or {}
    if not applicant.get("credit_code"):
        add("applicant.credit_code", "申请方统一社会信用代码", "未填写主体信用代码", "WARNING")
    if not applicant.get("contact"):
        add("applicant.contact", "联系方式", "未填写联系人或联系方式", "INFO")

    venue = app.get("venue_requirement", {})
    if not venue.get("min_capacity"):
        add("venue_requirement.min_capacity", "最低座席/容量要求", "未声明最低容量，无法核对场馆是否够用", "WARNING")
    if not venue.get("fallback_venue_codes"):
        add(
            "venue_requirement.fallback_venue_codes",
            "备选场馆",
            "未提供备选场馆；主馆冲突时只能延期或放弃同周末",
            "INFO",
        )

    att = app.get("expected_attendance", {})
    if not att.get("total"):
        add("expected_attendance.total", "预计总人流", "仅有峰值、未填报总人流，交通与垃圾环卫测算口径不全", "WARNING")

    funding = app.get("funding_structure", {})
    total = float(funding.get("total_budget_cny", 0) or 0)
    gov = float(funding.get("government_request_cny", 0) or 0)
    own = float(funding.get("applicant_self_raised_cny", 0) or 0)
    sponsor = float(funding.get("sponsorship_cny", 0) or 0)
    market = float(funding.get("market_revenue_cny", 0) or 0)
    sourced = own + sponsor + market + gov
    if total > 0 and sourced + 0.01 < total:
        add(
            "funding_structure.sources",
            "资金来源合计",
            f"资金来源合计 {sourced:,.0f} 元低于总预算 {total:,.0f} 元，缺口 {total - sourced:,.0f} 元未落实",
            "BLOCKER",
        )
    if gov > total:
        add(
            "funding_structure.government_request_cny",
            "财政申请额",
            "申请财政资金高于总预算，口径需更正",
            "BLOCKER",
        )
    contingency = funding.get("contingency_ratio")
    if contingency is None:
        add("funding_structure.contingency_ratio", "备用金比例", "未声明备用金比例", "INFO")
    elif float(contingency) < 0.05:
        add("funding_structure.contingency_ratio", "备用金比例", f"备用金比例 {float(contingency):.0%} 低于 5% 经验下限", "WARNING")

    safety = app.get("safety_responsibility", {})
    if not safety.get("security_plan_ref"):
        add("safety_responsibility.security_plan_ref", "安保方案文号", "未提交安保方案及编号，公安核验无法进行", "BLOCKER")
    if not safety.get("insurance_amount_cny"):
        add("safety_responsibility.insurance_amount_cny", "责任险保额", "未填写大型活动责任险保额", "BLOCKER")
    if not safety.get("medical_stations"):
        add("safety_responsibility.medical_stations", "医疗点数量", "未设置医疗点数量", "WARNING")

    md = app.get("market_development", {})
    if not md.get("broadcast_plan"):
        add("market_development.broadcast_plan", "转播/传播方案", "未提交转播或传播方案，市场回报缺测算依据", "WARNING")
    if not md.get("expected_direct_revenue_cny"):
        add("market_development.expected_direct_revenue_cny", "直接收入预测", "未预测门票/赞助等直接收入", "INFO")

    legacy = app.get("legacy_plan", {})
    if not legacy.get("facility_upgrade"):
        add("legacy_plan.facility_upgrade", "场馆设施升级", "未说明设施升级内容", "INFO")
    if not legacy.get("mass_sports_funding_cny"):
        add("legacy_plan.mass_sports_funding_cny", "群众体育投入", "未列明赛后群众体育投入，群众普及效益难量化", "WARNING")
    if not legacy.get("youth_programs"):
        add("legacy_plan.youth_programs", "青少年计划", "未说明青少年/社区延续计划", "INFO")

    tr = app.get("time_requirement", {})
    if tr.get("flexibility") == "FIXED" and len(tr.get("preferred_windows", [])) == 1:
        add(
            "time_requirement.flexibility",
            "时间弹性",
            "仅申报唯一周末且不可调整；一旦资源冲突无缓冲，建议补充可接受的备选档",
            "INFO",
        )
    return gaps
