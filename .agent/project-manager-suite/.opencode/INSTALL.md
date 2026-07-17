# Installing Project Manager Suite for OpenCode

> 仓库布局说明：`project-manager-suite` 是源码仓库的**子目录**，不是仓库根。克隆整个仓库后，插件文件的真实路径是 `<克隆目录>/project-manager-suite/.opencode/plugins/project-manager-suite.js`，skills 的真实路径是 `<克隆目录>/project-manager-suite/skills`，下文命令都按这个布局写。

## Prerequisites

- [OpenCode.ai](https://opencode.ai) installed
- Git installed

## Installation Steps

### 1. Clone the repository（克隆整个源码仓库）

```bash
git clone <your-repo-url> ~/.config/opencode/pm-suite-repo
```

### 2. Register the Plugin

Create a symlink（符号链接）so OpenCode discovers the plugin，注意软链源在仓库的 `project-manager-suite/.opencode/plugins/` 子目录下：

```bash
mkdir -p ~/.config/opencode/plugins
rm -f ~/.config/opencode/plugins/project-manager-suite.js
ln -s ~/.config/opencode/pm-suite-repo/project-manager-suite/.opencode/plugins/project-manager-suite.js ~/.config/opencode/plugins/project-manager-suite.js
```

### 3. Symlink Skills

Create a symlink so OpenCode's native skill tool discovers project-manager-suite skills，软链源是仓库的 `project-manager-suite/skills` 子目录：

```bash
mkdir -p ~/.config/opencode/skills
rm -rf ~/.config/opencode/skills/project-manager-suite
ln -s ~/.config/opencode/pm-suite-repo/project-manager-suite/skills ~/.config/opencode/skills/project-manager-suite
```

### 4. Verify（先验证再重启）

只看软链自身无法发现指错目标的悬空软链，必须穿透软链读到真实文件才算通过：

```bash
# 插件文件真实可读；能输出文件头几行即通过
head -n 5 ~/.config/opencode/plugins/project-manager-suite.js

# 穿透软链列出 skills 目录；软链悬空时此命令会直接报错
ls -L ~/.config/opencode/skills/project-manager-suite

# 主入口 SKILL 文件真实可读
head -n 5 ~/.config/opencode/skills/project-manager-suite/ai-project-manager/SKILL.md
```

任一条报 `No such file or directory`，说明软链目标路径写错，回到第 2 / 3 步核对是否遗漏了 `project-manager-suite` 这一级子目录。

### 5. Restart OpenCode

Restart OpenCode. The plugin will automatically inject project manager context.

## Usage

### Loading the Skill

Use OpenCode's native `skill` tool:

```
use skill tool to load project-manager-suite/ai-project-manager
```

### Project Skills

Create project-specific skills in `.opencode/skills/` within your project.

**Skill Priority:** Project skills > Personal skills > Plugin skills

## Tool Mapping

When skills reference Claude Code tools:
- `TodoWrite` → `update_plan`
- `Task` with subagents → `@mention` syntax
- `Skill` tool → OpenCode's native `skill` tool
- File operations → your native tools

## Updating

```bash
cd ~/.config/opencode/pm-suite-repo && git pull
```

## Troubleshooting

### Plugin not loading

1. Check the plugin file is readable through the symlink: `head -n 5 ~/.config/opencode/plugins/project-manager-suite.js`
2. Check source exists: `ls ~/.config/opencode/pm-suite-repo/project-manager-suite/.opencode/plugins/project-manager-suite.js`
3. Check OpenCode logs for errors

### Skills not found

1. Check the skills symlink resolves: `ls -L ~/.config/opencode/skills/project-manager-suite`
2. Verify it points to: `~/.config/opencode/pm-suite-repo/project-manager-suite/skills`
3. Use `skill` tool to list what's discovered

## Uninstalling

```bash
rm ~/.config/opencode/plugins/project-manager-suite.js
rm -rf ~/.config/opencode/skills/project-manager-suite
rm -rf ~/.config/opencode/pm-suite-repo
```
