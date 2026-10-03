import tempfile
import unittest
from pathlib import Path

from src.service import ReviewService, ServiceError
from tests._fixtures import build_service, TRIO, DUO


class ServiceFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.svc = build_service()
        self.trio = self.svc.evaluate_combinations(TRIO)
        self.duo = self.svc.evaluate_combinations(DUO)

    def _trio_jan(self):
        trio_set = set(TRIO)
        return next(
            s for s in self.svc.list_scenarios()
            if set(self.svc.scenario_apps[s["scenario_code"]]) == trio_set
            and s["plan_type"] == "STAGGERED"
            and self.svc.get_scenario(s["scenario_code"])["payload"]
                ["assignments"]["APP-INTL-2026-03"]["window"]["start"].startswith("2027-01")
        )

    def test_amendment_only_reevaluates_affected_combinations(self) -> None:
        duo_versions = {c: self.svc.get_scenario(c)["version"] for c in
                        {s["scenario_code"] for s in self.svc.list_scenarios()
                         if set(self.svc.scenario_apps[s["scenario_code"]]) == set(DUO)}}
        self.svc.amend_application(
            "APP-MASS-2026-11", "MATERIAL_CORRECTION",
            {"safety_responsibility": {"insurance_amount_cny": 20_000_000,
                                       "security_plan_ref": "公保审[2026]0322号"}},
            ["safety_responsibility.insurance_amount_cny",
             "safety_responsibility.security_plan_ref"],
            reason="补材料",
        )
        for code, version in duo_versions.items():
            self.assertEqual(
                self.svc.get_scenario(code)["version"], version,
                f"不含群众赛的方案 {code} 不应被重算",
            )

    def test_no_new_version_when_fingerprint_unchanged(self) -> None:
        before = {s["scenario_code"]: s["version"] for s in self.svc.list_scenarios()}
        self.svc.ingest_external({
            "event_id": "performance-register:H-CITY:unrelated",
            "event_type": "CONSTRAINT_REGISTERED",
            "aggregate_type": "resource_constraint",
            "aggregate_id": "history-h-city",
            "occurred_at": "2026-10-01T09:00:00+08:00",
            "version": 1,
            "summary": "无关主体履约补录",
            "source_system": "performance-register",
            "source_ref": "补1",
            "payload": {"resource_type": "HISTORY", "resource_code": "H-CITY",
                        "records": [{"applicant_code": "ORG-NOBODY", "year": 2025,
                                     "event_name": "无关", "performance": "GOOD", "note": ""}]},
        })
        after = {s["scenario_code"]: s["version"] for s in self.svc.list_scenarios()}
        self.assertEqual(before, after)

    def test_external_event_id_is_idempotent(self) -> None:
        ev = {
            "event_id": "venue-calendar:V-STADIUM:2026-09-01",
            "event_type": "CONSTRAINT_REGISTERED",
            "aggregate_type": "resource_constraint",
            "aggregate_id": "venue-v-stadium",
            "occurred_at": "2026-09-01T09:00:00+08:00",
            "version": 1, "summary": "重复喂送",
            "payload": {"resource_type": "VENUE", "resource_code": "V-STADIUM"},
        }
        with self.assertRaises(ServiceError):
            self.svc.ingest_external(ev)

    def test_material_correction_upgrades_jan_scenario_from_infeasible(self) -> None:
        jan = self._trio_jan()
        self.assertEqual(jan["verdict"], "INFEASIBLE")  # 群众赛安保材料阻断
        self.svc.amend_application(
            "APP-MASS-2026-11", "MATERIAL_CORRECTION",
            {"safety_responsibility": {"insurance_amount_cny": 20_000_000,
                                       "security_plan_ref": "公保审[2026]0322号",
                                       "medical_stations": 4}},
            ["safety_responsibility.insurance_amount_cny",
             "safety_responsibility.security_plan_ref",
             "safety_responsibility.medical_stations"],
            reason="补齐",
        )
        refreshed = self.svc.get_scenario(jan["scenario_code"])
        self.assertIn(refreshed["payload"]["verdict"], ("FEASIBLE", "CONDITIONAL"))
        self.assertGreaterEqual(refreshed["version"], 2)

    def test_system_cannot_publish_decision(self) -> None:
        self.svc.amend_application(
            "APP-MASS-2026-11", "MATERIAL_CORRECTION",
            {"safety_responsibility": {"insurance_amount_cny": 20_000_000,
                                       "security_plan_ref": "公保审[2026]0322号",
                                       "medical_stations": 4}},
            ["safety_responsibility.insurance_amount_cny",
             "safety_responsibility.security_plan_ref",
             "safety_responsibility.medical_stations"],
        )
        jan = self._trio_jan()
        with self.assertRaises(ServiceError):
            self.svc.publish_decision({"role": "SYSTEM", "name": "引擎"}, jan["scenario_code"],
                                      "APPROVED", "AUTO-1")
        with self.assertRaises(ServiceError):
            self.svc.publish_decision({"role": "EXPERT", "name": "某专家"}, jan["scenario_code"],
                                      "APPROVED", "EXP-1")

    def test_published_version_is_frozen_and_viewable(self) -> None:
        self.svc.amend_application(
            "APP-MASS-2026-11", "MATERIAL_CORRECTION",
            {"safety_responsibility": {"insurance_amount_cny": 20_000_000,
                                       "security_plan_ref": "公保审[2026]0322号",
                                       "medical_stations": 4}},
            ["safety_responsibility.insurance_amount_cny",
             "safety_responsibility.security_plan_ref",
             "safety_responsibility.medical_stations"],
        )
        jan = self._trio_jan()
        code, locked_version = jan["scenario_code"], jan["version"]
        decision = self.svc.publish_decision(
            {"role": "COMPETENT_AUTHORITY", "name": "市体育局"},
            code, "APPROVED", "体赛批[2026]47号",
            rationale="联审会决定", conditions=["赛前复核"],
        )
        self.assertEqual(decision["payload"]["scenario_version"], locked_version)

        # 公示后外部资源更新不得覆盖封存版本
        self.svc.ingest_external({
            "event_id": "police-duty:P-CITY:2026-10-20",
            "event_type": "CONSTRAINT_REGISTERED",
            "aggregate_type": "resource_constraint",
            "aggregate_id": "police-p-city",
            "occurred_at": "2026-10-20T09:00:00+08:00",
            "version": 1,
            "summary": "警力容量调整",
            "source_system": "police-duty",
            "source_ref": "警勤调[2026]01",
            "payload": {"resource_type": "POLICE", "resource_code": "P-CITY",
                        "capacity": {"daily_officer_capacity": 300}},
        })
        frozen = self.svc.get_scenario(code, locked_version)
        self.assertEqual(frozen["published"]["decision_ref"], "体赛批[2026]47号")
        self.assertEqual(frozen["published"]["decision"], "APPROVED")
        history = self.svc.scenario_history(code)
        published_versions = [h["version"] for h in history if h["published"]]
        self.assertEqual(published_versions, [locked_version])

    def test_event_replay_rebuilds_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            self.svc.save_events(str(path))
            rebuilt = ReviewService.replay(str(path))
            self.assertEqual(
                sorted(rebuilt.scenario_versions.keys()),
                sorted(self.svc.scenario_versions.keys()),
            )
            self.assertEqual(len(rebuilt.decisions), len(self.svc.decisions))


if __name__ == "__main__":
    unittest.main()
