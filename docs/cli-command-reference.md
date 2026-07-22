# dydata command reference

CLI version: `0.3.0`. Schema version: `1.1`.

| Command | Purpose | Agent callable |
| --- | --- | --- |
| `commands` | Discover every supported CLI command and its agent contract. | true |
| `auth.login` | Let a human sign in through secure terminal input, with an explicit browser fallback. | false |
| `auth.logout` | Revoke the refresh family and remove the observed local credential. | false |
| `auth.status` | Report whether a locally stored CLI credential is usable. | true |
| `stores.list` | List stores available within the caller's data scope. | true |
| `clues.follow-up-stats` | Summarize clue follow-up results for authorized stores. | true |
| `agent.doctor` | Diagnose the fixed Agent manifest, MCP metadata, and local authorization state. | true |
| `version` | Report the installed CLI and schema versions. | true |

## `commands`

Discover every supported CLI command and its agent contract.

### Parameters

| Name | Required | Type |
| --- | --- | --- |
| `--json` | true | `flag` |

### Roles

`all`

### Data scope

`none`

### Side effects

Authentication/local: `none`. Business data: `none`.

### Risk and confirmation

Risk: `low`. Confirmation: `none`. Agent callable: `true`.

### Sensitive data

`none`

### Output mode and schema

Mode: `json`.

`{"data": {"commands": "Command[]"}}`

### Errors and exit codes

| Error | Exit code |
| --- | --- |
| `INTERNAL_ERROR` | `6` |

### Examples

`dydata commands --json`

## `auth.login`

Let a human sign in through secure terminal input, with an explicit browser fallback.

### Parameters

| Name | Required | Type |
| --- | --- | --- |
| `--browser` | false | `flag` |

### Roles

`all`

### Data scope

`none`

### Side effects

Authentication/local: `remote_auth_grant_and_local_credential`. Business data: `none`.

### Risk and confirmation

Risk: `medium`. Confirmation: `human_secure_tty_or_browser`. Agent callable: `false`.

### Human handoff

An Agent may launch this command only after an explicit user request and must hand credential input to the user; it is not autonomously agent-callable.

`{"agent_may_launch": true, "agent_must_not_supply_credentials": true, "browser_fallback": "dydata auth login --browser", "default_mode": "secure_terminal", "requires_explicit_user_request": true, "requires_user_input": true}`

### Sensitive data

`human_entered_credential`

### Output mode and schema

Mode: `text`.

`{"mode": "text", "variants": {"browser": ["Open: <url>", "Code: <user_code>", "Authorization complete."], "existing_credential": ["A local CLI credential already exists. Run `dydata auth logout` before signing in as another account."], "terminal": ["Signed in as: <username>", "Role: <role>", "Store scope: <scope>", "Authorization complete."]}}`

### Errors and exit codes

| Error | Exit code |
| --- | --- |
| `INTERACTIVE_REQUIRED` | `2` |
| `AUTH_FAILED` | `3` |
| `AUTH_REQUIRED` | `3` |
| `AUTH_EXPIRED` | `3` |
| `INVALID_ARGUMENT` | `2` |
| `API_UNAVAILABLE` | `5` |
| `RATE_LIMITED` | `5` |
| `SCHEMA_MISMATCH` | `6` |
| `INTERNAL_ERROR` | `6` |

### Examples

`dydata auth login`
`dydata auth login --browser`

## `auth.logout`

Revoke the refresh family and remove the observed local credential.

### Parameters

| Name | Required | Type |
| --- | --- | --- |
| `None` | false | `-` |

### Roles

`all`

### Data scope

`none`

### Side effects

Authentication/local: `remote_auth_revoke_and_local_credential`. Business data: `none`.

### Risk and confirmation

Risk: `low`. Confirmation: `interactive`. Agent callable: `false`.

### Sensitive data

`credential`

### Output mode and schema

Mode: `text`.

`{"lines": ["Logged out."], "mode": "text"}`

### Errors and exit codes

| Error | Exit code |
| --- | --- |
| `API_UNAVAILABLE` | `5` |
| `RATE_LIMITED` | `5` |
| `SCHEMA_MISMATCH` | `6` |
| `INTERNAL_ERROR` | `6` |

### Examples

`dydata auth logout`

## `auth.status`

Report whether a locally stored CLI credential is usable.

### Parameters

| Name | Required | Type |
| --- | --- | --- |
| `--json` | true | `flag` |

### Roles

`all`

### Data scope

`current_identity`

### Side effects

Authentication/local: `auth_refresh_possible`. Business data: `none`.

### Risk and confirmation

Risk: `low`. Confirmation: `none`. Agent callable: `true`.

### Sensitive data

`credential_metadata`

### Output mode and schema

