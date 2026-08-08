[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet(
        "bootstrap", "lint", "test", "test-all", "test-contract",
        "test-security", "test-coverage", "audit", "ci"
    )]
    [string]$Target = "ci"
)

$ErrorActionPreference = "Stop"

$allGroups = @("run", "--all-packages", "--all-groups", "--locked")
$ruffPaths = @(
    "apps", "packages", "mcp-servers", "domain-packs", "scripts", "tests", "web"
)
$mypySources = @(
    "apps/api/src", "apps/mcp-gateway/src", "apps/worker/src",
    "mcp-servers/knowledge/src", "mcp-servers/ticket/src",
    "packages/agent-runtime/src", "packages/application/src",
    "packages/context/src", "packages/domain/src", "packages/graph/src",
    "packages/model-gateway/src", "packages/persistence/src",
    "packages/policy/src", "packages/security/src",
    "packages/tool-contracts/src", "web/src"
)
$securityTests = @(
    "tests/core/test_security.py", "tests/runtime/security",
    "tests/data/security", "tests/platform/security",
    "tests/platform/test_gateway_security.py",
    "tests/acceptance/platform_security", "tests/experience/test_secret_scan.py"
)

function Invoke-Uv {
    param([Parameter(Mandatory)][string[]]$Arguments)
    & uv @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "uv command failed with exit code $LASTEXITCODE"
    }
}

function Invoke-Bootstrap {
    Invoke-Uv @("sync", "--all-packages", "--all-groups", "--locked")
}

function Invoke-Lint {
    Invoke-Uv ($allGroups + @("ruff", "check") + $ruffPaths)
    Invoke-Uv ($allGroups + @("mypy", "--strict") + $mypySources)
}

function Invoke-Test {
    Invoke-Uv ($allGroups + @("python", "-B", "-m", "pytest"))
}

function Invoke-Contract {
    Invoke-Uv ($allGroups + @("python", "-B", "contracts/conformance/validate.py"))
}

function Invoke-Security {
    Invoke-Uv ($allGroups + @("python", "-B", "-m", "pytest") + $securityTests)
}

function Invoke-Coverage {
    Invoke-Uv (
        $allGroups + @(
            "python", "-B", "-m", "pytest", "--cov",
            "--cov-report=term-missing:skip-covered",
            "--cov-report=xml:coverage.xml"
        )
    )
}

function Invoke-Audit {
    Invoke-Uv (
        $allGroups + @(
            "pip-audit", "--local", "--skip-editable", "--progress-spinner", "off"
        )
    )
}

switch ($Target) {
    "bootstrap" { Invoke-Bootstrap }
    "lint" { Invoke-Lint }
    "test" { Invoke-Test }
    "test-all" { Invoke-Test; Invoke-Contract }
    "test-contract" { Invoke-Contract }
    "test-security" { Invoke-Security }
    "test-coverage" { Invoke-Coverage }
    "audit" { Invoke-Audit }
    "ci" {
        Invoke-Lint
        Invoke-Coverage
        Invoke-Contract
        Invoke-Security
        Invoke-Audit
    }
}
