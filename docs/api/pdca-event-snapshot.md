# PDCA 只读事件证据快照 v2

状态：本地实现及验证中，未部署。用户于2026-09-28明确免建票并授权本次独立只读接口。

## 需求和实现边界
正式验证须用 API。限定下单日窗口内的全部订单保留未支付、无券、未核销和已退款记录，不以分配表筛选；原始商品 ID 不合并。订单主指标45%，金额辅助只用订单实收，商品合并和实验由客户端负责。

独立 `GET /api/v1/admin/pdca-source-snapshots` 返回所有数据集计数及快照标识；`GET /api/v1/admin/pdca-source-snapshots/{snapshot_id}` 返回指定数据集页。schema_version=`pdca-event-evidence-v2`。沿用最高管理员只读鉴权；旧 observation-v1 保持不变。

单个数据库只读事务冻结字段白名单投影，随后使用短期内存快照分页；不新建数据库表，不提交业务事务。快照一致性只证明这次读取一致，不证明采集完整或可回放任意历史。所有快照 publishable=false，完整水位为 null。

数据集：orders、coupons、verification_events、refund_events、raw_refunds、quality_issues、collection_batches、collection_stages、sku_rules、poi_mappings。未知金额和时间保留 null；原始退款不能合并当成功退款，部分退款不能推定整单无效。

源模型无完整不可变核销历史、退款状态历史或已验证连续采集水位；不得通过改布尔值、填0、采集重放或回填放行。禁止输出凭证、客户手机号、完整 raw_payload、质量问题自由文本及批次错误原文。

## 验收范围
覆盖重复事件、撤销再核、多券、部分退款、核销后退款、迟到事件、截点前后、金额空值、鉴权失效、源不可用、稳定分页、限额和过期。7/4的193笔历史时间缺口与8/20的12笔/23条差异需发布后只读 API 实证，本地合成数据不能替代。

## 客户端接入

1. 调用 manifest，参数 `periodStart=2026-08-01&periodEnd=2026-08-07&observedThrough=2026-09-01T00:00:00%2B08:00`。日期为北京时间下单日，首尾包含，最多7天；cutoff 必须带时区且不晚于当前时间。推荐重复传 `skuIds=ID1&skuIds=ID2` 固定客户端白名单（1–100个ID）。省略时使用本次快照的当前精诚养车 SKU 规则，不能据此声称历史白名单完整。
2. 保存 `meta` 和 `data.datasets`。逐个调用 `/{snapshot_id}?dataset=orders&pageSize=500`，然后原样传回 `next_cursor`，直到 `has_more=false`。同一快照可重复读取；后续页面只从已冻结的字段投影读取，不重查业务源表。
3. 校验每数据集 `total_rows`、主键唯一、`dataset_sha256` 和全部页面 `snapshot_id` 一致。SHA256 的输入为按服务顺序排列的每行 Pydantic 紧凑 JSON，以 LF 连接且无尾 LF；消费者跨语言若不能保持字段顺序和时间格式，应保留源行并以行数/ID核对，不能对重新格式化的 JSON 计算后误报不同。
4. 失败保留旧已验收来源。410须丢弃本次未完成候选后重新取得 manifest，禁止续用新旧快照混页；401提示重新认证。全部页完成也不解除 publishable=false。

最大每数据集20,000行、全部50,000行、冻结 JSON 16MiB；单投影字段最多256Ki字符，数据库侧先检查。构建并发1个，每进程最多4个有效快照；10分钟到期。不主动淘汰未过期快照。缓存只保留脱敏字段，数据库事务在返回 manifest 前回滚关闭；每页重新鉴权，其他用户名不能读取。进程重启、跨 worker/实例不命中返回410，发布前需确认单 worker 或亲和路由。没有新增共享存储或持久快照表。

`as_of` 是本次冻结读取开始的服务时间，不是采集水位、业务发生时间或“当时系统已知”时间；`observed_through` 是业务比较截点。PostgreSQL 使用独立 `REPEATABLE READ, READ ONLY` 事务，SQLite 使用显式读事务。consistent_snapshot=true 的依据是实际冻结读取和并发更新测试；它与历史完整性独立。

## 字段映射与语义

