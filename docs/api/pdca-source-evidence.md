# PDCA 独立只读证据接口

状态（2026-09-24）：已完成限定API镜像发布和授权会话真实读取；尚未替代人工导表。下方早期测试记录保留为历史证据，以本节和发布检查表的最新更新为准。

新增接口、独立认证及旧接口兼容专项53项通过；隔离PostgreSQL只读验证3项通过。基于发布基线的干净全量回归3135 passed、172 skipped，退出0。生产仅替换API，保留原运行环境，其他服务容器及启动时间不变；未运行迁移、补采、权限初始化或网关重载。原页面可访问，新接口匿名401，授权会话已完成分页读取。

真实候选仅用于核验。已发现成交集合、金额语义和观察时点需要进一步对齐，完整采集水位仍不可证明；不能把接口连通当作核销率验收通过。线上镜像已含接口，但源码合入主分支前，常规发布仍可能覆盖此接口。详见[限定发布检查表](pdca-api-release-checklist.md)。

`GET /api/v1/admin/pdca-source-evidence`。原接口不变；无迁移、采集或刷新操作。独立验证原签名会话及最高管理员身份，数据库用户还须启用、初始化、会话版本有效。不调用旧权限初始化依赖。

PostgreSQL独立READ ONLY事务，查询8秒、锁等待1秒，结束回滚；SQLite测试开启query_only并恢复连接原设置。数据库强制只读已在隔离PostgreSQL实测，生产未进行故意写入测试；SQLite不能替代PostgreSQL验证。

## 请求

dataset：orders、coupons、verifications、refunds、sku_rules、poi_mappings。
periodStart/periodEnd：上海业务日含首尾，最多7天；observedThrough：带时区，不得未来或早于开始日；pageSize：1–500；cursor：上页next_cursor，不可跨范围/数据集/截止/契约使用。

## 集合与字段

以create_order_time选择当前精诚养车SKU规则匹配的订单，不要求有券、核销或线索。不以sale_time/pay_time代替下单时间。券、退款按订单ID关联，核销按券ID关联。

字段和可空性见 `apps/api/dy_api/pdca_source_schema.py` 显式Pydantic投影，kind区分类型。无raw_payload。金额按原字段整数分返回，缺失null，不混加订单/券/退款金额。未经核实的默认零备用金额字段不输出；与Excel实收口径等价性待核验。

## 响应与限制

data包含rows、next_cursor、has_more。meta.schema_version为pdca-source-observation-v1，含查询指纹、范围、观察截止、查询时间。

固定标记read_only=true、consistent_snapshot=false、collection_complete_through=null、refund_reason_available=false、amount_semantics_verified=false。缺下单时间、未映射商品和孤立事件的覆盖量未知；维度是当前状态。核销时间过滤不等于历史重放，退款/撤销返回当前行。查询时间及请求截止不是采集水位。

未知状态不归类为成功、未知原因不归因；完整覆盖和逐单对账未获证明前，PDCA不得切换主源。

## 验证

匿名401、非最高管理员403、非法查询422、源不可用503。专项测试 `tests/test_pdca_readonly_access.py`、`tests/test_pdca_source_evidence.py`；旧接口回归 `tests/test_ranking_source_evidence.py`。2026-09-21三文件50项通过。

`tests/test_pdca_readonly_postgres.py`在本机一次性PostgreSQL 18容器中3项通过：写入被数据库拒绝、事务设置及连接归还后恢复、真实应用订单读取。测试只接受回环测试端口、固定测试数据库；不使用生产连接。临时容器已移除。生产规模、生产字段对账及全量回归仍未通过验收，部署另行授权。

上述旧开发目录曾发现迁移head断言不一致。发布候选现基于已核实线上提交d36d991b：旧证据接口与迁移基线85项通过（218.64秒）；独立临时目录消除了公共pytest目录清理权限错误，未改迁移或测试断言。迁入后新增接口、路由注册及旧证据接口53项通过（12.10秒）；本机一次性PostgreSQL测试3项通过（3.47秒），容器已移除。前端构建通过（有大包提示），未改前端源代码。候选全量回归仍进行中，不宣称已通过或上线。

独立代码审查未发现Critical/Important问题；此为源代码审查，不替代全量测试、真实数据对账或生产验证。用户已批准限定API发布和短暂API重启；未批准数据库迁移或其他服务更新，网关必要平滑重载尚待确认。

首次候选全量测试在1445通过、31跳过后，因Windows子进程输出UTF-8而父进程按GBK读取，在旧CLI帮助测试中失败。仅统一测试启动环境为`PYTHONUTF8=1`后，该用例1项通过（1.44秒）；未修改业务代码或测试断言。统一编码后的全量重跑仍进行中，不将单项修复视为全量通过。

全量重跑最终结果：3135 passed、172 skipped、1 error（1848.09秒）。错误在会话结束时原`vite_uat_base_url`夹具清理测试Node进程超时，并非订单时间用例断言失败。核实遗留进程属于本轮测试后，在提升权限下仅清理该进程树；原夹具在提升权限下重新启动和退出通过（5.72秒）。未修改夹具、旧业务或断言。此补测定位了环境清理问题，但不等同于取得一次退出码0的完整回归；发布闸门仍保留该事实和172项跳过，等待后续干净全量或明确审阅。

已知待核验边界：游标解码限制键长度512字符，生成端未作对称限制，超长源键可能无法继续分页；生产接入前应确认实际键约束或补充验证。
