param(
    [string]$Repository = 'YuxuanChen-2000/human-ai-brief',
    [string]$Python = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$ghCommand = Get-Command gh -ErrorAction SilentlyContinue
$gh = if ($ghCommand) { $ghCommand.Source } else { Join-Path $projectRoot '.tools/gh/gh.exe' }
if (-not (Test-Path -LiteralPath $gh)) { throw 'Install GitHub CLI and run gh auth login first.' }
if (-not $Python) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    $Python = if (Test-Path -LiteralPath $bundledPython) { $bundledPython } else { 'python' }
}
& $Python (Join-Path $PSScriptRoot 'publish_github.py') --repository $Repository --gh $gh
if ($LASTEXITCODE -ne 0) { throw 'Publication did not complete. Check the error above; existing remote history was not overwritten.' }


