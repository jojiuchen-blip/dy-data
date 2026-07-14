# Installing Project Manager Suite for Codex

通过 symlink（符号链接，指向另一个目录的快捷方式）把 skills 挂载到 Codex 的技能目录，实现自动发现。

> 仓库布局说明：`project-manager-suite` 是源码仓库的**子目录**，不是仓库根。克隆整个仓库后，skills 的真实路径是 `<克隆目录>/project-manager-suite/skills`，下文命令都按这个布局写。

## Prerequisites

- Git

## Installation

1. **Clone the repository（克隆整个源码仓库）:**
   ```bash
   git clone <your-repo-url> ~/.codex/pm-suite-repo
   ```

2. **Create the skills symlink（注意软链源是仓库内的 `project-manager-suite/skills` 子目录）:**
   ```bash
   mkdir -p ~/.agents/skills
   ln -s ~/.codex/pm-suite-repo/project-manager-suite/skills ~/.agents/skills/project-manager-suite
   ```

   **Windows (PowerShell):**
   ```powershell
   New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.agents\skills"
   cmd /c mklink /J "$env:USERPROFILE\.agents\skills\project-manager-suite" "$env:USERPROFILE\.codex\pm-suite-repo\project-manager-suite\skills"
   ```

3. **Restart Codex** (quit and relaunch the CLI) to discover the skills.

## Verify

只看软链自身（`ls -la`）无法发现指错目标的悬空软链，必须穿透软链读到真实文件才算通过：

```bash
# 穿透软链列出目标目录内容；软链悬空时此命令会直接报错
ls -L ~/.agents/skills/project-manager-suite

# 进一步确认主入口 SKILL 文件真实可读；能输出文件头几行即通过
head -n 5 ~/.agents/skills/project-manager-suite/ai-project-manager/SKILL.md
```

两条命令都成功（列出 `ai-project-manager` 等 skill 目录、能读到 SKILL.md 内容）即安装成功；任一条报 `No such file or directory`，说明软链目标路径写错，回到第 2 步核对 `project-manager-suite/skills` 这一级子目录是否遗漏。

## Tool Mapping

When skills reference Claude Code tools, substitute Codex equivalents:
- `TodoWrite` → `update_plan`
- `Task` with subagents → Codex subagent syntax
- `Skill` tool → Codex native skill tool
- `Read`, `Write`, `Edit`, `Bash` → Native tools

## Updating

```bash
cd ~/.codex/pm-suite-repo && git pull
```

Skills update instantly through the symlink.

## Uninstalling

```bash
rm ~/.agents/skills/project-manager-suite
```

Optionally delete the clone: `rm -rf ~/.codex/pm-suite-repo`.
