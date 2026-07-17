# 开发日志规则

## 目录边界

- 可提交的开发过程日志写入 `docs/devlog/`，该目录由 `project-profile.md` 的“最近状态入口”配置。
- `/logs/` 只保存本地运行日志并保持 Git 忽略；不得把可追踪的项目状态写入该目录。
- 日志工具的默认回退目录仍为 `logs/`，但本项目必须解析到已配置的 `docs/devlog/`。

## 写入方式

- 使用安装态套包的 `project-devlog` 和 `devlog-sync.mjs`，不要自由创建另一套命名。
- 文件按 `YYYYMMDD_refactor_log_<执行人>.md` 命名；执行人默认取 Git `user.name`。
- 同一天同一执行人只保留一份日志；后续内容追加“补充更新”，不得覆盖既有记录。
- 记录真实目标、动作、结果、涉及文件、验证、结论和下一步；未完成或未验证内容必须明确标注。

## 状态同步

- 日志是执行证据，不是需求、优先级或 issue 状态权威。
- issue 状态与验收回写 Linear，当前阶段回写 `project-profile.md`，当前执行摘要回写 `docs/plans/execution-plan.md`。
- 出现“建议升级为规则”等信号时，同步更新 `docs/retrospectives/rule-candidates-YYYYMM.md`；正式规则仍需评审后进入对应权威文件。

## 收口检查

- 路径是否为 `docs/devlog/`，文件是否可被 Git 跟踪。
- 内容是否与 Linear、执行计划和实际验证一致。
- 是否错误包含密钥、Cookie、数据库 URL、真实生产标识或个人数据。
- 是否把运行日志、调试噪声或未确认推断写成项目结论。
