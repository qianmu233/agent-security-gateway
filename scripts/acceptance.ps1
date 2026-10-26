param([string]$JavaHome = $env:JAVA_HOME, [string]$MavenRepository = '', [int]$Port = 18093)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'verify.ps1') -JavaHome $JavaHome -MavenRepository $MavenRepository
if ($LASTEXITCODE -ne 0) { throw 'Full Maven verification failed' }
& (Join-Path $PSScriptRoot 'demo.ps1') -JavaHome $JavaHome -Port $Port
$report = Join-Path $PSScriptRoot '../target/security-evaluation/results.json'
$data = Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
if ($data.sampleStatus -ne 'COMPLETE' -or $data.metrics.passedScenarios -ne 24) { throw 'Evaluation incomplete or failed' }
Write-Host ('Evaluation: legal pass={0}%; illegal execution blocked={1}%; illegal execution success={2}%; false rejection={3}%; p50={4:N2} ms; p95={5:N2} ms' -f $data.metrics.legalPassRatePercent,$data.metrics.illegalExecutionBlockRatePercent,$data.metrics.illegalExecutionSuccessRatePercent,$data.metrics.legalFalseRejectRatePercent,$data.metrics.latencyP50Millis,$data.metrics.latencyP95Millis)
Write-Host "Acceptance passed; reports: $report and report.md/results.csv"
