"""组合规划：在时间弹性与备选场馆范围内枚举可比方案。

产出三类候选（plan_type）：
- SAME_WEEKEND 全部安排在同一周末（含换备选馆的变体）
- STAGGERED   在各自可接受周末内错峰，占用窗互不重叠
- CO_HOSTED   同周末、同一大馆联合承办（合并峰值受安全容量约束）

时间只按“周末档”（周六开赛）对齐；错峰组合数量可能很大，
这里按“预算年度分布 + 日期早/中/晚”抽取有代表性的少数组合，
保证评审会上比较的是有实质区别的摆法。

候选只描述“怎么摆”，能否兑现由 engine.evaluate 测算。
"""
from __future__ import annotations

import hashlib
import itertools
from datetime import timedelta

from src.domain import to_date

PLAN_LABELS = {
    "SAME_WEEKEND": "同周末承办",
    "STAGGERED": "错峰承办",
    "CO_HOSTED": "联合承办",
}

STAGGERED_PER_PATTERN = 3   # 每种年度分布取早/中/晚各一
STAGGERED_TOTAL_CAP = 12


def _duration_days(window: dict) -> int:
    return (to_date(window["end"]) - to_date(window["start"])).days


def _saturdays_near(anchor: str, radius_days: int) -> list[str]:
    """anchor ± radius_days 内的所有周六日期。"""
    anchor_date = to_date(anchor)
    out = []
    for delta in range(-radius_days, radius_days + 1):
        d = anchor_date + timedelta(days=delta)
        if d.weekday() == 5:  # 周六
            out.append(d.isoformat())
    return out


def acceptable_windows(app: dict) -> list[dict]:
    """该申请在其时间弹性内可接受的周末档集合。"""
    tr = app["time_requirement"]
    preferred = tr["preferred_windows"]
    flex = tr["flexibility"]
    flex_days = int(tr.get("flex_days", 0) or 0)
    duration = _duration_days(preferred[0])

    starts: set[str] = set()
    for w in preferred:
        if flex == "FIXED":
            starts.add(w["start"])
        else:
            starts.update(_saturdays_near(w["start"], flex_days))

    def win_at(start: str) -> dict:
        return {"start": start, "end": (to_date(start) + timedelta(days=duration)).isoformat()}

    return [win_at(s) for s in sorted(starts)]


def _code(plan_type: str, codes: list[str], signature: str) -> str:
    digest = hashlib.sha1(f"{','.join(codes)}|{signature}".encode("utf-8")).hexdigest()[:8]
    short = {"SAME_WEEKEND": "SW", "STAGGERED": "ST", "CO_HOSTED": "CH"}[plan_type]
    return f"SCN-{short}-{digest}"


def _win_from(app: dict, start: str) -> dict:
    days = _duration_days(app["time_requirement"]["preferred_windows"][0])
    return {"start": start, "end": (to_date(start) + timedelta(days=days)).isoformat()}


def _largest_venue(applications: list[dict], registry) -> str | None:
    candidates: set[str] = set()
    for a in applications:
        vr = a["venue_requirement"]
        candidates.add(vr["primary_venue_code"])
        candidates.update(vr.get("fallback_venue_codes", []))
    best, best_cap = None, -1
    for code in candidates:
        v = registry.venue(code)
        if v and (v.capacity or {}).get("approved_capacity", 0) > best_cap:
            best, best_cap = code, v.capacity["approved_capacity"]
    return best


