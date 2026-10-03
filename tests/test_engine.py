import unittest

from src import demo_data
from src.domain import material_gaps
from tests._fixtures import build_service, TRIO, DUO


class EngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.svc = build_service()
        self.trio_views = self.svc.evaluate_combinations(TRIO)
        self.duo_views = self.svc.evaluate_combinations(DUO)

    def test_same_weekend_is_infeasible_with_objective_blockers(self) -> None:
        same = next(
            v for v in self.trio_views
            if v["payload"]["plan_type"] == "SAME_WEEKEND"
            and v["payload"]["window"]["start"] == "2026-11-14"
            and all(a.get("venue_override") is None for a in v["payload"]["assignments"].values())
        )
        self.assertEqual(same["payload"]["verdict"], "INFEASIBLE")
        dims = {c["dimension"] for c in same["payload"]["conflicts"] if c["severity"] == "BLOCKER"}
        # 撞馆（客观）、警力超容（假设口径下）、财政超年度额度（客观）
        self.assertIn("VENUE", dims)
        self.assertIn("POLICE", dims)
        self.assertIn("BUDGET", dims)

    def test_police_need_is_computed_per_concurrency_cluster(self) -> None:
        # 单赛事单独评估时警力需求应显著低于三赛同日
        solo = self.svc.evaluate_combinations(["APP-INTL-2026-03"])
        intl_solo = next(v for v in solo if v["payload"]["plan_type"] == "SAME_WEEKEND")
        demand_solo = intl_solo["payload"]["metrics"]["police_peak_daily_demand"]["value"]
        same = next(
            v for v in self.trio_views
            if v["payload"]["plan_type"] == "SAME_WEEKEND"
            and v["payload"]["window"]["start"] == "2026-11-14"
            and all(a.get("venue_override") is None for a in v["payload"]["assignments"].values())
        )
        demand_same = same["payload"]["metrics"]["police_peak_daily_demand"]["value"]
        self.assertLess(demand_solo, demand_same)

    def test_material_gap_blocks_until_corrected(self) -> None:
        gaps = material_gaps(demo_data.mass_event())
        blockers = {g["field"] for g in gaps if g["severity"] == "BLOCKER"}
        self.assertIn("safety_responsibility.security_plan_ref", blockers)
        self.assertIn("safety_responsibility.insurance_amount_cny", blockers)

    def test_cross_year_staggered_splits_fiscal_years_and_is_not_blocked_by_2026_cap(
        self,
    ) -> None:
        feasible_like = [
            v for v in self.trio_views
            if v["payload"]["plan_type"] == "STAGGERED"
            and v["payload"]["assignments"]["APP-INTL-2026-03"]["window"]["start"].startswith("2027-01")
        ]
        self.assertTrue(feasible_like)
        for v in feasible_like:
            bud = [c for c in v["payload"]["conflicts"]
                   if c["dimension"] == "BUDGET" and c["severity"] == "BLOCKER"]
            self.assertFalse(bud, "跨年错峰不应触发财政阻断")
            # 财政申请按自然年拆分，两个年度均出现客观指标
            self.assertIn("budget_2026_requested", v["payload"]["metrics"])
            self.assertIn("budget_2027_requested", v["payload"]["metrics"])

    def test_fiscal_blocker_is_objective_with_traceable_sources(self) -> None:
        same = next(
            v for v in self.trio_views
            if v["payload"]["plan_type"] == "SAME_WEEKEND"
            and v["payload"]["window"]["start"] == "2026-11-14"
            and all(a.get("venue_override") is None for a in v["payload"]["assignments"].values())
        )
        bud = next(c for c in same["payload"]["conflicts"] if c["dimension"] == "BUDGET" and c["severity"] == "BLOCKER")
        self.assertEqual(bud["evidence_class"], "OBJECTIVE")
        self.assertTrue(bud["source_refs"], "财政阻断必须能溯源到台账承诺事项")

    def test_cohost_capacity_check(self) -> None:
        cohost = next(v for v in self.trio_views if v["payload"]["plan_type"] == "CO_HOSTED")
        cap = [c for c in cohost["payload"]["conflicts"] if c["code"] == "VEN-COHOST-CAP"]
        self.assertTrue(cap)
        self.assertEqual(cap[0]["evidence_class"], "ASSUMPTION")

    def test_every_conclusion_has_three_way_classification_or_none(self) -> None:
        for v in self.trio_views:
            for c in v["payload"]["conflicts"]:
                self.assertIn(c["evidence_class"], ("OBJECTIVE", "ASSUMPTION", "EXPERT"))
            for a in v["payload"]["assumptions"]:
                self.assertTrue(a["statement"])

    def test_verdict_is_never_approval(self) -> None:
        for v in self.trio_views + self.duo_views:
            self.assertIn(v["payload"]["verdict"], ("FEASIBLE", "CONDITIONAL", "INFEASIBLE"))
