"""HTTP 接口（仅标准库）：申报、外部事件喂送、评估、意见、公示与回看。

启动：python3 -m src.api [--port 8080]

所有写操作都是命令式 JSON；系统本身不产生批准，
POST /decisions 仅接受 actor.role=COMPETENT_AUTHORITY 且必须带 decision_ref。
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from src.report import (
    applicant_gap_report,
    comparison_overview,
    render_applicant_report,
    render_comparison,
    render_scenario_report,
    scenario_report,
)
from src.service import ReviewService, ServiceError

# 进程内单一服务实例（演示/联调用途；生产应替换为持久化事件库）
SERVICE = ReviewService()


class Handler(BaseHTTPRequestHandler):
    server_version = "EventReview/0.1"

    def _send(self, status: int, body: dict | list) -> None:
        data = json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: int, message: str) -> None:
        self._send(status, {"error": message})

    def _body(self) -> dict | None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            self._error(400, "缺少请求体")
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError as exc:
            self._error(400, f"JSON 解析失败：{exc}")
            return None

    def log_message(self, fmt: str, *args) -> None:  # 静音默认日志
        return

    # ------------------------------------------------------------------
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path, qs = parsed.path, parse_qs(parsed.query)
        try:
            if path == "/health":
                self._send(200, {"status": "ok", "events": len(SERVICE.events)})
            elif path == "/applications":
                self._send(200, list(SERVICE.applications.values()))
            elif path.startswith("/applications/"):
                code = path.rsplit("/", 1)[-1]
                if code not in SERVICE.applications:
                    self._error(404, f"申请不存在：{code}"); return
                data = applicant_gap_report(SERVICE, code)
                if qs.get("format") == ["text"]:
                    self._text(render_applicant_report(data))
                else:
                    self._send(200, data)
            elif path == "/scenarios":
                self._send(200, SERVICE.list_scenarios(include_inactive=qs.get("all") == ["1"]))
            elif path.startswith("/scenarios/"):
                rest = path[len("/scenarios/"):].strip("/").split("/")
                code = rest[0]
                if len(rest) == 1:
                    version = int(qs["version"][0]) if qs.get("version") else None
                    data = scenario_report(SERVICE, code, version)
                    if qs.get("format") == ["text"]:
                        self._text(render_scenario_report(data))
                    else:
                        self._send(200, data["view"])
                elif rest[1] == "history":
                    self._send(200, SERVICE.scenario_history(code))
                elif rest[1] == "opinions":
                    self._send(200, [e["payload"] for e in SERVICE.opinions.get(code, [])])
                else:
                    self._error(404, "未知子资源")
            elif path == "/comparison":
                codes = qs.get("scenario")
                if not codes:
                    self._error(400, "请用 ?scenario=...&scenario=... 指定方案"); return
                overview = comparison_overview(SERVICE, codes)
                if qs.get("format") == ["text"]:
                    self._text(render_comparison(overview))
                else:
                    self._send(200, overview)
            elif path == "/events":
                self._send(200, SERVICE.event_log())
            elif path == "/decisions":
                self._send(200, [e["payload"] | {"event_id": e["event_id"]} for e in SERVICE.decisions.values()])
            else:
                self._error(404, f"未知路径：{path}")
        except ServiceError as exc:
            self._error(404, str(exc))
        except Exception as exc:  # noqa: BLE001
            self._error(500, f"服务异常：{exc}")

    def _text(self, text: str) -> None:
        data = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        body = self._body()
        if body is None:
            return
        try:
            if path == "/applications":
                event = SERVICE.submit_application(body, actor_name=(body.get("applicant") or {}).get("name", ""))
                self._send(201, {"event_id": event["event_id"], "application_code": body.get("application_code"),
                                 "version": event["version"]})
            elif path.startswith("/applications/") and path.endswith("/amendments"):
                code = path.split("/")[2]
                event = SERVICE.amend_application(
                    code,
                    body["amendment_type"],
                    body.get("patch", {}),
                    body.get("changed_fields", []),
                    reason=body.get("reason", ""),
                    actor_name=body.get("actor_name", ""),
                )
                self._send(201, {"event_id": event["event_id"], "version": event["version"],
                                 "reevaluated_only": "仅含本申请的组合被重新计算"})
            elif path == "/external-events":
                event = SERVICE.ingest_external(body)
                self._send(201, {"event_id": event["event_id"],
                                 "note": "仅 CONSTRAINT_REGISTERED；沿用来源系统稳定 event_id"})
            elif path == "/evaluations":
                codes = body.get("application_codes")
                if not codes:
                    self._error(400, "需要 application_codes"); return
                views = SERVICE.evaluate_combinations(codes)
                self._send(201, [{"scenario_code": v["scenario_code"], "version": v["version"],
                                  "verdict": v["payload"]["verdict"], "plan_type": v["payload"]["plan_type"],
                                  "window": v["payload"]["window"], "changed": v["changed"]}
                                 for v in views])
            elif path == "/opinions":
                event = SERVICE.record_opinion(
                    body["scenario_code"], body["expert"], body["dimension"],
                    body["statement"], body.get("weight_suggestion"),
                )
                self._send(201, {"event_id": event["event_id"], "version": event["version"]})
            elif path == "/decisions":
                actor = body.get("actor") or {}
                event = SERVICE.publish_decision(
                    actor, body["scenario_code"], body["decision"], body["decision_ref"],
                    rationale=body.get("rationale", ""),
                    conditions=body.get("conditions"),
                    published=body.get("published", True),
                )
                self._send(201, {"event_id": event["event_id"], "decision_ref": body["decision_ref"],
                                 "locked_scenario_version": event["payload"]["scenario_version"]})
            else:
                self._error(404, f"未知路径：{path}")
        except ServiceError as exc:
            self._error(422, str(exc))
        except KeyError as exc:
            self._error(400, f"缺少字段：{exc}")
        except Exception as exc:  # noqa: BLE001
            self._error(500, f"服务异常：{exc}")


def serve(port: int = 8080) -> None:
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"赛事联审服务已启动：http://127.0.0.1:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    serve(args.port)
