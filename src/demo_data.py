"""演示数据：职业联赛、群众赛、国际邀请赛同时选中 2026-11-14 周末。

外部资源一律以 CONSTRAINT_REGISTERED 事件喂送，带来源系统与文号，
体现“与真实资源日历及历史履约记录核对”。
"""
from __future__ import annotations

WEEKEND = {"start": "2026-11-14", "end": "2026-11-15"}


def pro_league() -> dict:
    return {
        "application_code": "APP-PRO-2026-07",
        "event_name": "2026 城市职业足球联赛主场战",
        "event_level": "PRO_LEAGUE",
        "applicant": {"name": "市足球俱乐部有限公司", "contact": "王领队 13800000001", "credit_code": "ORG-PRO"},
        "time_requirement": {
            "preferred_windows": [dict(WEEKEND)],
            "flexibility": "WEEKEND_FLEXIBLE",
            "flex_days": 7,
            "setup_days": 1,
            "teardown_days": 1,
        },
        "venue_requirement": {
            "primary_venue_code": "V-STADIUM",
            "fallback_venue_codes": ["V-GYMNASIUM"],
            "min_capacity": 40000,
            "venue_features": ["标准天然草坪", "夜场照明"],
        },
        "expected_attendance": {"single_day_peak": 42000, "total": 80000, "participants": 60, "spectator_ratio": 0.99},
        "funding_structure": {
            "total_budget_cny": 20_000_000,
            "applicant_self_raised_cny": 8_000_000,
            "sponsorship_cny": 4_000_000,
            "market_revenue_cny": 0,
            "government_request_cny": 8_000_000,
            "contingency_ratio": 0.08,
        },
        "safety_responsibility": {
            "responsible_party": "APPLICANT",
            "insurance_amount_cny": 50_000_000,
            "medical_stations": 6,
            "security_plan_ref": "公保审[2026]0311号",
        },
        "market_development": {
            "broadcast_plan": "卫视+网络平台全国直播，预计收视 1200 万人次",
            "sponsorship_tiers": ["冠名", "场地广告"],
            "expected_direct_revenue_cny": 9_000_000,
            "expected_indirect_revenue_cny": 6_000_000,
        },
        "legacy_plan": {
            "facility_upgrade": "草坪补光与替补席改造赛后留用",
            "mass_sports_funding_cny": 1_000_000,
            "youth_programs": "赛后开展校园足球周末课 20 场",
            "post_event_utilization": "改造设施纳入市体校日常训练",
        },
    }


def mass_event() -> dict:
    return {
        "application_code": "APP-MASS-2026-11",
        "event_name": "市民健步走暨社区健身嘉年华",
        "event_level": "MASS_PARTICIPATION",
        "applicant": {"name": "市社会体育指导员协会", "contact": "李秘书 13800000002", "credit_code": "ORG-MASS"},
        "time_requirement": {
            "preferred_windows": [dict(WEEKEND)],
            "flexibility": "WEEKEND_FLEXIBLE",
            "flex_days": 14,
            "setup_days": 1,
            "teardown_days": 1,
        },
        "venue_requirement": {
            "primary_venue_code": "V-MASS-PLAZA",
            "fallback_venue_codes": [],
            "min_capacity": 20000,
            "venue_features": ["开放式广场", "应急通道≥4条"],
        },
        "expected_attendance": {"single_day_peak": 25000, "total": 60000, "participants": 25000},
        "funding_structure": {
            "total_budget_cny": 5_000_000,
            "applicant_self_raised_cny": 1_000_000,
            "sponsorship_cny": 1_000_000,
            "market_revenue_cny": 1_000_000,
            "government_request_cny": 2_000_000,
            "contingency_ratio": 0.06,
        },
        "safety_responsibility": {
            # 故意缺少 insurance_amount_cny 与 security_plan_ref：材料缺口剧情
            "responsible_party": "APPLICANT",
            "medical_stations": 3,
        },
        "market_development": {
            "broadcast_plan": "本地融媒体图文直播",
            "sponsorship_tiers": ["社区共建单位"],
            "expected_direct_revenue_cny": 800_000,
            "expected_indirect_revenue_cny": 1_500_000,
        },
        "legacy_plan": {
            "facility_upgrade": "广场标识与饮水点改造留用",
            "mass_sports_funding_cny": 800_000,
            "youth_programs": "社区健身指导站全年开放",
            "post_event_utilization": "器材配发 30 个社区晨晚练点",
        },
    }


