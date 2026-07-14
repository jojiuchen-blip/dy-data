const FIELD_LEVELS = {
    REQUIRED: 'required',
    OPTIONAL: 'optional',
    INFERRED: 'inferred',
    FORBIDDEN: 'forbidden'
};

const FIELD_SOURCES = {
    USER_CONFIRMED: 'user_confirmed',
    SYSTEM_INFERRED: 'system_inferred',
    PM_WRITTEN: 'pm_written'
};

const FILE_ROLE_IDS = {
    RULES: 'global_rules',
    PROFILE: 'project_profile',
    PLAN: 'execution_plan',
    DEVLOG: 'project_devlog',
    LINK_INDEX: 'project_link_index'
};

const STAGE_IDS = {
    S0: 'S0',
    S0_5: 'S0.5',
    S1: 'S1',
    S2: 'S2',
    S3: 'S3',
    S4: 'S4',
    S5: 'S5',
    S6: 'S6',
    S7: 'S7'
};

export { FIELD_LEVELS, FIELD_SOURCES, FILE_ROLE_IDS, STAGE_IDS };
