import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from src import api, demo_data


def _request(method: str, path: str, body: dict | None = None, port: int = 8099):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        api.SERVICE = __import__("src.service", fromlist=["ReviewService"]).ReviewService()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 8099), api.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()

    def setUp(self) -> None:
        # 每个用例重建干净实例
        from src.service import ReviewService
        api.SERVICE = ReviewService()
        for ev in demo_data.external_constraint_events(None):
            status, out = _request("POST", "/external-events", ev)
            self.assertEqual(status, 201, out)

    def test_full_review_flow_over_http(self) -> None:
        for payload in (demo_data.pro_league(), demo_data.mass_event(), demo_data.international()):
            status, out = _request("POST", "/applications", payload)
            self.assertEqual(status, 201, out)

        status, out = _request("POST", "/evaluations",
                               {"application_codes": ["APP-PRO-2026-07", "APP-MASS-2026-11", "APP-INTL-2026-03"]})
        self.assertEqual(status, 201)
        self.assertTrue(out)
        same = next(s for s in out if s["verdict"] == "INFEASIBLE")
        self.assertTrue(same["scenario_code"])

        # 材料缺口
        status, gap = _request("GET", "/applications/APP-MASS-2026-11")
        self.assertEqual(status, 200)
        self.assertTrue(any(g["field"] == "safety_responsibility.security_plan_ref" for g in gap["gaps"]))
        self.assertTrue(gap["constraint_sources"], "约束来源须带来源系统与事件ID")

    def test_system_approval_rejected_over_http(self) -> None:
        app = demo_data.pro_league()
        _request("POST", "/applications", app)
        status, out = _request("POST", "/evaluations", {"application_codes": [app["application_code"]]})
        self.assertEqual(status, 201)
        code = out[0]["scenario_code"]

        status, out = _request("POST", "/decisions", {
            "actor": {"role": "SYSTEM", "name": "引擎"},
            "scenario_code": code, "decision": "APPROVED", "decision_ref": "AUTO-1",
        })
        self.assertEqual(status, 422)
        self.assertIn("有权部门", out["error"])

    def test_authority_decision_accepted_with_ref(self) -> None:
        app = demo_data.pro_league()
        _request("POST", "/applications", app)
        out = _request("POST", "/evaluations", {"application_codes": [app["application_code"]]})[1]
        code = out[0]["scenario_code"]
        status, out = _request("POST", "/decisions", {
            "actor": {"role": "COMPETENT_AUTHORITY", "name": "市体育局"},
            "scenario_code": code, "decision": "DEFERRED", "decision_ref": "体赛批[2026]48号",
            "rationale": "待补材料",
        })
        self.assertEqual(status, 201, out)
        self.assertEqual(out["locked_scenario_version"], 1)

    def test_opinion_recorded_as_expert_evidence(self) -> None:
        app = demo_data.pro_league()
        _request("POST", "/applications", app)
        out = _request("POST", "/evaluations", {"application_codes": [app["application_code"]]})[1]
        code = out[0]["scenario_code"]
        status, out = _request("POST", "/opinions", {
            "scenario_code": code,
            "expert": {"name": "测试专家", "title": "交通"},
            "dimension": "TRAFFIC", "statement": "建议错峰", "weight_suggestion": 0.4,
        })
        self.assertEqual(status, 201, out)
        status, opinions = _request("GET", f"/scenarios/{code}/opinions")
        self.assertEqual(status, 200)
        self.assertEqual(opinions[0]["evidence_class"], "EXPERT")


if __name__ == "__main__":
    unittest.main()
