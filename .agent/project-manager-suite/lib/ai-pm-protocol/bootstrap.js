/**
 * Traceability:
 * Rule sources:
 * - skills/00-01-ai-project-manager/SKILL.md
 * Consumed by:
 * - lib/bootstrap/index.js
 * - hooks/session-start
 * - .opencode/plugins/project-manager-suite.js
 */
const bootstrapPolicy = {
    primarySkill: 'ai-project-manager',
    primarySkillPath: 'skills/00-01-ai-project-manager/SKILL.md',
    defaultEntryRole: 'project-domain-first-entry',
    sharedGenerationGoal: 'hooks_and_plugins_share_same_core_bootstrap_content',
    channels: {
        hooks: {
            trigger: 'SessionStart',
            events: ['startup', 'resume', 'clear', 'compact'],
            wrapper: 'json_additional_context'
        },
        opencode: {
            trigger: 'experimental.chat.system.transform',
            wrapper: 'system_prompt_transform',
            includeToolMapping: true
        },
        codex: {
            trigger: 'skill_discovery_only',
            wrapper: null,
            includeToolMapping: false
        }
    }
};

export { bootstrapPolicy };
