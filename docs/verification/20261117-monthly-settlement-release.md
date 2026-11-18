# 2026-11-17 月度结算发布记录

**1.7.0-rc.1 · 已部署待业务验收。** 2026-11-17 18:03:14（Asia/Shanghai）完成腾讯云生产切换。此编号为发布记录中的候选版本，未创建 Git tag。

## 源码与验证

- [PR #80](https://github.com/jojiuchen-blip/dy-data/pull/80) 合入 `main` 的完整提交为 `678429d6c433b253f55c23334e11fcbbcaa5a2ea`。该提交为实际部署源码。前一生产版本为 `81877460c7f08fefa1f096534636770c5155ba46`。
- [部署前 CI/CD 44051198156](https://github.com/jojiuchen-blip/dy-data/actions/runs/44051198156) 的 PR 提交为 `65e5692b89a16c29d34c8588188e416faf054add`，实际 checkout 为 `263f770c7d4de3e03948cb74b827264fd03a432b`。上述两个提交与实际部署提交的代码树都是 `9f0a9f8f92c6473658319b3db4df67b351f496f7`。
- 全仓 pytest 5,715 项通过、565 项按配置跳过。强制门禁另行执行静态发布 PostgreSQL 126 项、财务与月末 PostgreSQL 395 项、财务 Chromium 39 项，均无失败或跳过。前端、API、Worker、Browser 与 Web 镜像构建通过。旧候选的浏览器测试失败已复现并修正，测试夹具按实际 API 返回规范化的筛选，并断言导出冲突的 HTTP 409。[旧候选 CI](https://github.com/jojiuchen-blip/dy-data/actions/runs/44041659225)
- Git 归档 14,309,778 字节，SHA-256 为 `23c68c92d79e86b2d865cdd296b3ac1f4eb8ea8f5e67b3a5af05b6714f9530d9`。通过现行源码校验和 staging 后，按候选 Dockerfile、`requirements.txt`、`apps/web/package-lock.json` 及生产 Compose 在目标主机重新构建。

## 部署与实际产物

部署运行标识为 `pr80-678429d6c433b253f55c23334e11fcbbcaa5a2ea-20261117T095102400493Z`，脚本退出码为 0。使用现行腾讯部署流程的生产互斥锁、归档散列校验、数据库备份、迁移、发布预热和冒烟，在锁内核对前一运行 SHA。主线自动推送部署关闭，[自动 workflow 回执](https://github.com/jojiuchen-blip/dy-data/actions/runs/44059246637) 为 skipped。

切换前可用磁盘 62,024,638,464 字节（32%），高于当次备份门槛 14,315,011,823 字节。新整库备份 `pre-migrate-20261117T095141Z.dump` 为 2,443,447,115 字节，权限 0600，`pg_restore --list` 核验通过，无待完成归档。尚无本次全库恢复演练证据。

数据库从 `20261105_0067` 升到 `20261117_0068`。独立回读确认三张月结相关表、金额来源摘要字段、三组发布来源计数及触发器；未解决快照迁移异常为 0。五模块各有一份成功的在用发布版本。

| 实际运行服务 | Docker 镜像 ID |
|---|---|
| API | `sha256:7ea3d6321b6b40dbb9defbbddce162ca53e3a15370f7398e341af06fa78b46b1` |
| Worker / publication-worker | `sha256:15f23b9d7099d824fd8037e840b840af82c19b59e92ef3e730011385a3e0c1ae` |
| Web | `sha256:17d54fadcc28cdbfe3ffb616eb9902f463a0d87bc6f8e3051559f7491c0cea63` |
| Browser | `sha256:c0755b0cfcdb3638ce1fa32ac12b709c06020d91828be46673767be9b12f51af` |
| Ops Agent | `sha256:069c1a3148d1e0f6c546d8e1b79ffaf6a10d32ae6d68873c4bb26d4be0741c7f` |
| Proxy | `sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10` |
| PostgreSQL | `sha256:1b1689b20d16a014a3d195653381cf2caa75a41a92d93b255a9d6ea29fd353aa` |

上线后八服务运行正常。源目录 26 个抽查文件、API、Worker 和 publisher 各 20 个运行文件与目标源码一致。公网首页返回 200，Web 主 JS 的 SHA-256 与容器内一致。匿名鉴权返回 401，生产 Agent manifest 返回 200，Worker 调度器进程及数据库连通性符合预期。

## 账务与回退

- 月结模式和无人值守确认的生产开关均为 `false`，日常共享采集的调度入口和开关已按现有配置核验。启用月结前仍需真实整月采集、资源及身份覆盖证据。
- 上线后在用正式账单为 8 月 620 份、9 月 593 份、10 月 0 份。新发布为已有 8、9 月账单版本记录首次可见时间。无额外历史金额修复、首批历史确认或 10 月正式出账。10 月身份缺证、采集登录及真实导入导出验收继续跟踪。[DYDATA-104](https://linear.app/keith-lim/issue/DYDATA-104)
- 回退使用上一生产 SHA 和受控清单 `images-20261117T095104Z.manifest` 内的 8 个不可变镜像，已逐一读回镜像标签及 ID。迁移为增加表、列和来源计数触发器，应用回退前应复核上线后的有效账务与发布版本。数据库恢复需独立评估。
