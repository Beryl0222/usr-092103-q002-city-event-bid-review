# 城市赛事承办联审服务

回答评审会上必须先回答的现实问题：**如果职业联赛、群众赛和国际邀请赛都选中同一个周末，
现有场馆、警力、交通和年度财政能否同时兑现**——而不是把三张各自漂亮的评分表分别放行。

本服务面向三类角色：

- **申请方**：按八要素申报，明确看到材料缺口与每条约束的来源；
- **评审专家**：在同一组可比方案上比较不同摆法的后果，记录意见与权重；
- **主管部门（有权部门）**：凭文号作出批准/驳回/缓议并留痕。系统只测算、**不代批**。

## 核心原则

1. **事件溯源、稳定标识**。一切状态变化都是追加事件；既有五个事件类型与四个聚合标识保持稳定，
   外部系统（场馆日历、警务勤务、交通监测、预算台账、履约台账）继续只喂送 `CONSTRAINT_REGISTERED`，
   `event_id` 沿用来源系统编号（如 `venue-calendar:V-STADIUM:2026-09-01`），具备幂等性。
2. **结论三分**。每条结论标注证据类别：
   - `OBJECTIVE` 客观指标：申报材料或资源台账原文，可溯源到文号与事件 ID；
   - `ASSUMPTION` 测算假设：引擎采用的口径与系数（承载率、警力系数、峰值重合系数、跨年分摊口径等），
     集中声明、报告公示、可被专家质疑后替换重算；
   - `EXPERT` 专家意见：仅来自 `OPINION_RECORDED`，引擎不代为生成。
3. **系统不批准**。测算裁定只有 `FEASIBLE / CONDITIONAL / INFEASIBLE`；
   批准（`APPROVED/REJECTED/DEFERRED`）只能由 `COMPETENT_AUTHORITY` 携带批复文号经
   `DECISION_PUBLISHED` 作出，`SYSTEM` 等其他角色一律被拒绝。
4. **增量重算**。临时换馆、联合承办、延期、材料更正只重新计算**受影响组合**；
   结果无实质变化（内容指纹一致）不产生新版本。
5. **公示可回看**。已公示版本整包封存，后续任何更新都不覆盖；新风险/新排期另立新方案、新版本。

## 申报八要素

赛事级别、时间弹性、场馆需求（含备选馆）、预期人流（单日峰值/总量）、资金结构
（总预算及自筹/赞助/市场/财政申请）、安全责任（责任险、安保方案文号、医疗点）、
市场开发（转播与收入预测）、赛事遗产计划（群众体育投入、赛后利用）。

## 测算口径（摘要）

| 维度 | 核对方式 | 证据类别 |
|---|---|---|
| 场馆 | 含搭拆的占用窗撞期、同比赛日撞用、峰值 vs 核定容量×承载率(0.9)、联办合并峰值 | 撞期为客观；容量换算为假设 |
| 警力 | 按“同日并发簇”计算需求（基础 80 人＋每万人 12 人×级别系数 1.0/1.2/1.5），与台账容量（含既有勤务折减）比较 | 需求为假设；容量与勤务为客观 |
| 交通 | 簇峰值×散场重合系数 0.80，对比通道日容量（施工/管制按台账系数折减） | 需求为假设；容量与管制为客观 |
| 财政 | 财政申请按自然年、跨年按天数分摊，对比各年度限额与已承诺事项 | 客观（超预算直接阻断） |
| 履约 | 历史良好/合格/不佳/违约记录客观列示；是否限制承办由有权部门判断 | 客观 |

系统输出四维参考分（均为 0–100、越高越好）：群众普及、财政安全、交通顺畅、市场回报。
分数是测算分，不是专家评分；专家可记录不同权重，最终取舍与批准属于有权部门。

## 组合类型

- `SAME_WEEKEND`：全部赛事同一周末（含撞馆时换备选馆的变体）；
- `STAGGERED`：在各自时间弹性内错峰，占用窗（含搭拆）互不重叠，跨年方案体现预算年度后果；
- `CO_HOSTED`：同周末同一大馆联合承办，合并峰值受安全容量约束，须提交联合动线方案。

## 资料结构