def international() -> dict:
    return {
        "application_code": "APP-INTL-2026-03",
        "event_name": "2026 国际田径邀请赛",
        "event_level": "INTERNATIONAL_INVITATIONAL",
        "applicant": {"name": "市田径运动协会", "contact": "张专员 13800000003", "credit_code": "ORG-INTL"},
        "time_requirement": {
            "preferred_windows": [dict(WEEKEND)],
            "flexibility": "WINDOW_FLEXIBLE",
            "flex_days": 60,
            "setup_days": 2,
            "teardown_days": 2,
        },
        "venue_requirement": {
            "primary_venue_code": "V-STADIUM",
            "fallback_venue_codes": ["V-GYMNASIUM"],
            "min_capacity": 15000,
            "venue_features": ["国际田联认证跑道", "兴奋剂检测室"],
        },
        "expected_attendance": {"single_day_peak": 18000, "total": 36000, "participants": 420, "spectator_ratio": 0.9},
        "funding_structure": {
            "total_budget_cny": 40_000_000,
            "applicant_self_raised_cny": 5_000_000,
            "sponsorship_cny": 8_000_000,
            "market_revenue_cny": 2_000_000,
            "government_request_cny": 25_000_000,
            "contingency_ratio": 0.10,
        },
        "safety_responsibility": {
            "responsible_party": "APPLICANT",
            "insurance_amount_cny": 100_000_000,
            "medical_stations": 8,
            "security_plan_ref": "公保审[2026]0307号",
        },
        "market_development": {
            "broadcast_plan": "国际信号制作+境外平台转播，覆盖 30 国",
            "sponsorship_tiers": ["官方合作伙伴", "官方供应商"],
            "expected_direct_revenue_cny": 22_000_000,
            "expected_indirect_revenue_cny": 30_000_000,
        },
        "legacy_plan": {
            "facility_upgrade": "跑道国际认证翻新、检测室留用",
            "mass_sports_funding_cny": 3_000_000,
            "youth_programs": "田径进校园 40 所学校",
            "post_event_utilization": "认证场地承接国家队冬训",
        },
    }


