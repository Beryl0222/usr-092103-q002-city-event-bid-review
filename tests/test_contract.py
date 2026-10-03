import json
import unittest
from pathlib import Path

from src.contracts import validate_event
from src.validator import validate_event as legacy_validate_event

ROOT = Path(__file__).parents[1]


class ContractTest(unittest.TestCase):
    def test_sample_matches_envelope(self) -> None:
        sample = json.loads((ROOT / "data" / "sample.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_event(sample), [])

    def test_legacy_validator_entry_still_works(self) -> None:
        sample = json.loads((ROOT / "data" / "sample.json").read_text(encoding="utf-8"))
        self.assertEqual(legacy_validate_event(sample), [])

    def test_schema_file_is_valid_json_and_keeps_stable_identifiers(self) -> None:
        schema = json.loads((ROOT / "contracts" / "domain.schema.json").read_text(encoding="utf-8"))
        event_enum = schema["properties"]["event_type"]["enum"]
        for stable in ("APPLICATION_RECEIVED", "CONSTRAINT_REGISTERED", "SCENARIO_EVALUATED",
                       "OPINION_RECORDED", "DECISION_PUBLISHED"):
            self.assertIn(stable, event_enum, "既有稳定事件标识不得消失")
        agg_enum = schema["properties"]["aggregate_type"]["enum"]
        for stable in ("hosting_application", "resource_constraint", "review_scenario", "decision_release"):
            self.assertIn(stable, agg_enum)

    def test_event_aggregate_must_match(self) -> None:
        errors = validate_event({
            "event_id": "e1", "event_type": "DECISION_PUBLISHED",
            "aggregate_type": "hosting_application", "aggregate_id": "x",
            "occurred_at": "2026-10-03T10:00:00+08:00", "version": 1, "summary": "s",
        })
        self.assertTrue(any("aggregate_type" in e for e in errors))

    def test_amendment_requires_amendment_block(self) -> None:
        errors = validate_event({
            "event_id": "e2", "event_type": "APPLICATION_AMENDED",
            "aggregate_type": "hosting_application", "aggregate_id": "a1",
            "occurred_at": "2026-10-03T10:00:00+08:00", "version": 2, "summary": "s",
            "payload": {"application_code": "a1", "event_name": "n", "event_level": "OTHER",
                         "time_requirement": {"preferred_windows": [{"start": "2026-11-14", "end": "2026-11-15"}],
                                              "flexibility": "FIXED"},
                         "venue_requirement": {"primary_venue_code": "V1"},
                         "expected_attendance": {"single_day_peak": 100},
                         "funding_structure": {"total_budget_cny": 1, "government_request_cny": 1},
                         "safety_responsibility": {"responsible_party": "APPLICANT"},
                         "market_development": {}, "legacy_plan": {"post_event_utilization": "x"}},
        })
        self.assertTrue(any("amendment" in e for e in errors))

    def test_constraint_external_identifier_accepted(self) -> None:
        errors = validate_event({
            "event_id": "venue-calendar:V1:2026-09-01",
            "event_type": "CONSTRAINT_REGISTERED",
            "aggregate_type": "resource_constraint", "aggregate_id": "venue-v1",
            "occurred_at": "2026-09-01T09:00:00+08:00", "version": 1, "summary": "s",
            "source_system": "venue-calendar", "source_ref": "场登01",
            "payload": {"resource_type": "VENUE", "resource_code": "V1"},
        })
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
