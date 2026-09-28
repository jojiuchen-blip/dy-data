# 开发日志 — 2026-09-28

> 操作人：Your Name；本任务用户明确免建票并授权开发。
> 关联计划：[PDCA事件契约](../plans/delivery-plans/main-delivery-plan-pdca-events.md)

## 目标与边界

新增经营引擎独立只读事件投影与一致分页。基于远端main已核实提交7d779dd，在独立分支pdca/event-contract-20260928开发。原入口有其他任务未提交改动，未覆盖；原PDCA目录仅只读。没有修改业务数据、采集/指标逻辑、模型/迁移或生产环境。

## 实现与交接

- 新契约pdca-event-evidence-v2及两个GET路由，十个限定字段数据集；旧observation-v1不变。
- 独立数据库REPEATABLE READ/READ ONLY（SQLite显式读事务），投影后回滚关闭；分页读取短期内存冻结行。
- 快照10分钟、每进程4个、构建并发1；行数/字节/单字段限额，过期410、容量429、超限413、源故障503；认证每页重验并先释放连接，避免小连接池自阻塞。
- 有效退款和原始退款分开；撤销时间未知保留撤销事实；部分退款不自动剔除整单；采集完整水位和正式实收语义仍未知，publishable=false。
- 交付[字段契约/最小下一步](../api/pdca-event-snapshot.md)、两份JSON Schema和纯合成样例；已反馈原PDCA任务衔接。

## 验证记录

| 验证 | 实际结果 |
|---|---|
| 原只读接口/访问基线 | 44通过 |
| 新接口测试驱动 | 首批6项因404失败，逐步增加到18项，含先红后绿修复 |
| PDCA及相邻只读接口专项 | 88通过、6跳过；跳过为4项旧PostgreSQL和2项新增PostgreSQL，未提供本地临时实例 |
| PostgreSQL 16隔离CI | [运行36372808675](https://github.com/jojiuchen-blip/dy-data/actions/runs/36372808675)，94通过、0跳过，23.09秒；源码提交68fae02，PR合并测试引用cbc01cc。覆盖实际只读拒写、REPEATABLE READ并发视图及全部投影 |
| 完整回归初轮 | 2905通过、517跳过、4失败、8错误，313.57秒；4项缺TypeScript、8项缺Chromium |
| 缺依赖项定向复跑 | 在本工作区补齐npm锁文件依赖和临时测试浏览器后，19通过，37.28秒；未改业务代码 |
| 最后路由修订回归 | 新接口及隔离CI约束19通过，8.03秒 |
| Web production build | 通过，4.98秒；仅既有bundle大小提示 |
| 机器契约 | Manifest及10个数据集页全部通过交付JSON Schema校验 |
| 独立代码审查 | 3项问题已修，复核通过；后续另补连接池和认证查询失败测试 |
| 治理 | suite lock有效，全局文件0错误/警告，计划结构13/13及执行上下文门禁通过 |
| 链接索引 | 已刷新；33个历史坏链，与HEAD基线数量相同，本任务新增坏链0 |

全仓串行运行较慢，改用4进程按文件隔离；既有XLSX二进制参数含时间戳，首次xdist收集名称不一致。仅在ignored tmp目录加入pytest_make_parametrize_id为bytes参数使用稳定显示名，未改变测试值或仓库测试。全仓输出保留在ignored tmp/pdca-contract；不能把517项跳过计为通过。没有声称一次完整回归全绿。

## 审查修复

1. 撤销状态但缺cancel_time：额外生成时间未知的revocation，防止只见正向事件。
2. 核销状态字典遗漏：完整覆盖既有规范化及valid/fulfilled/used/reversed/refunded等取值。
3. 构建内存：数据库侧先拒绝超大投影字段，流式读取并累计字节，保留冻结总量限额。
4. 中文用户名比较、源schema错误分类、单连接池自阻塞、认证查询错误脱敏均有回归测试。

## 事实缺口与待发布项

当前模型缺完整不可变核销/退款历史、可信购买数量及已核准连续水位。尚未读取生产新投影，不能断言生产库根本没有193笔历史退款时间；历史四日实收逐单核验是正面证据，但不能全局置true。源缺口、语义待确认和仅投影已解决项详见接口文档。

[草稿PR #42](https://github.com/jojiuchen-blip/dy-data/pull/42)已创建。用户明确授权公开推送后，分支推送成功；GitHub连接器创建PR返回403，浏览器工具初始化失败，使用已配置Git身份调用GitHub官方API成功创建，凭证未输出或落盘。隔离PostgreSQL CI已通过；[常规CI运行36372808739](https://github.com/jojiuchen-blip/dy-data/actions/runs/36372808739)截至本次回填仍在运行，未宣称通过。CI配置只增加测试，不添加生产权限或部署步骤。源码未部署，未启用正式API指标。

最小后续：代码审阅及PostgreSQL隔离检查 → 经授权发布 → 一次API差集与覆盖核验 → 按确证缺口决定是否另外授权补采/历史事件存储/回填。没有提出无意义的腾讯云登录；仅关键证据无法通过已有API取得时再说明目的。

Foundation增量请求：[S4-FCR-PDCA-001](../plans/foundation-plans/foundation-change-requests-pdca-events.md)，仅文档索引建议，未改Foundation业务规则。

## 复盘

一致快照和完整业务历史必须分别证明；观察时间不能代替业务时间或水位。此经验已落实契约与测试，本次不另改全局规则。
