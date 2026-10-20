param([string]$JUnitXml = '')
$ErrorActionPreference = 'Stop'
$i20Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$i20Export = Join-Path $i20Root ('data\release-validation\' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $i20Export -Force >$null
if (-not $JUnitXml) {
    $i20ReportDirectory = Join-Path $i20Root ('reports\implementation20\local\clean-install\' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $i20ReportDirectory -Force >$null
    $JUnitXml = Join-Path $i20ReportDirectory 'offline.xml'
}
if (Test-Path -LiteralPath $JUnitXml) { throw 'Refusing to overwrite an existing verification report' }
$i20Files = git -C $i20Root ls-files --cached --others --exclude-standard
foreach ($i20File in $i20Files) {
    if ($i20File -match '(__pycache__|\.egg-info/|\.pyc$|\.zip$)') { continue }
    if ($i20File -notmatch '^(src/|tests/|scripts/|infra/|docs/|tools/|\.github/|README\.md$|LICENSE$|NOTICE$|pyproject\.toml$|uv\.lock$|requirements\.txt$|Dockerfile$|\.dockerignore$|\.gitignore$|\.env\.example$)') { continue }
    $i20Source = Join-Path $i20Root $i20File
    if (-not (Test-Path -LiteralPath $i20Source -PathType Leaf)) { continue }
    $i20Target = Join-Path $i20Export $i20File
    New-Item -ItemType Directory -Path (Split-Path $i20Target) -Force >$null
    Copy-Item -LiteralPath $i20Source -Destination $i20Target
}
$env:RUN_LIVE_GROQ_TESTS = '0'
$env:RUN_LIVE_LLM_TESTS = '0'
$env:NEO4J_URI = 'bolt://127.0.0.1:17688'
Remove-Item Env:SENTINEL_TEST_OPERATIONS_DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:SENTINEL_I19_DISPOSABLE_NEO4J -ErrorAction SilentlyContinue
uv sync --directory $i20Export --frozen --group dev
if ($LASTEXITCODE -ne 0) { throw 'Isolated installation failed' }
uv run --directory $i20Export --frozen pytest -q -rs --junitxml="$JUnitXml"
$i20Result = $LASTEXITCODE
Write-Output "Isolated source export retained at $i20Export; no original Olist archive or local credentials copied."
Write-Output "Private verification report: $JUnitXml"
exit $i20Result