def external_constraint_events(next_id) -> list[dict]:
    """真实资源日历事件。event_id 沿用来源系统稳定编号。"""
    events = []

    def ev(event_id, resource_type, resource_code, name, payload, source_system, source_ref, occurred):
        full = {
            "event_id": event_id,
            "event_type": "CONSTRAINT_REGISTERED",
            "aggregate_type": "resource_constraint",
            "aggregate_id": f"{resource_type.lower()}-{resource_code}",
            "occurred_at": occurred,
            "version": 1,
            "summary": f"{source_system} 同步：{name}",
            "source_system": source_system,
            "source_ref": source_ref,
            "actor": {"role": "RESOURCE_SYSTEM"},
            "payload": {"resource_type": resource_type, "resource_code": resource_code,
                        "resource_name": name, **payload},
        }
        events.append(full)

    ev("venue-calendar:V-STADIUM:2026-09-01", "VENUE", "V-STADIUM", "市体育中心体育场",
       {"capacity": {"approved_capacity": 60000, "safe_load_ratio": 0.9}},
       "venue-calendar", "场登[2026]主01", "2026-09-01T09:00:00+08:00")
    ev("venue-calendar:V-GYMNASIUM:2026-09-01", "VENUE", "V-GYMNASIUM", "市体育馆",
       {"capacity": {"approved_capacity": 12000, "safe_load_ratio": 0.9},
        "blocked_windows": [{"start": "2026-11-14", "end": "2026-11-15",
                             "reason": "场馆消防设施年度检修，停场两天"}]},
       "venue-calendar", "场登[2026]馆07", "2026-09-01T09:05:00+08:00")
    ev("venue-calendar:V-MASS-PLAZA:2026-09-01", "VENUE", "V-MASS-PLAZA", "全民健身广场",
       {"capacity": {"approved_capacity": 30000, "safe_load_ratio": 0.9}},
       "venue-calendar", "场登[2026]广02", "2026-09-01T09:10:00+08:00")

    ev("police-duty:P-CITY:2026-09-05", "POLICE", "P-CITY", "市公安局大型活动安保警力池",
       {"capacity": {"daily_officer_capacity": 380, "officers_per_event_base": 80,
                     "officers_per_10k_attendance": 12},
        "blocked_windows": [{"start": "2026-11-14", "end": "2026-11-15",
                             "reason": "同一周末已预排国际会展中心博览会安保勤务"}]},
       "police-duty", "警勤[2026]秋字18号", "2026-09-05T14:00:00+08:00")

    ev("traffic-center:T-METRO:2026-09-06", "TRAFFIC", "T-METRO", "地铁线网集散能力",
       {"capacity": {"daily_person_capacity": 350000}},
       "traffic-center", "交规[2026]轨04", "2026-09-06T10:00:00+08:00")
    ev("traffic-center:T-ROAD:2026-09-06", "TRAFFIC", "T-ROAD", "奥体片区道路集散能力",
       {"capacity": {"daily_person_capacity": 80000, "blocked_reduction_ratio": 0.25},
        "blocked_windows": [{"start": "2026-11-14", "end": "2026-11-15",
                             "reason": "奥体主干道接驳段半幅施工，道路集散能力下降约 25%"}]},
       "traffic-center", "交施[2026]112号", "2026-09-06T10:05:00+08:00")

    ev("budget-ledger:B-GEN:2026-09-10", "BUDGET", "B-GEN", "体育事业年度财政额度",
       {"fiscal_year": 2026,
        "capacity": {"annual_cap_cny": {
            "2026": 80_000_000,
            "2027": 90_000_000,
        },
            "committed": [
                {"fiscal_year": 2026, "amount_cny": 33_000_000, "reason": "已公示的下半年其他赛事承诺",
                 "source_ref": "财教[2026]已列01"},
                {"fiscal_year": 2026, "amount_cny": 15_000_000, "reason": "青少年体育与场馆运维专项",
                 "source_ref": "财教[2026]已列02"},
                {"fiscal_year": 2027, "amount_cny": 10_000_000, "reason": "2027 年度已预列事项",
                 "source_ref": "财教[2027]预列01"},
            ]}},
       "budget-ledger", "财额度[2026]体3号", "2026-09-10T16:00:00+08:00")

    ev("performance-register:H-CITY:2026-09-12", "HISTORY", "H-CITY", "全市大型活动履约台账",
       {"records": [
           {"applicant_code": "ORG-PRO", "year": 2025, "event_name": "职业联赛主场赛事",
            "performance": "GOOD", "note": "安保、结算均按时完成"},
           {"applicant_code": "ORG-MASS", "year": 2025, "event_name": "市民健步走",
            "performance": "POOR", "note": "散场组织超出预案约 2 小时，周边道路拥堵投诉集中"},
           {"applicant_code": "ORG-INTL", "year": 2024, "event_name": "国际田径公开赛",
            "performance": "GOOD", "note": "国际技术代表验收通过，赛后审计无问题"},
       ]},
       "performance-register", "体履[2025]年鉴", "2026-09-12T11:00:00+08:00")
    return events