| 数据集 / 键 | 来源与客户端映射 | 未知或限制 |
|---|---|---|
| orders / order_id | RawDouyinOrder；sku_id保留原始ID，create_order_time下单日，pay_time支付证据，updated_at源行修改 | 不查分配表，不按核销/退款状态过滤。下单时间缺失、未知SKU及源库未采集订单覆盖未证明 |
| payment_evidence | pay_time ≤ cutoff 为 paid_by_cutoff；晚于为 paid_after_cutoff；缺失unknown | 只描述时间证据，不推断免费/异常订单的成交资格；退款订单仍保留 |
| order_receipt_candidate_cent | 与旧v1相同：明确 receipt_amount + platform_discount_amount，整数分，完整性检查通过才计算 | 四个历史日已在PDCA逐单对账，但不能外推全范围。正式 order_receipt_amount_cent 暂null；paid_amount_cent不得作为实收兜底 |
| purchase_quantity | 未找到可直接信任的模型字段 | null，不用当前券行数猜购买数量 |
| coupons / coupon_id | RawDouyinOrderCoupon；order_id关联；当前状态及退款金额/时间原样保留 | 券退款汇总不能与refund_events相加；无源修改时间时coupon_updated_at仍null |
| verification_events / event_id | RawDouyinVerifyRecord投影；verify_id+事件种类SHA256形成稳定ID；券表补order_id | 每原始行可投影核销和撤销，撤销original_event_id关联该行核销。不是上游不可变event_id；原行覆写时不能恢复被覆盖的重核历史 |
| event_type / effective_at | verification、revocation、unknown；分别来自verify_time/cancel_time；保留verify_status原值 | 已撤销但无时间仍有revocation行且effective_at/within_business_cutoff=null。客户端遇到未知撤销时不能默认截至cutoff仍有效 |
| 重核 / 多券 | 不同verify_id独立事件，同券可见多次核销；订单通过order_id去重 | 不用排序猜previous_event_id；缺上游关联/历史时history_complete=false。接口不计算订单核销率 |
| refund_events / refund_event_id | DouyinRefundEvent，源库已生成的业务退款记录；order_id/coupon_id关联 | 当前可变事件行，不是完整退款状态历史；存在本行不证明全范围退款覆盖 |
| refund_status / effective_at | 仅status=2把occurred_at投影到effective_at，才可作成功退款时间证据 | 非2的effective_at=null。successful_observed_at是系统观测时间，不能替代业务退款时间 |
| refund_type / refund_scope | 1=partial，2=full，其余unknown；refund_amount_cent明确整数分 | partial不能当整单无效；full是否整单/单券仍结合coupon_id和业务规则。refunded_quantity、after_verification均null，不能猜 |
| within_business_cutoff | 已知有效事件时间 ≤ cutoff为true，之后false；时点或事件含义未知为null | 截点后的当前证据仍返回，客户端按明确语义取舍；迟到观测不会被source_observed_at过滤掉 |
| raw_refunds / source_record_key | 原始售后记录，保留refund_id/status/amount/申请和完成时间 | 独立于业务退款；不能从raw status50直接推出有效资金退款。没有可靠键不得按订单把多条售后强配某业务事件 |
| amount_field_type / completion_fields_present | 只查询精确refund_amount_cent的JSON类型、5个白名单完成字段的存在性 | 不返回原始字段值；type=missing/null有区别；“字段存在”不代表值有效或语义已证实 |
| quality_issues / issue_id | DataQualityIssue；issue_type/severity/order_id/coupon_id/source_run_id/created_at | 不输出message/raw_context。没有resolved字段，resolution_status=unknown；历史问题存在不一定现在仍阻断 |
| collection_batches / job_id | 订单/事件关联的source_run_id，或window与[start,cutoff]相交的JobRun；含失败/待执行状态 | 批次可混合数据源，仅是覆盖线索；无窗口且无法关联的历史批次未证明覆盖，不能把成功计数变成水位 |
| collection_stages / stage_run_id | 选中job_id对应JobStageRun，含status/committed_at | 不输出checkpoint_json，不用阶段完成时间代替业务完整截止 |
| sku_rules / poi_mappings | 冻结当前商品规则、全部当前POI到门店映射；rule_version是规则行与选中SKU集合摘要 | 无历史映射版本；POI唯一约束阻止多门店当前映射，不代表历史冲突已经解决，相关DQI仍须审核 |

