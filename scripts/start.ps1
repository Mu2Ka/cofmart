param(
    [switch]$Initialize,
    [switch]$DemoSlots
)

$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
$taskDockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if ($taskDockerCommand) {
    $script:TaskDocker = $taskDockerCommand.Source
} else {
    $taskCandidates = @(
        "$env:LOCALAPPDATA/Programs/DockerDesktop/resources/bin/docker.exe",
        "$env:USERPROFILE/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe",
        'C:/Program Files/Docker/Docker/resources/bin/docker.exe'
    )
    $script:TaskDocker = $taskCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $script:TaskDocker) {
    throw 'Docker Desktop is not installed. Finish its installation and start Docker Desktop first.'
}

function Invoke-ProjectDocker {
    & $script:TaskDocker @args
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed (exit $LASTEXITCODE). Check the error above."
    }
}

Push-Location $taskProjectRoot
try {
    if (-not (Test-Path -LiteralPath '.env')) {
        throw 'Create .env from .env.example and set API_BOT before starting.'
    }
    Invoke-ProjectDocker info --format '{{.OSType}}'
    Invoke-ProjectDocker compose config --quiet
    Invoke-ProjectDocker compose up -d --wait db
    if ($Initialize) {
        Invoke-ProjectDocker compose --profile tools run --rm --build migrate
        Invoke-ProjectDocker compose run --rm bot python -m app.db.seed
    }
    if ($DemoSlots) {
        $taskSlotStart = (Get-Date).AddHours(1).ToString('yyyy-MM-ddTHH:mm:sszzz')
        foreach ($taskCafe in @(1, 2)) {
            Invoke-ProjectDocker compose run --rm bot python -m app.db.manage add-slots --cafe-id $taskCafe --start $taskSlotStart --count 24 --interval 15 --capacity 5
        }
    }
    Invoke-ProjectDocker compose up -d --build bot api frontend
    Invoke-ProjectDocker compose ps
    Write-Host ''
    Write-Host 'Bot: send /start in Telegram.'
    Write-Host 'Frontend: http://localhost:5173 (Telegram HTTPS setup is needed for actual Mini App orders).'
    Write-Host 'API: http://localhost:8000/docs'
    Write-Host 'Stop: docker compose stop'
} finally {
    Pop-Location
}
