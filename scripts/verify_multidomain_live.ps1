param([string]$JUnitXml = '')
$ErrorActionPreference = 'Stop'
$i19OwnedNeo4j = $false
$i19OwnedPostgres = $false
$i19Variables = @('NEO4J_URI','NEO4J_PASSWORD','NEO4J_USER','RUN_LIVE_GROQ_TESTS',
    'RUN_LIVE_LLM_TESTS','SENTINEL_TEST_OPERATIONS_DATABASE_URL','SENTINEL_I19_DISPOSABLE_NEO4J')
$i19Previous = @{}
foreach ($i19Name in $i19Variables) { $i19Previous[$i19Name] = [Environment]::GetEnvironmentVariable($i19Name) }
try {
    $i19Password = [guid]::NewGuid().ToString('N')
    $env:NEO4J_URI = 'bolt://127.0.0.1:17687'
    $env:NEO4J_PASSWORD = $i19Password
    $env:NEO4J_USER = 'neo4j'
    $env:RUN_LIVE_GROQ_TESTS = '0'
    $env:RUN_LIVE_LLM_TESTS = '0'
    $env:SENTINEL_I19_DISPOSABLE_NEO4J = '1'
    $env:SENTINEL_TEST_OPERATIONS_DATABASE_URL = "postgresql://postgres:${i19Password}@127.0.0.1:15432/sentinel_test_i19"
    docker run -d --rm --name sentinel-i19-final-neo4j -p 127.0.0.1:17687:7687 -p 127.0.0.1:17474:7474 -e "NEO4J_AUTH=neo4j/$i19Password" neo4j:5.26-community
    if ($LASTEXITCODE -ne 0) { throw 'Disposable Neo4j creation failed' }
    $i19OwnedNeo4j = $true
    docker run -d --rm --name sentinel-i19-final-postgres -p 127.0.0.1:15432:5432 -e "POSTGRES_PASSWORD=$i19Password" -e POSTGRES_DB=sentinel_test_i19 postgres:17
    if ($LASTEXITCODE -ne 0) { throw 'Disposable PostgreSQL creation failed' }
    $i19OwnedPostgres = $true
    $i19Ready = $false
    for ($i19Attempt = 0; $i19Attempt -lt 30; $i19Attempt++) {
        docker exec sentinel-i19-final-neo4j wget -q --spider http://localhost:7474 2>$null
        $i19NeoReady = $LASTEXITCODE -eq 0
        docker exec sentinel-i19-final-postgres pg_isready -U postgres -d sentinel_test_i19 >$null 2>$null
        if ($i19NeoReady -and $LASTEXITCODE -eq 0) { $i19Ready = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $i19Ready) { throw 'Disposable services did not become ready within 60 seconds' }
    uv run python -c "import os; from sentinel_pomdp.operations import PostgresOperationRepository; r=PostgresOperationRepository(os.environ['SENTINEL_TEST_OPERATIONS_DATABASE_URL']); r.close()"
    if ($LASTEXITCODE -ne 0) { throw 'Disposable PostgreSQL migration failed' }
    if ($JUnitXml) { uv run pytest -q -rs --junitxml=$JUnitXml }
    else { uv run pytest -q -rs }
    $i19Result = $LASTEXITCODE
}
finally {
    # --rm removes only these newly created containers and their anonymous volumes.
    if ($i19OwnedNeo4j) { docker stop sentinel-i19-final-neo4j }
    if ($i19OwnedPostgres) { docker stop sentinel-i19-final-postgres }
    foreach ($i19Name in $i19Variables) {
        [Environment]::SetEnvironmentVariable($i19Name, $i19Previous[$i19Name], 'Process')
    }
}
exit $i19Result