```
contracts/domain.schema.json   事件信封、载荷结构与稳定枚举（含新增 APPLICATION_AMENDED）
data/sample.json               最小事件样例（原有）
data/sample_constraint.json    外部 CONSTRAINT_REGISTERED 喂送样例（带来源系统/文号）
src/contracts.py               信封+载荷运行期校验（src.validator.validate_event 仍兼容）
src/domain.py                  申报视图、材料缺口核对、资源注册表（由约束事件物化）
src/engine.py                  冲突核对、跨年财政、四维评分、证据三分、裁定
src/planner.py                 同周末/错峰/联办候选枚举
src/service.py                 事件溯源服务：命令、增量重算、版本封存、禁止代批、重放
src/report.py                  申请方核对单、方案说明、组合取舍中文报告
src/demo_data.py               三赛同周末演示数据与真实资源日历事件
src/api.py                     HTTP 接口（标准库）
src/cli.py                     命令行完整剧情演示
tests/                         契约/引擎/服务流程/HTTP 共 25 个用例
```

## 快速开始

```bash
# 全部检查
python3 -m unittest discover -s tests

# 完整剧情演示（约 11 个环节）
python3 -m src.cli

# HTTP 服务
python3 -m src.api --port 8080
```

CLI 演示剧情：外部资源台账喂送 → 三赛申报 → 材料缺口（群众赛缺安保方案/责任险）→
首轮测算（同周末撞馆、警力 420>380、财政超 300 万，均不可行）→ 补材料只重算三赛组合
（双赛组合 18 个方案版本不变）→ 无关台账更新重算但不升版 → 专家意见 →
四维对比与取舍说明 → 系统代批被拒、有权部门凭文号公示 → 公示后延期、旧版封存可回看 →
事件日志导出与重放重建。

## HTTP 接口摘要

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/applications` | 提交申报（八要素） |
| POST | `/applications/{code}/amendments` | 换馆/联办/延期/材料更正，只重算受影响组合 |
| POST | `/external-events` | 喂送 `CONSTRAINT_REGISTERED`（沿用来源稳定 event_id，幂等） |
| POST | `/evaluations` | 对一组申请枚举并测算全部组合 |
| GET | `/scenarios` / `/scenarios/{code}` | 方案列表 / 指定版本（`?version=&format=text`） |
| GET | `/scenarios/{code}/history` `/opinions` | 版本沿革 / 专家意见 |
| GET | `/comparison?scenario=...` | 多方案对比（含中文文本） |
| POST | `/opinions` | 专家意见（自动标记 EXPERT） |
| POST | `/decisions` | **仅 COMPETENT_AUTHORITY + decision_ref**，否则 422 |
| GET | `/applications/{code}` | 材料缺口与约束来源（溯源到文号/事件ID） |
| GET | `/events` `/decisions` | 事件日志与公示台账 |

## 事件目录

| 事件 | 聚合 | 角色 | 说明 |
|---|---|---|---|
| `APPLICATION_RECEIVED` | hosting_application | APPLICANT | 申报受理 |
| `APPLICATION_AMENDED` | hosting_application | APPLICANT | 换馆/联办/延期/材料更正（带 amendment 与 changed_fields） |
| `CONSTRAINT_REGISTERED` | resource_constraint | RESOURCE_SYSTEM | 场馆/警力/交通/财政/履约台账更新（外部稳定标识） |
| `SCENARIO_EVALUATED` | review_scenario | SYSTEM | 方案测算版本（含指标、假设、冲突、四维分；无变化不升版） |
| `OPINION_RECORDED` | review_scenario | EXPERT | 专家意见与建议权重 |
| `DECISION_PUBLISHED` | decision_release | **COMPETENT_AUTHORITY** | 批准/驳回/缓议，必须有文号；锁定方案版本 |

## 边界说明

- 系统展示“不同组合在时间窗与预算年度上的后果”，但不替有权部门批准；
- “无资源记录”被明确提示为无法核对（WARNING），而不是当作资源可用；
- 历史履约不佳只客观提示并列入复核条件，不自动剥夺承办资格；
- 演示中的进程内存储适合联调；生产部署应将追加式事件日志落到持久库，
  状态随时可由事件流重放（`ReviewService.replay`）。
