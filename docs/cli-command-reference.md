# dydata command reference

CLI version: `0.1.0`. Schema version: `1.0`.

| Command | Purpose | Agent callable |
| --- | --- | --- |
| `commands` | Discover every supported CLI command and its agent contract. | true |
| `auth.login` | Sign in interactively and store credentials locally. | false |
| `auth.logout` | Revoke the refresh family and remove the observed local credential. | false |
| `auth.status` | Report whether a locally stored CLI credential is usable. | true |
| `stores.list` | List stores available within the caller's data scope. | true |
| `clues.follow-up-stats` | Summarize clue follow-up results for authorized stores. | true |
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

Sign in interactively and store credentials locally.

### Parameters

| Name | Required | Type |
| --- | --- | --- |
| `None` | false | `-` |

### Roles

`all`

### Data scope

`none`

### Side effects

Authentication/local: `remote_auth_grant_and_local_credential`. Business data: `none`.

### Risk and confirmation

Risk: `medium`. Confirmation: `interactive`. Agent callable: `false`.

### Sensitive data

`credential`

### Output mode and schema

Mode: `text`.

`{"lines": ["Open: <url>", "Code: <user_code>", "Authorization complete."], "mode": "text"}`

### Errors and exit codes

| Error | Exit code |
| --- | --- |
| `AUTH_REQUIRED` | `3` |
| `AUTH_EXPIRED` | `3` |
| `INVALID_ARGUMENT` | `2` |
| `API_UNAVAILABLE` | `5` |
| `RATE_LIMITED` | `5` |
| `SCHEMA_MISMATCH` | `6` |
| `INTERNAL_ERROR` | `6` |

### Examples

`dydata auth login`

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