Mode: `json`.

`{"data": {"authenticated": "boolean", "expires_at": "datetime"}}`

### Errors and exit codes

| Error | Exit code |
| --- | --- |
| `AUTH_REQUIRED` | `3` |
| `AUTH_EXPIRED` | `3` |
| `API_UNAVAILABLE` | `5` |
| `RATE_LIMITED` | `5` |
| `SCHEMA_MISMATCH` | `6` |
| `INTERNAL_ERROR` | `6` |

### Examples

`dydata auth status --json`

## `stores.list`

List stores available within the caller's data scope.

### Parameters

| Name | Required | Type |
| --- | --- | --- |
| `--json` | true | `flag` |

### Roles

`store`, `admin`, `highest_admin`

### Data scope

`authorized_stores`

### Side effects

Authentication/local: `auth_refresh_possible`. Business data: `none`.

### Risk and confirmation

Risk: `low`. Confirmation: `none`. Agent callable: `true`.

### Sensitive data

`store_identity`

### Output mode and schema

Mode: `json`.

`{"data": {"stores": "Store[]"}}`

### Errors and exit codes

| Error | Exit code |
| --- | --- |
| `AUTH_REQUIRED` | `3` |
| `AUTH_EXPIRED` | `3` |
| `SCOPE_DENIED` | `4` |
| `API_UNAVAILABLE` | `5` |
| `RATE_LIMITED` | `5` |
| `SCHEMA_MISMATCH` | `6` |
| `INTERNAL_ERROR` | `6` |

### Examples

`dydata stores list --json`

## `clues.follow-up-stats`

Summarize clue follow-up results for authorized stores.

### Parameters

| Name | Required | Type |
| --- | --- | --- |
| `--from` | false | `YYYY-MM-DD` |
| `--to` | false | `YYYY-MM-DD` |
| `--store-id` | false | `string` |
| `--output` | false | `json|table` |

### Roles

`store`, `admin`, `highest_admin`

### Data scope

`authorized_stores`

### Side effects

Authentication/local: `auth_refresh_possible`. Business data: `none`.

### Risk and confirmation

Risk: `low`. Confirmation: `none`. Agent callable: `true`.

### Sensitive data

`store_metrics`

### Output mode and schema

Mode: `json_or_table`.

`{"data": {"stores": "FollowUpStats[]", "totals": "FollowUpStats"}}`

### Errors and exit codes

| Error | Exit code |
| --- | --- |
| `AUTH_REQUIRED` | `3` |
| `AUTH_EXPIRED` | `3` |
| `SCOPE_DENIED` | `4` |
| `INVALID_ARGUMENT` | `2` |
| `API_UNAVAILABLE` | `5` |
| `RATE_LIMITED` | `5` |
| `SCHEMA_MISMATCH` | `6` |
| `INTERNAL_ERROR` | `6` |

### Examples

`dydata clues follow-up-stats`
`dydata clues follow-up-stats --from 2026-07-01 --to 2026-07-07 --store-id store-a --output table`

## `agent.doctor`

Diagnose the fixed Agent manifest, MCP metadata, and local authorization state.

### Parameters

| Name | Required | Type |
| --- | --- | --- |
| `--json` | true | `flag` |

### Roles

`all`

### Data scope

`current_identity_and_authorized_stores`

### Side effects

Authentication/local: `auth_refresh_possible`. Business data: `none`.

### Risk and confirmation

Risk: `low`. Confirmation: `none`. Agent callable: `true`.

### Sensitive data

`credential_metadata_and_store_identity`

### Output mode and schema

Mode: `json`.

`{"data": {"checks": "DiagnosticCheck[]", "credential": "CredentialDiagnostic", "next_action": "string"}}`

### Errors and exit codes

| Error | Exit code |
| --- | --- |
| `AUTH_EXPIRED` | `3` |
| `API_UNAVAILABLE` | `5` |
| `RATE_LIMITED` | `5` |
| `SCHEMA_MISMATCH` | `6` |
| `INTERNAL_ERROR` | `6` |

### Examples

`dydata agent doctor --json`

## `version`

Report the installed CLI and schema versions.

### Parameters

| Name | Required | Type |
| --- | --- | --- |
| `--json` | true | `flag` |

### Roles

`all`

### Data scope

`none`

### Side effects

Authentication/local: `none`. Business data: `none`.

### Risk and confirmation

Risk: `low`. Confirmation: `none`. Agent callable: `true`.

### Sensitive data

`none`

### Output mode and schema

Mode: `json`.

`{"data": {"cli_version": "string", "schema_version": "string"}}`

### Errors and exit codes

| Error | Exit code |
| --- | --- |
| `INTERNAL_ERROR` | `6` |

### Examples

`dydata version --json`
