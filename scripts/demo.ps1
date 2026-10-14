param([string]$JavaHome = 'C:\Users\R9000P\.jdks\ms-17.0.16', [int]$Port = 18093)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$jar = Join-Path $root 'target/agent-security-gateway-0.1.0.jar'
if (!(Test-Path -LiteralPath $jar)) { throw 'Build the project before running the demo' }
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Invalid local port' }
if (@(([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties()).GetActiveTcpListeners() | Where-Object Port -eq $Port).Count -ne 0) { throw 'Demo port is already in use' }
$names = @('P3_READER_A_SECRET','P3_BUYER_A_SECRET','P3_BUYER_B_SECRET')
$saved = @{}
$client = $null
$process = $null
$logs = Join-Path $root ('target/demo/' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $logs -Force | Out-Null
try {
    foreach ($name in $names) {
        $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        $bytes = New-Object byte[] 32
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        [Environment]::SetEnvironmentVariable($name, ([BitConverter]::ToString($bytes).Replace('-','').ToLowerInvariant()), 'Process')
    }
    $process = Start-Process (Join-Path $JavaHome 'bin/java.exe') -ArgumentList @('-jar', ('"' + $jar + '"'), '--server.address=127.0.0.1', "--server.port=$Port", '--debug=false', '--logging.level.root=INFO', '--logging.level.org.springframework.web=WARN') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'app.log') -RedirectStandardError (Join-Path $logs 'error.log') -PassThru
    Add-Type -AssemblyName System.Net.Http
    $client = New-Object Net.Http.HttpClient
    $client.Timeout = [TimeSpan]::FromSeconds(5)
    $script:demoId = 0
    function Invoke-Mcp([string]$Method, [object]$Params, [string]$Credential) {
        $script:demoId++
        $req = New-Object Net.Http.HttpRequestMessage
        $req.Method = [Net.Http.HttpMethod]::Post
        $req.RequestUri = [Uri]"http://127.0.0.1:$Port/mcp"
        $req.Headers.TryAddWithoutValidation('Accept','application/json, text/event-stream') | Out-Null
        $req.Headers.TryAddWithoutValidation('MCP-Protocol-Version','2025-06-18') | Out-Null
        if ($Credential) { $req.Headers.TryAddWithoutValidation('X-API-Key',$Credential) | Out-Null }
        $payload = @{jsonrpc='2.0';id=$script:demoId;method=$Method;params=$Params} | ConvertTo-Json -Depth 10 -Compress
        $req.Content = New-Object Net.Http.StringContent($payload, [Text.Encoding]::UTF8, 'application/json')
        $response = $null
        try {
            $response = $client.SendAsync($req).GetAwaiter().GetResult()
            $raw = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            foreach ($name in $names) { if ($raw.Contains([Environment]::GetEnvironmentVariable($name,'Process'))) { throw 'Secret reflected in MCP response' } }
            $body = if ($raw) { $raw | ConvertFrom-Json } else { $null }
            return @{status=[int]$response.StatusCode;body=$body}
        } finally { if ($response) { $response.Dispose() }; $req.Dispose() }
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(25)
    do {
        if ($process.HasExited) { throw 'Demo server failed to start; inspect local logs' }
        try { $ready = (Invoke-Mcp 'tools/list' @{} '').status -eq 401 } catch { $ready = $false }
        if (!$ready) { Start-Sleep -Milliseconds 200 }
    } while (!$ready -and [DateTime]::UtcNow -lt $deadline)
    if (!$ready) { throw 'Demo startup deadline exceeded' }
    $reader = 'reader-a.' + $env:P3_READER_A_SECRET
    $buyer = 'buyer-a.' + $env:P3_BUYER_A_SECRET
    $init = Invoke-Mcp 'initialize' @{protocolVersion='2025-06-18';capabilities=@{};clientInfo=@{name='p3-demo';version='1'}} $reader
    if ($init.status -ne 200 -or !$init.body.result.serverInfo) { throw 'Initialize failed' }
    $list = Invoke-Mcp 'tools/list' @{} $reader
    if ($list.status -ne 200 -or $list.body.result.tools.Count -ne 2) { throw 'Discovery failed' }
    $evidence = @(@{case='initialize';status=200}, @{case='tools/list';status=200;tools=@($list.body.result.tools.name)})
    foreach ($case in @(
        @{label='inventory-own';key=$reader;tool='inventory.read';arguments=@{productId='sku-a1'};error=$false;code='ALLOW'},
        @{label='update-own';key=$buyer;tool='purchase_order.update';arguments=@{orderId='po-a1';quantity=25};error=$false;code='ALLOW'},
        @{label='reader-write';key=$reader;tool='purchase_order.update';arguments=@{orderId='po-a1';quantity=99};error=$true;code='FORBIDDEN'},
        @{label='cross-tenant';key=$buyer;tool='purchase_order.update';arguments=@{orderId='po-b1';quantity=99};error=$true;code='FORBIDDEN'},
        @{label='agent-forged';key=$reader;tool='purchase_order.update';arguments=@{orderId='po-a1';quantity=99;role='ADMIN';tenantId='tenant-a'};error=$true;code='INVALID_ARGUMENTS'}
    )) {
        $response = Invoke-Mcp 'tools/call' @{name=$case.tool;arguments=$case.arguments} $case.key
        if ($response.status -ne 200 -or $response.body.result.isError -ne $case.error) { throw "Demo case failed: $($case.label)" }
        $content = $response.body.result.content[0].text | ConvertFrom-Json
        if ($case.error -and $content.code -ne $case.code) { throw 'Unexpected denial code' }
        if ($case.label -eq 'inventory-own' -and $content.data.available -ne 120) { throw 'Inventory mismatch' }
        if ($case.label -eq 'update-own' -and $content.data.quantity -ne 25) { throw 'Order update mismatch' }
        $evidence += @{case=$case.label;status=200;code=$case.code;requestId=$content.requestId}
    }
    $replacement = if ($reader.EndsWith('a')) { 'b' } else { 'a' }
    $wrong = $reader.Substring(0, $reader.Length - 1) + $replacement
    foreach ($credential in @('', ($reader + '.suffix'), $wrong)) {
        if ((Invoke-Mcp 'tools/list' @{} $credential).status -ne 401) { throw 'Invalid credentials accepted' }
    }
    $evidence += @{case='missing-malformed-wrong-credentials';status=401}
    $unknown = Invoke-Mcp 'tools/call' @{name='unregistered';arguments=@{}} $buyer
    if ($unknown.body.error.message -ne 'UNKNOWN_TOOL') { throw 'Unknown tool accepted' }
    $evidence += @{case='unregistered-tool';status=200;code='UNKNOWN_TOOL'}
    foreach ($path in @((Join-Path $logs 'app.log'), (Join-Path $logs 'error.log'))) {
        $text = Get-Content -LiteralPath $path -Raw -ErrorAction SilentlyContinue
        foreach ($name in $names) { if ($text -and $text.Contains([Environment]::GetEnvironmentVariable($name,'Process'))) { throw 'Secret found in server logs' } }
    }
    $evidence | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 (Join-Path $logs 'evidence.json')
    $evidence | ForEach-Object { Write-Host "$($_.case): HTTP $($_.status) $($_.code)" }
    Write-Host "Packaged JAR demo passed; sanitized evidence: $logs/evidence.json"
} finally {
    if ($client) { $client.Dispose() }
    if ($process -and !$process.HasExited) { Stop-Process -InputObject $process }
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
}
