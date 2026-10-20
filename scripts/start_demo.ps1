param([string]$Project = 'sentinel-demo-local', [int]$Port = 18082)
$ErrorActionPreference = 'Stop'
if ($Project -notmatch '^sentinel-demo-[a-z0-9-]+$') { throw 'Use an isolated sentinel-demo- project name' }
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Choose a local unprivileged port' }
$i20DemoRoot = Join-Path $PSScriptRoot '..\data\demo'
New-Item -ItemType Directory -Path $i20DemoRoot -Force >$null
$i20EnvFile = Join-Path $i20DemoRoot "$Project.env"
if (-not (Test-Path -LiteralPath $i20EnvFile)) {
    $i20NeoPassword = [guid]::NewGuid().ToString('N')
    $i20PostgresPassword = [guid]::NewGuid().ToString('N')
    $i20Key = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
    $i20Lines = @("NEO4J_AUTH=neo4j/$i20NeoPassword", "NEO4J_PASSWORD=$i20NeoPassword",
        "POSTGRES_PASSWORD=$i20PostgresPassword", "SENTINEL_API_KEY=$i20Key",
        "SENTINEL_PORT=$Port", 'SENTINEL_LLM_PROVIDER=fake', 'SENTINEL_EXTERNAL_LLM_ENABLED=0',
        "SENTINEL_TENANT_ID=tenant_demo_$($Project.Replace('-','_'))",
        'SENTINEL_PRINCIPAL_ID=demo-reviewer', 'SENTINEL_ROLES=analyst,reviewer',
        'SENTINEL_PERMISSIONS=investigation:execute,evidence:read,provenance:read,trace:read,workflow:resume,document:upload,document:read,evidence:review,domain-pack:manage,model:approve,job:submit,job:read,job:cancel,operations:read,evaluation:read')
    [IO.File]::WriteAllLines($i20EnvFile, $i20Lines)
}
$i20Previous = @{}
try {
    foreach ($i20Line in [IO.File]::ReadAllLines($i20EnvFile)) {
        $i20Pair = $i20Line.Split('=', 2)
        $i20Previous[$i20Pair[0]] = [Environment]::GetEnvironmentVariable($i20Pair[0])
        [Environment]::SetEnvironmentVariable($i20Pair[0], $i20Pair[1], 'Process')
    }
    $i20Compose = Join-Path $PSScriptRoot '..\infra\deployment.compose.yaml'
    docker compose -p $Project --env-file $i20EnvFile -f $i20Compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Compose configuration rejected' }
    docker compose -p $Project --env-file $i20EnvFile -f $i20Compose up -d --build --wait --wait-timeout 180
    if ($LASTEXITCODE -ne 0) { throw 'Controlled demo startup failed' }
    docker compose -p $Project --env-file $i20EnvFile -f $i20Compose exec -T api python scripts/prepare_demo.py --synthetic-demo
    if ($LASTEXITCODE -ne 0) { throw 'Synthetic demo preparation failed' }
    Write-Output "Demo ready at http://127.0.0.1:$Port; local credential file: data/demo/$Project.env (do not publish)."
}
finally {
    foreach ($i20Name in $i20Previous.Keys) {
        [Environment]::SetEnvironmentVariable($i20Name, $i20Previous[$i20Name], 'Process')
    }
}
