"""测试夹具：装载演示数据的联审服务。"""
from __future__ import annotations

from src import demo_data
from src.service import ReviewService

TRIO = ["APP-PRO-2026-07", "APP-MASS-2026-11", "APP-INTL-2026-03"]
DUO = ["APP-PRO-2026-07", "APP-INTL-2026-03"]


def build_service() -> ReviewService:
    svc = ReviewService()
    for ev in demo_data.external_constraint_events(None):
        svc.ingest_external(ev)
    for payload in (demo_data.pro_league(), demo_data.mass_event(), demo_data.international()):
        svc.submit_application(payload, actor_name=payload["applicant"]["name"])
    return svc
