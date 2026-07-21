# dydata command reference

CLI version: `0.1.0`. Schema version: `1.0`.

| Command | Purpose | Agent callable |
| --- | --- | --- |
| `commands` | Discover every supported CLI command and its agent contract. | true |
| `auth.login` | Sign in interactively and store credentials locally. | false |
| `auth.logout` | Remove the locally stored CLI credential. | false |
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

### Output schema

`{"data": {"commands": "Command[]"}}`

### Errors

`INTERNAL_ERROR`

### Examples

`dydata commands --json`

## `auth.login`

Sign in interactively and store credentials locally.

### Parameters

| Name | Required | Type |
| --- | --- | --- |
| `None` | false | `-` |

### Output schema

`{"data": {"authenticated": "boolean"}}`

### Errors

`AUTH_REQUIRED`, `INTERNAL_ERROR`

### Examples

`dydata auth login`

## `auth.logout`

Remove the locally stored CLI credential.

### Parameters

| Name | Required | Type |
| --- | --- | --- |
| `None` | false | `-` |

### Output schema

`{"data": {"authenticated": "boolean"}}`

### Errors

`INTERNAL_ERROR`

### Examples

`dydata auth logout`

## `auth.status`

Report whether a locally stored CLI credential is usable.

### Parameters

| Name | Required | Type |
| --- | --- | --- |
| `--json` | true | `flag` |

### Output schema

`{"data": {"authenticated": "boolean", "expires_at": "datetime"}}`

### Errors

`AUTH_REQUIRED`, `AUTH_EXPIRED`, `INTERNAL_ERROR`

### Examples

`dydata auth status --json`

## `stores.list`

List stores available within the caller's data scope.

### Parameters

| Name | Required | Type |
| --- | --- | --- |
| `--json` | true | `flag` |

### Output schema

`{"data": {"stores": "Store[]"}}`

### Errors

`AUTH_REQUIRED`, `SCOPE_DENIED`, `API_UNAVAILABLE`, `INTERNAL_ERROR`

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

### Output schema

`{"data": {"stores": "FollowUpStats[]", "totals": "FollowUpStats"}}`

### Errors

`AUTH_REQUIRED`, `SCOPE_DENIED`, `INVALID_ARGUMENT`, `API_UNAVAILABLE`, `INTERNAL_ERROR`

### Examples

`dydata clues follow-up-stats`
`dydata clues follow-up-stats --from 2026-07-01 --to 2026-07-07 --store-id store-a --output table`

## `version`

Report the installed CLI and schema versions.

### Parameters

| Name | Required | Type |
| --- | --- | --- |
| `--json` | true | `flag` |

### Output schema

`{"data": {"cli_version": "string", "schema_version": "string"}}`

### Errors

`INTERNAL_ERROR`

### Examples

`dydata version --json`
