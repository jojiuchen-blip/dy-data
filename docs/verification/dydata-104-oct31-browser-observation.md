# DYDATA-104：浏览器真实健康观察与恢复确认

本补丁承接 [DYDATA-104](https://linear.app/keith-lim/issue/DYDATA-104) 既有生产可靠性范围。主线程实际通过管理员运维入口重启后，Chrome与容器健康恢复，但原命令保留 `replacement_heartbeat_timeout`：browser不连接数据库，既有代码却依赖不存在的browser心跳生产者。此处只修正后续观察/确认链，不能改写原失败审计或声称新代码已上线。

## 实现与边界

- OpsAgent使用已有受限socket，只对唯一Compose项目/service=browser增加固定只读inspect。lookup及inspect的完整ID/labels分别核对；无通用路径、任意目标、shell或新增Docker写动作。只返回启动/健康选定字段，不输出inspect环境、健康输出或数据库异常内容。
- `StartedAt`按UTC解析，保留原纳秒文本以区分实际启动身份；拒绝未设置、非法及未来时点。健康结果必须有本次启动后、90秒内的完成检查；只有healthy的新启动可确认browser重启，starting/unhealthy/旧启动不能确认。worker继续原自报心跳路径。
- browser仍不获得数据库凭据或socket。现有OpsAgent最小数据库角色在固定内部观察子进程中记录`component_heartbeats`，标明`observer=ops_agent/source=docker_inspect`；CPU/RSS/队列/当前任务未知保持空，不把容器健康解释成无导出活动。
- 空闲观察每30秒最多一次，重启等待即时观察。marker、导出任务、所有browser实例的活动声明都继续保护，较新的观察心跳不能掩盖旧实例的活动；不会因TTL或观察自动清除残留活动。唯一目标、命令lease/epoch、幂等及300秒冷却保持，browser串行观察与退出回收预算计入租约，worker租约不变。

## 时间、事务与进程生命周期

`main.py`只接受固定内部`--observe-browser-once <monotonic deadline>`，不接受任意模块、动作或目标。父进程统一限制启动、连接池/连接建立、首查询、HTTP header/body和提交等待；stdout最多4KiB。只有及时退出0并通过字段、真实启动与健康时点检查的答复才可确认。超时、非零、超量、坏字段或提前输出后继续运行均失败；父进程kill并wait回收，不能留下后台线程或子进程继续持久化。kill后的回收另有最多1秒保留预算，回收失败为致命错误。

子进程自行建立新池，避免共享池排队；继承原Ops最小角色。PG读写每条SQL下推剩余预算，statement/lock最大3秒/1秒且保留既有更小限制；flush后在剩余预算内执行`SET CONSTRAINTS ALL IMMEDIATE`，再封闭后续SQL/flush提交。socket timeout和内层事务检查本身不是连接/慢滴流的硬墙钟证明，固定子进程边界不可移除。普通遥测提交可能已发生而答复丢失时，只能继续显示真实观察，父进程仍不确认命令成功。

## 验证记录

- 先红后绿：初始观察专项24例在旧代码20失败/4通过，保留原收据；原browser成功fixture随后改成明确真实观察，原worker/命令保护断言未弱化。
- 最终固定应用与测试提交`cc5dc2a19378700b08155e49ef122e49a10ceeba`：观察专项、旧Ops、worker资源和Compose四文件完整组合**124通过、0失败/跳过，178.09秒**。其中观察58、旧Ops27、资源/Compose39；观察文件包含真实PG预算3例。较早内层版本另取得110通过，不冒充最终同轮结果。
- 固定子进程专项独立10通过，且已纳入最终124项：合法退出、提前合法输出后迟写被kill、超量/非零/坏数据、真实占满连接池、真实HTTP每10ms滴流、空闲观察频率。独立复核的HTTP与真实PG占满池故障，均在2秒返回失败且子进程已回收，无迟到标记。
- 独立PG预算最终3通过、0失败/跳过，1.34秒，最终完整组合亦执行通过：行锁等待不推进心跳、延迟触发器在剩余SQL预算内取消并回滚、原80ms/30ms更小限制保留。只创建随机自有schema的JobRun/Heartbeat两表，清理自身schema；不是生产角色/部署验收。
- 本地真实Docker Unix socket只读观察通过：恰好GET lookup和GET固定inspect，取得真实healthy及同次启动Health；隔离测试容器经精确标签核对后清理。未操作其他容器或生产。

私有收据保留在工作树忽略目录，未提交凭据、真实业务标识或完整inspect。没有新增DDL、HTTP路由或权限授予；运行手册的固定只读观察说明由主线程统一回捞。生产部署、真实最小角色环境及月末完整采集仍须主线程独立核验；本补丁不证明抖音登录有效或月结证据完整。

最终私有JUnit：`browser-observer-verified.xml`，SHA-256 `35ed8e99f08485c123a1d304fa9a8be1d1de4e292573861f53ad4c1c46e4882d`。PG独立JUnit SHA-256 `05ee61c438232ae573af2a4cba950efcae7d0c7600ad3c05a718fa7fbc633c71`。独立Docker只读收据SHA-256 `0d004b499921ce0aeb68f808fb418fce9e53151e193dcb427bc3d9918b4b269c`。应用文件SHA-256为`main.py c3378dee8dd43c8f87e24131e8c0f26c97dfad6be8ac51ff1f033c2b085d7963`、`docker_api.py 7d7f9c5d9afbebc3b56ed73558c677974fd7b72be13186fbdb8eb6b406874140`。

保留验证中的原失败：首轮完整组合123通过/1失败，原因是HTTP故障子进程在限时内尚未完成较重测试模块导入，未进入accept。仅将故障程序改为直接显式替换连接构造器、移除测试mock框架冷启动开销，仍要求进入真实HTTP、2秒墙钟、10秒滴流、退出回收和无迟写；单例1通过后完整124项复跑通过，未改应用源码或放宽断言。更早极小PG fixture在80ms限时下建表超时也保留；仅将fixture建表阶段设3秒，运行时80ms/30ms断言保持。
