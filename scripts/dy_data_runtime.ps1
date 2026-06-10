$ErrorActionPreference = "Stop"

function Get-DyDataConfigPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    if ($env:DY_DATA_CONFIG) {
        return [Environment]::ExpandEnvironmentVariables($env:DY_DATA_CONFIG)
    }

    $localConfig = Join-Path $Root "config.local.json"
    if (Test-Path -LiteralPath $localConfig) {
        return $localConfig
    }

    $sharedConfig = Join-Path $Root "config.json"
    if (Test-Path -LiteralPath $sharedConfig) {
        return $sharedConfig
    }

    return $null
}

function Get-DyDataConfig {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    $configPath = Get-DyDataConfigPath -Root $Root
    if (-not $configPath -or -not (Test-Path -LiteralPath $configPath)) {
        return $null
    }

    try {
        return Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "Invalid config JSON: $configPath. $($_.Exception.Message)"
    }
}

function Get-DyDataConfigValue {
    param(
        [Parameter(Mandatory = $false)]
        $Config,

        [Parameter(Mandatory = $true)]
        [string[]]$Keys
    )

    $value = $Config
    foreach ($key in $Keys) {
        if ($null -eq $value) {
            return $null
        }
        $property = $value.PSObject.Properties[$key]
        if ($null -eq $property) {
            return $null
        }
        $value = $property.Value
    }

    if ($value -is [string] -and -not $value.Trim()) {
        return $null
    }
    return $value
}

function Resolve-DyDataCommandPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,

        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $text = [Environment]::ExpandEnvironmentVariables($Value.Trim())
    if ($text -eq "python" -or $text -eq "py") {
        return $text
    }
    if ($text.StartsWith("~\")) {
        return (Join-Path $env:USERPROFILE $text.Substring(2))
    }
    if ([System.IO.Path]::IsPathRooted($text)) {
        return $text
    }
    return (Join-Path $Root $text)
}

function Resolve-DyDataPython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    if ($env:DY_DATA_PYTHON_EXE) {
        return Resolve-DyDataCommandPath -Root $Root -Value $env:DY_DATA_PYTHON_EXE
    }

    $config = Get-DyDataConfig -Root $Root
    $configuredPython = Get-DyDataConfigValue -Config $config -Keys @("paths", "python_exe")
    if ($configuredPython) {
        return Resolve-DyDataCommandPath -Root $Root -Value ([string]$configuredPython)
    }

    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }

    return "python"
}

function Add-DyDataPythonPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    $separator = [System.IO.Path]::PathSeparator
    $parts = @()
    if ($env:PYTHONPATH) {
        $parts = $env:PYTHONPATH -split [regex]::Escape([string]$separator)
    }

    $hasRoot = $false
    foreach ($part in $parts) {
        if ($part -ieq $Root) {
            $hasRoot = $true
            break
        }
    }

    if (-not $hasRoot) {
        $env:PYTHONPATH = (@($Root) + $parts | Where-Object { $_ }) -join $separator
    }
}

function Initialize-DyDataRuntime {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    $resolvedRoot = (Resolve-Path -LiteralPath $Root).Path
    $configPath = Get-DyDataConfigPath -Root $resolvedRoot
    if ($configPath -and -not $env:DY_DATA_CONFIG) {
        $env:DY_DATA_CONFIG = $configPath
    }

    $python = Resolve-DyDataPython -Root $resolvedRoot
    $env:DY_DATA_PYTHON_EXE = $python
    Add-DyDataPythonPath -Root $resolvedRoot

    return $python
}