状态字典 `pdca-status-evidence-v1`：核销状态先strip/lower并将连字符转下划线；已知核销为1/valid/verified/success/fulfilled/used/已核销，撤销为2/cancelled/canceled/revoked/reversed/refunded/已撤销。撤销状态加历史verify_time可以投影既有核销事实，不能据此忽略撤销。订单原始状态（含1、101、201）不直接转成“已核销”；normalized字段只是源当前值。退款业务状态只对2定义成功，其余原值作为非成功证据保留，不在本接口扩写未经核准的状态标签。

## 失败语义

| HTTP | 含义 | 客户端动作 |
|---|---|---|
| 401 / 403 | 未登录、过期/撤销认证 / 非最高管理员 | 保留历史，提示认证或权限问题 |
| 410 | 快照到期、进程不存在该快照或其他用户名 | 整批重新读；旧候选不发布 |
| 413 | 行数、字节或单字段超限 | 缩小日期/SKU范围；不接受截断数据 |
| 422 | 参数/时区/窗口/数据集/游标错误 | 修正请求；游标与快照及数据集绑定并有HMAC签名 |
| 429 | 构建并发或有效快照容量已满 | 遵守Retry-After，复用已有快照 |
| 503 | 库/表/查询不可用，源值无法满足schema | 报告未知或失败；不把空列表当成功来源，不泄露SQL/连接信息 |

## 缺口分类与达到正式验证的最小下一步

| 缺口 | 本次能否解决 / 已知证据边界 | 最小下一步与授权 |
|---|---|---|
| 业务退款、质量问题、批次未投影 | 已解决投影；不能由模型存在推定生产行已存在 | 审阅并发布本接口后用API核查。发布尚未授权；不需先扫码开展源码工作 |
| 7/4的193笔退款时间、8/20的12笔23条来源差异 | 未查询生产新投影，不能断言源数据库根本没有 | 同一快照按既有差集关联退款事件/DQI/字段诊断，输出汇总。若仍无证据再决定数据补全；不得硬排除 |
| 一致分页 | 已实现实际事务冻结；仅10分钟进程内保留 | CI PostgreSQL并发测试及发布环境worker/亲和路由核验；若要长期共享快照需另行设计授权 |
| 完整支付母体 | 查询已去除核销/分配/状态偏置；未证明上游采集全覆盖及缺日期记录 | 将分区/账号/商品范围与上游可验证总量及失败任务核对，不只核对样本 |
| 核销撤销重核/退款状态不可变历史 | 当前模型和upsert实现没有完整日志能力；这是源码能力限制，未宣称整库不存在其他历史证据 | 先核实目标库其他已授权历史证据。若确无历史，选择真实可支持的起点，或另行授权采集/历史事件存储；接口无法恢复被覆盖事件 |
| 连续完整水位/迟到与回补版本 | JobRun/JobStageRun本身不证明所有必要分区/来源无缺口，缺少已核准水位合同 | 先只读审计批次与源总量；需要新水位记录、补采或回填时另行授权。未知期间不发布 |
| 通用订单实收、免费/缺支付时间、退款生效粒度 | 需要业务语义和全范围证据确认；四日实收逐单核验是已有正面证据 | 沿用四日证据扩大到本次正式范围，确认补贴口径和异常处理规则，不回退用户实付。确认后版本化更新契约与客户端验收 |
| 实验效果 | 不由接口上线证明 | 客户端保持因素—行动—验证—经验链；D7、D0、新图、门店跟进率分组另按成熟度和干扰因素验证 |

因此本次交付是解除“缺少源证据访问”的阻塞，尚不能启用正式API指标。最小顺序是：源码审阅及隔离PostgreSQL检查 → 经授权发布 → 一次API差异核查及覆盖审计 → 按真实结果决定能支持的验证范围。只有具体缺口确认需要时，才提出采集/回填/历史存储授权；不能预先把整套业务改造塞进本次接口任务。

## 机器可读交接

- [Manifest JSON Schema](pdca-event-manifest.schema.json)
- [Page JSON Schema](pdca-event-page.schema.json)
- [合成响应样例](pdca-event-synthetic-example.json)（无真实订单/客户数据；其中快照ID仅作格式示例，不可请求）
- 生成命令：设置 `PYTHONPATH=apps/api` 并包含仓库根目录后，运行 `python scripts/generate_pdca_snapshot_contract.py`；脚本只使用独立内存SQLite，不连接经营源库。
- [实现与验证记录](../devlog/20260928_refactor_log_Your_Name.md)
