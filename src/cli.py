"""命令行演示：三赛同周末联审完整剧情。

运行：python3 -m src.cli
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from src import demo_data
from src.report import (
    applicant_gap_report,
    comparison_overview,
    render_applicant_report,
    render_comparison,
    render_scenario_report,
    scenario_report,
)
from src.service import ReviewService, ServiceError

SEP = "=" * 82


def heading(title: str) -> None:
    print("\n" + SEP)
    print(title)
    print(SEP)


def main() -> None:
    svc = ReviewService()

    # ---- 0. 外部真实资源日历（先有资源台账，再收申报） ----------------
    heading("〇、外部系统喂送真实资源日历与履约台账（CONSTRAINT_REGISTERED，稳定标识）")
    for ev in demo_data.external_constraint_events(None):
        svc.ingest_external(ev)
        print(f"  ✓ {ev['event_id']}  [{ev['source_system']} {ev['source_ref']}] {ev['summary']}")

    # ---- 1. 三项赛事申报 ----------------------------------------------
    heading("一、三项赛事提交申报：职业联赛 / 群众赛 / 国际邀请赛，均首选 11 月 14 日周末")
    apps = [demo_data.pro_league(), demo_data.mass_event(), demo_data.international()]
    trio = [a["application_code"] for a in apps]
    for payload in apps:
        ev = svc.submit_application(payload, actor_name=payload["applicant"]["name"])
        print(f"  ✓ {ev['event_id']} {payload['application_code']}《{payload['event_name']}》")

    # ---- 2. 申请方材料核对单（群众赛有缺口） --------------------------
    heading("二、申请方视图：材料缺口与约束来源（以群众赛为例）")
    gap = applicant_gap_report(svc, "APP-MASS-2026-11")
    print(render_applicant_report(gap))

    # ---- 3. 首轮组合测算 ----------------------------------------------
    heading("三、系统对全部摆法进行首轮测算（同周末 / 换馆 / 联合承办 / 错峰）")
    # 另建一个“职业联赛+国际邀请赛”双赛组合，用于演示增量重算边界
    duo = ["APP-PRO-2026-07", "APP-INTL-2026-03"]
    svc.evaluate_combinations(duo)
    results = svc.evaluate_combinations(trio)
    for r in results:
        p = r["payload"]
        print(f"  {r['scenario_code']} v{r['version']} | {p['plan_type']:<11} | {p['verdict']:<11} | {p['window']['start']}~{p['window']['end']} | {r.get('note', '')[:46]}")
    print(f"\n  共生成 {len(results)} 个可比方案；另含双赛组合 {len(svc.list_scenarios()) - len(results)} 个。")

    same = next(r for r in results if r["payload"]["plan_type"] == "SAME_WEEKEND"
                and r["payload"]["window"]["start"] == "2026-11-14"
                and all(a.get("venue_override") is None for a in r["payload"]["assignments"].values()))
    print("\n  同周末原方案的关键阻断（节选）：")
    for c in [c for c in same["payload"]["conflicts"] if c["severity"] == "BLOCKER"][:5]:
        print(f"    - [{c['dimension']}] {c['message']}")

    # ---- 4. 材料更正：只重算受影响方案 -------------------------------
    heading("四、群众赛补齐安保材料（MATERIAL_CORRECTION）——只重算含该赛事的组合")
    duo_versions_before = {s["scenario_code"]: s["version"] for s in svc.list_scenarios(include_inactive=True)
                           if set(svc.scenario_apps.get(s["scenario_code"], [])) == set(duo)}
    svc.amend_application(
        "APP-MASS-2026-11", "MATERIAL_CORRECTION",
        {
            "safety_responsibility": {
                "insurance_amount_cny": 20_000_000,
                "security_plan_ref": "公保审[2026]0322号",
                "medical_stations": 4,
            }
        },
        changed_fields=["safety_responsibility.insurance_amount_cny",
                        "safety_responsibility.security_plan_ref",
                        "safety_responsibility.medical_stations"],
        reason="按公安预审意见补交易责险保单与安保方案文号",
        actor_name="李秘书",
    )
    unaffected = sum(
        1 for code, v in duo_versions_before.items()
        if max(svc.scenario_versions[code]) == v
    )
    print(f"  ✓ 双赛组合（不含群众赛）共 {len(duo_versions_before)} 个方案，版本全部保持不变：{unaffected}/{len(duo_versions_before)}")

    refreshed = svc.list_scenarios()
    trio_set = set(trio)

    def in_trio(s: dict) -> bool:
        return set(svc.scenario_apps.get(s["scenario_code"], [])) == trio_set

    def intl_in_jan(s: dict) -> bool:
        p = svc.get_scenario(s["scenario_code"])["payload"]
        w = p["assignments"].get("APP-INTL-2026-03", {}).get("window", {})
        return w.get("start", "").startswith("2027-01")

    jan = next(s for s in refreshed
               if in_trio(s) and s["plan_type"] == "STAGGERED" and intl_in_jan(s) and s["verdict"] != "INFEASIBLE")
    print(f"  ✓ 三赛组合已重算；其中国际赛延至次年 1 月的错峰方案 {jan['scenario_code']} 现为：{jan['verdict']}（有条件即可放行）")

    # ---- 5. 外部台账无影响更新：重算但不升版 --------------------------
    heading("五、履约台账补录一条与本批申请无关的记录：受影响方案重算，指纹无变化不升版")
    versions_before = {s["scenario_code"]: s["version"] for s in svc.list_scenarios()}
    svc.ingest_external({
        "event_id": "performance-register:H-CITY:2026-10-01",
        "event_type": "CONSTRAINT_REGISTERED",
        "aggregate_type": "resource_constraint",
        "aggregate_id": "history-h-city",
        "occurred_at": "2026-10-01T09:00:00+08:00",
        "version": 1,
        "summary": "履约台账补录：其他协会记录（与本批申请无关）",
        "source_system": "performance-register",
        "source_ref": "体履[2025]年鉴-补1",
        "actor": {"role": "RESOURCE_SYSTEM"},
        "payload": {
            "resource_type": "HISTORY", "resource_code": "H-CITY",
            "resource_name": "全市大型活动履约台账",
            "records": [{"applicant_code": "ORG-OTHER", "year": 2025,
                         "event_name": "其他单位活动", "performance": "GOOD", "note": "无"}],
        },
    })
    changed = [c for c, v in versions_before.items() if max(svc.scenario_versions[c]) != v]
    print(f"  ✓ 全部在评方案完成复核，产生新版本的方案数：{len(changed)}（无实质变化不升版）")

    # ---- 6. 专家意见 ---------------------------------------------------
    heading("六、专家在评审会上记录意见（OPINION_RECORDED，证据类别=专家意见）")
    chosen_code = jan["scenario_code"]
    svc.record_opinion(chosen_code, {"name": "赵平安", "title": "交通管理专家"}, "TRAFFIC",
                       "赞成国际邀请赛延至次年 1 月：11 月 14 日奥体片区施工叠加博览会勤务，三赛同日散场风险不可控；"
                       "1 月无施工与勤务冲突，建议权重 0.35。", weight_suggestion=0.35)
    svc.record_opinion(chosen_code, {"name": "钱惠民", "title": "群众体育专家"}, "MASS_SPORTS",
                       "群众赛应保留在 11 月，方便社区队伍组织；职业联赛弹性最小，建议优先保联赛档期。",
                       weight_suggestion=0.25)
    svc.record_opinion(chosen_code, {"name": "孙稳健", "title": "财政评审专家"}, "FISCAL",
                       "2026 年度额度在三赛同办时缺口约 300 万元；国际赛跨年安排后各年度均有余量，"
                       "且 2500 万元财政申请须按绩效目标分期拨付。", weight_suggestion=0.30)
    print("  ✓ 已记录 3 条专家意见（附建议权重；权重仅参考，不改变系统测算分）")

    # ---- 7. 组合对比与取舍说明 ----------------------------------------
    heading("七、联审会组合对比：为何选此弃彼（群众普及/财政/交通/市场四维）")
    # 取代表性方案：同周末原方案、联办方案、2026 内错峰、跨年错峰（拟选）
    representative = [same["scenario_code"]]
    cohost = next(r["scenario_code"] for r in results
                  if r["payload"]["plan_type"] == "CO_HOSTED" and r["payload"]["window"]["start"] == "2026-11-14")
    representative.append(cohost)
    in_year_staggered = next(
        r["scenario_code"] for r in results
        if r["payload"]["plan_type"] == "STAGGERED"
        and all(w["window"]["start"].startswith("2026") for w in r["payload"]["assignments"].values())
    )
    representative.append(in_year_staggered)
    if chosen_code not in representative:
        representative.append(chosen_code)
    waived = [c for c in representative if c != chosen_code]
    print(render_comparison(comparison_overview(svc, representative), chosen=chosen_code, waived=waived))

    heading("八、拟选方案详单（每条结论标注客观指标 / 测算假设 / 专家意见）")
    print(render_scenario_report(scenario_report(svc, chosen_code)))

    # ---- 8. 批准只属于有权部门 ----------------------------------------
    heading("九、批准边界：系统角色尝试发布决定被拒绝；有权部门凭文号公示")
    try:
        svc.publish_decision({"role": "SYSTEM", "name": "联审测算引擎"}, chosen_code,
                             "APPROVED", "AUTO-001", rationale="测算可行自动批准")
    except ServiceError as exc:
        print(f"  ✗ 系统代批被拒绝：{exc}")
    decision = svc.publish_decision(
        {"role": "COMPETENT_AUTHORITY", "name": "市体育局（联合公安、财政、交通）", "title": "承办评审会"},
        chosen_code, "APPROVED", "体赛批[2026]47号",
        rationale="同周末三赛在体育场撞用且财政年度额度不足；采用错峰方案：群众赛、联赛留在 11 月，"
                  "国际邀请赛延至 2027 年 1 月并计入 2027 年度财政。专家意见与四维测算已记录留痕。",
        conditions=["群众赛按公保审[2026]0322号落实散场分流预案并演练一次",
                    "国际邀请赛财政资金按绩效目标分期拨付",
                    "1 月档赛前 30 日复核场馆、警力与交通台账"],
    )
    print(f"  ✓ 已公示：{decision['payload']['decision_ref']}，"
          f"锁定方案 {chosen_code} v{decision['payload']['scenario_version']}")

    # ---- 9. 公示后更正：旧版仍可回看 ----------------------------------
    heading("十、公示后群众赛申请延期：公示版本封存可回看，新排期另立新方案")
    published_version = decision["payload"]["scenario_version"]
    svc.amend_application(
        "APP-MASS-2026-11", "POSTPONEMENT",
        {"time_requirement": {"preferred_windows": [{"start": "2026-11-21", "end": "2026-11-22"}]}},
        changed_fields=["time_requirement.preferred_windows"],
        reason="因区级活动叠加，申请顺延一周", actor_name="李秘书",
    )
    history = svc.scenario_history(chosen_code)
    print(f"  已公示方案 {chosen_code} 的版本沿革（公示后不再被重算覆盖）：")
    for h in history:
        tag = f"← 已公示封存 {h['decision_ref']}" if h["published"] else ""
        print(f"    v{h['version']} {h['verdict']:<11} {h['window']['start']}~{h['window']['end']} "
              f"触发：{'、'.join(h['reevaluated_fields']) or '初评'} {tag}")
    old = svc.get_scenario(chosen_code, published_version)
    print(f"\n  回看公示版本 v{published_version}：结论 {old['payload']['verdict']}，"
          f"公示信息仍在：{old['published']['decision_ref']} / {old['published']['decision']}")
    new_trio = [s for s in svc.list_scenarios(include_inactive=True)
                if set(svc.scenario_apps.get(s["scenario_code"], [])) == trio_set
                and s["active"] and s["plan_type"] == "STAGGERED"]
    print(f"  延期后三赛组合重新生成在评错峰方案 {len(new_trio)} 个（新代码、新版本，不影响公示档案），例如：")
    for s in new_trio[:3]:
        print(f"    {s['scenario_code']} v{s['version']} {s['verdict']:<11} {s['window']['start']}~{s['window']['end']}")

    # ---- 10. 事件日志留痕与重建 ---------------------------------------
    heading("十一、事件日志留痕：所有结论可凭事件流重建")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        svc.save_events(str(path))
        rebuilt = ReviewService.replay(str(path))
        print(f"  ✓ 已写出 {len(svc.events)} 条事件至 {path.name} 并重放重建")
        print(f"  ✓ 重建后方案数 {len(rebuilt.list_scenarios(include_inactive=True))}，"
              f"公示 {len(rebuilt.decisions)} 份，与运行态一致："
              f"{len(rebuilt.scenario_versions) == len(svc.scenario_versions)}")
    print("\n  最近事件：")
    for e in svc.event_log()[-6:]:
        print(f"    {e['occurred_at']}  {e['event_type']:<20} {e['aggregate_id']:<24} v{e['version']}  {e['summary'][:40]}")

    print("\n" + SEP)
    print("演示结束：系统完成申报、核对、测算、对比、留痕；批准始终由有权部门作出。")
    print(SEP)


if __name__ == "__main__":
    main()
