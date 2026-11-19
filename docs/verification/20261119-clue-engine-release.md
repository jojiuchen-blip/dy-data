# 2026-11-19 商品级线索引擎生产发布

**1.7.0-rc.3 · 已部署，待业务试点验收。** 2026-11-19 16:17:00（Asia/Shanghai）完成腾讯轻量云 Ubuntu + Docker 的生产切换。标签尚未创建。[DYDATA-115](https://linear.app/keith-lim/issue/DYDATA-115)

## 源码与验证

- [PR #82](https://github.com/jojiuchen-blip/dy-data/pull/82) 于 15:22:25 合入 `main`。线上源码为 `ae40d26efe86c98b8498b7a2aca03d667d72c9f0`，上一生产源码为 `fbeec663e0baea2dd19b0732ee50e296bed07c67`。
- CI 的 PR 提交为 `0e5dabcf3ff7c2302f1eb635b7d15ee749c69e56`，实际检出的合并提交为 `7961ecb8d01470593bb66bfde8efddde62907845`。合入主线后读回的代码树 `8b169c0ba4d30289e4e0864650d5f79d845ad3aa` 和 CI 检出的代码树相同。[合并验证](https://github.com/jojiuchen-blip/dy-data/actions/runs/44469724266)
- 全仓 pytest 6,046 项通过、618 项跳过。独立门禁通过静态看板 PostgreSQL 144 项、财务与月结 PostgreSQL 466 项以及商品和门店 Chromium 24 项。前端、Nginx 导出和所有镜像构建检查通过。
- 35 项隔离 PostgreSQL 回归验证真实生产迁移起点、已有线索、店铺用户和月结销售名称证据。应用功能和两看板指标对账见[研发验收记录](dydata-115-verification.md)。
- Git 归档 14,531,145 字节，SHA-256 为 `755c8f21cc999bf20257005a7cab32168a32973cc5518dc55f3e056c974ee20d`。服务器校验归档后，按本次源码、依赖锁、Dockerfile 和生产 Compose 构建镜像。

## 生产切换

首轮运行 `pr82-ae40d26efe86c98b8498b7a2aca03d667d72c9f0-20261119T073450Z` 通过备份并将数据库从 `20261118_0069` 升至 `20261119_0071`。榜单预热超过 240 秒后流程停止，旧 API 和业务 Worker 继续服务，发布进程恢复上一镜像。

第二轮运行 `pr82-ae40d26efe86c98b8498b7a2aca03d667d72c9f0-20261119T075439Z` 使用相同源码，将本次单模块预热等待调整到 600 秒。榜单约 6 分 43 秒完成，线索概览及其余模块就绪后切换应用。脚本退出码为 0。

| 实际运行服务 | Docker 镜像 ID | 核验 |
| --- | --- | --- |
| API | `sha256:5a01cfe0dcf2a13b55af7fa00348d0b68cc11dfffd5d006efc3bcbf191ee2600` | 健康 |
| Worker | `sha256:bdc1fbabc5224f1b1154f3c24a609ca4310bb89935dc4ddc97bfb3db34cce7ca` | 健康 |
| publication-worker | `sha256:bdc1fbabc5224f1b1154f3c24a609ca4310bb89935dc4ddc97bfb3db34cce7ca` | 健康 |
| Web | `sha256:7bca5842abe47a5a3728957812b04c626ebf8bdd61adfb91c282a34fa9a18da6` | 公网冒烟通过 |
| Browser | `sha256:8a0281047d6197a9b84ecc083339238d30eec89b711aeb0293ab695242b753fc` | 健康 |
| Ops Agent | `sha256:7e417b5f7fb39d907ad98368c31a4cf44788e53b6149dbf81ef93a5574a9859d` | 健康 |
| Proxy | `sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10` | 公网冒烟通过 |
| PostgreSQL | `sha256:1b1689b20d16a014a3d195653381cf2caa75a41a92d93b255a9d6ea29fd353aa` | 健康 |

公网首页返回 200，主 JS 与 Web 容器内文件的 SHA-256 一致。匿名鉴权、线索概览和商品流转管理接口返回 401，生产 Agent manifest 返回 200。API、Worker 和 publisher 的线索源码与部署目录抽查一致。Worker 运行期及数据库连通检查通过。

## 数据库、开关与回退

- 生产保留 `20261118_0069` 月结销售名称证据，依次追加商品流转 `20261119_0070` 与看板 `20261119_0071`。生产读回 `20261119_0071`，未解决快照迁移异常为 0，月结销售名称列仍为 JSONB。
- 两张看板的最新发布均成功。线索概览、抖音指标看板分别使用 `clue-task-v3`、`clue-task-v1`。销售、结算、财务的在用发布均成功。
- 只读查询显示已配置商品 0、已开启 0、曾开启 0、已授权共享规则维护人 0。生产月结为开启状态，自动确认关闭。正式试点需业务负责人确认商品 ID 与已发布名单，再明确授权开启。
- 首轮在执行迁移前校验空闲空间 55,644,319,744 字节。迁移前备份 `pre-migrate-20261119T074027Z.dump` 为 2,469,922,976 字节。第二轮备份 `pre-migrate-20261119T075504Z.dump` 为 2,470,037,065 字节，包含已迁移结构。两份权限均为 0600，`pg_restore --list` 通过。备份回执覆盖归档目录校验。
- 应用回退目标为 `fbeec663e0baea2dd19b0732ee50e296bed07c67`。`images-20261119T075453Z.manifest` 中八个镜像别名均与对应不可变镜像 ID 一致。应用回退前需复核新配置、跟进与看板数据的读取兼容性。数据库恢复依运行手册单独评估。
