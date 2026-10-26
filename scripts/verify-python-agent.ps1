param(
    [string]$JavaHome = $env:JAVA_HOME,
    [string]$MavenRepository = '',
    [int]$DemoPort = 18094
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$python = Join-Path $root 'python-agent/.venv/Scripts/python.exe'
if ([string]::IsNullOrWhiteSpace($JavaHome)) { throw 'Set JAVA_HOME to JDK 17 or supply -JavaHome.' }
if (!(Test-Path -LiteralPath $python)) { throw 'Create the P3 Python venv and install requirements.lock first.' }
if (!(Test-Path -LiteralPath (Join-Path $JavaHome 'bin/java.exe'))) { throw 'Provide JDK 17 via -JavaHome.' }
if (!(Select-String -LiteralPath (Join-Path $JavaHome 'release') -Pattern '^JAVA_VERSION="17[."]' -Quiet)) {
    throw 'A real JDK 17 is required.'
}
if (!$MavenRepository) { $MavenRepository = Join-Path $root '.local/repository' }
$settings = Join-Path $root 'scripts/python-agent-maven-settings.xml'
$names = @('JAVA_HOME','PATH','PYTHONUTF8','P3_JAVA_HOME','MAVEN_ARGS')
$saved = @{}
foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$run = [Guid]::NewGuid().ToString('N').Substring(0,12)
try {
    $env:JAVA_HOME = $JavaHome
    $env:P3_JAVA_HOME = $JavaHome
    $env:PATH = "$JavaHome\bin;$env:PATH"
    $env:PYTHONUTF8 = '1'
    # Maven >=3.9 honors MAVEN_ARGS. Replace only this process's settings, not global files.
    $env:MAVEN_ARGS = "-s `"$settings`" -gs `"$settings`""
    Push-Location (Join-Path $root 'python-agent')
    try {
        & $python -m pytest tests/test_agent.py tests/test_model_adapter.py tests/test_experiment_a.py -x -q "--junitxml=../target/python-agent-$run-unit.xml"
        if ($LASTEXITCODE -ne 0) { throw 'Python Agent contract failure; stop and review.' }
        & $python -m pytest tests/test_protocol.py -x -q "--junitxml=../target/python-agent-$run-protocol.xml"
        if ($LASTEXITCODE -ne 0) { throw 'MCP protocol contract failure; stop and review.' }
    } finally { Pop-Location }
    Push-Location $root
    try {
        # Compilation only, no test deletion/disablement. Fixed public plugin builds the SDK classpath.
        $ErrorActionPreference = 'Continue'
        & mvn -B "-Dmaven.repo.local=$MavenRepository" test-compile org.apache.maven.plugins:maven-dependency-plugin:3.8.1:build-classpath "-Dmdep.outputFile=target/python-agent-classpath.txt"
        $code = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        if ($code -ne 0) { throw 'Java fixture compile/classpath bootstrap failed.' }
    } finally { Pop-Location }
    Push-Location (Join-Path $root 'python-agent')
    try {
        & $python -m pytest tests/test_java_integration.py -x -q "--junitxml=../target/python-agent-$run-cross.xml"
        if ($LASTEXITCODE -ne 0) { throw 'Cross-language/security failure; stop. Do not retry an unauthorized side effect.' }
        & $python -m ruff check p3_agent tests scripts
        if ($LASTEXITCODE -ne 0) { throw 'Ruff failed.' }
        & $python -m pip check
        if ($LASTEXITCODE -ne 0) { throw 'pip check failed.' }
    } finally { Pop-Location }
    & (Join-Path $PSScriptRoot 'acceptance.ps1') -JavaHome $JavaHome -MavenRepository $MavenRepository -Port $DemoPort
    if ($LASTEXITCODE -ne 0) { throw 'Original Java acceptance failed.' }
    Write-Host "P3 Python and original Java acceptance passed. Run=$run. No real LLM requests."
} finally {
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
}
