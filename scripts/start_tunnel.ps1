$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$toolsDirectory = Join-Path $projectRoot '.tools'
$envPath = Join-Path $projectRoot '.env'
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
$logPath = Join-Path $toolsDirectory 'ssh-tunnel.output.log'
$errorPath = Join-Path $toolsDirectory 'ssh-tunnel.error.log'
$pidPath = Join-Path $toolsDirectory 'ssh-tunnel.pid'
$knownHosts = Join-Path $toolsDirectory 'known_hosts'

if (-not (Test-Path -LiteralPath $envPath)) { throw 'Existing .env file is required.' }
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Project .venv is required.' }
$sshPath = (Get-Command ssh -ErrorAction Stop).Source
New-Item -ItemType Directory -Path $toolsDirectory -Force | Out-Null

$tunnelProcess = $null
if (Test-Path -LiteralPath $pidPath) {
    $savedId = [int](Get-Content -LiteralPath $pidPath -Raw).Trim()
    $candidate = Get-Process -Id $savedId -ErrorAction SilentlyContinue
    if ($candidate -and $candidate.Path -eq $sshPath) { $tunnelProcess = $candidate }
}
if (-not $tunnelProcess) {
    $port = & $pythonPath -c 'from dotenv import dotenv_values; import sys; print(dotenv_values(sys.argv[1]).get("WEB_PORT") or "8080")' $envPath
    if ($LASTEXITCODE -ne 0 -or $port -notmatch '^\d+$') { throw 'Cannot read WEB_PORT.' }
    $sshArguments = @('-4', '-T', '-o', 'StrictHostKeyChecking=accept-new', '-o', "UserKnownHostsFile=$knownHosts", '-o', 'PreferredAuthentications=none', '-o', 'ServerAliveInterval=30', '-o', 'ConnectTimeout=15', '-R', "80:127.0.0.1:$port", 'nokey@localhost.run')
    $tunnelProcess = Start-Process -FilePath $sshPath -ArgumentList $sshArguments -WindowStyle Hidden -RedirectStandardOutput $logPath -RedirectStandardError $errorPath -PassThru
    Set-Content -LiteralPath $pidPath -Value $tunnelProcess.Id
}

$publicUrl = $null
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if (Test-Path -LiteralPath $logPath) {
        $log = Get-Content -LiteralPath $logPath -Raw
        if ($log -match 'https://[a-z0-9.-]+\.lhr\.life') { $publicUrl = $Matches[0]; break }
    }
    if ($tunnelProcess.HasExited) { throw "Tunnel exited. Check $errorPath" }
    Start-Sleep -Seconds 1
}
if (-not $publicUrl) { throw "Tunnel URL was not received. Check $logPath and $errorPath" }

& $pythonPath -c 'from dotenv import set_key; import sys; set_key(sys.argv[1], "MINI_APP_URL", sys.argv[2], quote_mode="never")' $envPath $publicUrl
if ($LASTEXITCODE -ne 0) { throw 'Cannot update MINI_APP_URL in the existing .env.' }
Write-Output "MINI_APP_URL updated: $publicUrl"
Write-Output "Tunnel is running in the background (PID $($tunnelProcess.Id))."
Write-Output 'Now run main.py, then send /start to your bot.'
Write-Output 'Free tunnel addresses can rotate. If the address stops working, stop the tunnel and run this script again.'
