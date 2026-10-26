param([string]$JavaHome = $env:JAVA_HOME, [string]$MavenRepository = '')
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ([string]::IsNullOrWhiteSpace($JavaHome)) { throw 'Set JAVA_HOME to JDK 17 or supply -JavaHome' }
if (!(Test-Path -LiteralPath (Join-Path $JavaHome 'bin/java.exe'))) { throw 'Provide a real JDK 17 via -JavaHome' }
if (!(Select-String -LiteralPath (Join-Path $JavaHome 'release') -Pattern '^JAVA_VERSION="17[."]' -Quiet)) { throw 'This verification requires a real JDK 17' }
if ([string]::IsNullOrWhiteSpace($MavenRepository)) { $MavenRepository = Join-Path $root '.local/repository' }
$names = @('JAVA_HOME','PATH','P3_READER_A_SECRET','P3_BUYER_A_SECRET','P3_BUYER_B_SECRET')
$saved = @{}
foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    $env:JAVA_HOME = $JavaHome
    $env:PATH = "$JavaHome\bin;$env:PATH"
    foreach ($name in $names[2..4]) {
        $bytes = New-Object byte[] 32
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        [Environment]::SetEnvironmentVariable($name, ([BitConverter]::ToString($bytes).Replace('-','').ToLowerInvariant()), 'Process')
    }
    Push-Location $root
    try {
        # Windows PowerShell 5 treats native stderr warnings as errors when redirected.
        $ErrorActionPreference = 'Continue'
        & mvn -B "-Dmaven.repo.local=$MavenRepository" verify
        $buildExit = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        if ($buildExit -ne 0) { throw 'Maven verify failed' }
    } finally { Pop-Location }
} finally {
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
}
