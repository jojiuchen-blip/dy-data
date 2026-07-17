/**
 * Traceability:
 * Rule sources:
 * - skills/00-01-ai-project-manager/references/core/routing.md
 * - skills/00-01-ai-project-manager/references/core/global-files-protocol.md
 * Consumed by:
 * - tools/generate-host-rules.mjs
 * - tools/bootstrap-host.mjs
 */
const rulesSyncPolicy = {
    sourceDir: 'skills/00-01-ai-project-manager/references/rules',
    targetDir: 'docs/rules',
    strategy: 'create_missing_only',
    allowForceOverwrite: true,
    supportsDryRun: true,
    generatedFileHeader: true,
    runtimePriority: ['host_rules', 'suite_defaults'],
    integration: {
        existingTool: 'project-manager-suite/tools/generate-host-rules.mjs',
        shouldBeReusedByBootstrapHost: true
    }
};

export { rulesSyncPolicy };