def generate_candidates(applications: list[dict], registry) -> list[dict]:
    """返回候选方案列表：{scenario_code, plan_type, assignments, note}。"""
    apps = sorted(applications, key=lambda a: a["application_code"])
    codes = [a["application_code"] for a in apps]
    candidates: list[dict] = []
    seen: set[str] = set()

    def add(plan_type: str, assignments: dict[str, dict], note: str) -> None:
        sig_start = min(v["window"]["start"] for v in assignments.values())
        sig_schedule = ";".join(
            f"{c}={v['window']['start']}~{v['window']['end']}@{v.get('venue_override') or next(a for a in apps if a['application_code'] == c)['venue_requirement']['primary_venue_code']}"
            for c, v in sorted(assignments.items())
        )
        scode = _code(plan_type, codes, f"{sig_start}|{sig_schedule}")
        if scode in seen:
            return
        seen.add(scode)
        candidates.append(
            {"scenario_code": scode, "plan_type": plan_type, "assignments": assignments, "note": note}
        )

    per_app = [(a, acceptable_windows(a)) for a in apps]
    common = sorted(set.intersection(*(set(w["start"] for w in wins) for _, wins in per_app)))

    # 1) 同周末：每个共同周末一档，各用申报主场馆
    for start in common:
        assignments = {c: {"window": _win_from(a, start), "venue_override": None} for c, a in zip(codes, apps)}
        add("SAME_WEEKEND", assignments, f"三项赛事同周末（{start}）各用申报主场馆")

    # 1b) 撞馆时换备选馆的变体（仅在资源日历中有登记的备选馆）
    primary_groups: dict[str, list[str]] = {}
    for a in apps:
        primary_groups.setdefault(a["venue_requirement"]["primary_venue_code"], []).append(a["application_code"])
    for start in common:
        for venue_code, users in primary_groups.items():
            if len(users) < 2:
                continue
            for moving_code in users:
                moving = next(a for a in apps if a["application_code"] == moving_code)
                for fb in moving["venue_requirement"].get("fallback_venue_codes", []):
                    if registry.venue(fb) is None or fb == venue_code:
                        continue
                    assignments = {
                        c: {"window": _win_from(a, start), "venue_override": fb if c == moving_code else None}
                        for c, a in zip(codes, apps)
                    }
                    add(
                        "SAME_WEEKEND",
                        assignments,
                        f"{start} 同周末：{moving['event_name']}临时换至备选馆 {fb}，其余不变",
                    )

    # 2) 错峰：占用窗（含搭拆）互不重叠；按年度分布抽代表组合（两项及以上赛事才有意义）
    if len(apps) >= 2:
        combos: list[tuple] = []
        for combo in itertools.product(*(w for _, w in per_app)):
            if len({w["start"] for w in combo}) < len(apps):
                continue
            occs: list[tuple] = []
            clash = False
            for (a, _), win in zip(per_app, combo):
                tr = a["time_requirement"]
                occ_start = to_date(win["start"]) - timedelta(days=int(tr.get("setup_days", 0) or 0))
                occ_end = to_date(win["end"]) + timedelta(days=int(tr.get("teardown_days", 0) or 0))
                if any(occ_start <= e and s <= occ_end for s, e in occs):
                    clash = True
                    break
                occs.append((occ_start, occ_end))
            if not clash:
                combos.append(combo)

        groups: dict[tuple[int, ...], list[tuple]] = {}
        for combo in combos:
            pattern = tuple(to_date(w["start"]).year for w in combo)
            groups.setdefault(pattern, []).append(combo)

        picked = 0
        for pattern in sorted(groups):
            bucket = sorted(groups[pattern], key=lambda c: tuple(w["start"] for w in c))
            if len(bucket) <= STAGGERED_PER_PATTERN:
                chosen = bucket
            else:
                idxs = sorted({0, len(bucket) // 2, len(bucket) - 1})
                chosen = [bucket[i] for i in idxs]
            for combo in chosen:
                if picked >= STAGGERED_TOTAL_CAP:
                    break
                assignments = {c: {"window": win, "venue_override": None} for (c, win) in zip(codes, combo)}
                labels = "、".join(f"{a['event_name']}→{win['start']}" for (a, _), win in zip(per_app, combo))
                add("STAGGERED", assignments, f"错峰安排：{labels}")
                picked += 1

    # 3) 联合承办：同周末共用最大容量场馆（两项及以上赛事才有意义）
    if len(apps) >= 2:
        big = _largest_venue(apps, registry)
        if big and common:
            for start in common:
                assignments = {
                    c: {"window": _win_from(a, start), "venue_override": big}
                    for c, a in zip(codes, apps)
                }
                add("CO_HOSTED", assignments,
                    f"{start} 同周末在 {big} 联合承办，统一安保动线，合并峰值受安全容量约束")

    candidates.sort(key=lambda c: (c["plan_type"], min(v["window"]["start"] for v in c["assignments"].values())))
    return candidates
