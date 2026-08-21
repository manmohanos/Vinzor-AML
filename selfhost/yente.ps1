# Self-hosted screening stack: portable Elasticsearch + yente, no Docker,
# no service, no admin - the same pattern as pg.ps1 used for Postgres.
#
#   .\yente.ps1 start     start Elasticsearch and yente (indexes on first run)
#   .\yente.ps1 stop      stop both
#   .\yente.ps1 status    what is running, and whether the index is ready
#   .\yente.ps1 reindex   pull the latest OpenSanctions data into the index
#
# Layout (created by the setup steps in the repo README):
#   %USERPROFILE%\es-tools\elasticsearch-8.14.3\   portable ES, bundled JDK
#   %USERPROFILE%\es-tools\yente-venv\             yente in its own venv
#
# Ports: Elasticsearch 9200, yente 8090 (8000 belongs to `vinzor serve`).
# Point the product at it with:
#   $env:VINZOR_SCREENING_URL   = "http://127.0.0.1:8090"
#   $env:VINZOR_SCREENING_SCOPE = "sanctions"

param([string]$Command = "status")

$Tools    = Join-Path $env:USERPROFILE "es-tools"
$EsHome   = Join-Path $Tools "elasticsearch-8.14.3"
$Venv     = Join-Path $Tools "yente-venv"
$Manifest = Join-Path $PSScriptRoot "manifest.yml"
$EsPid    = Join-Path $Tools "es.pid"
$YentePid = Join-Path $Tools "yente.pid"

function Ready($url) {
    try { (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 }
    catch { $false }
}

function YenteEnv {
    $env:YENTE_INDEX_URL = "http://127.0.0.1:9200"
    # yente fetches its manifest with an HTTP client that reads "C:/..." as a
    # URL scheme, so a Windows path breaks it. The manifest is served over
    # loopback HTTP instead - StartManifestServer below.
    $env:YENTE_MANIFEST  = "http://127.0.0.1:8777/manifest.yml"
    $env:YENTE_PORT      = "8090"
    $env:YENTE_AUTO_REINDEX = "false"   # reindexing is a deliberate act
}

function StartManifestServer {
    if (-not (Ready "http://127.0.0.1:8777/manifest.yml")) {
        Start-Process -FilePath "python" `
            -ArgumentList "-m","http.server","8777","--bind","127.0.0.1" `
            -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru |
            ForEach-Object { $_.Id | Out-File (Join-Path $Tools "manifest.pid") }
    }
}

switch ($Command) {
    "start" {
        if (-not (Ready "http://127.0.0.1:9200")) {
            Write-Host "starting elasticsearch..."
            $es = Start-Process -FilePath (Join-Path $EsHome "bin\elasticsearch.bat") `
                -WindowStyle Hidden -PassThru
            $es.Id | Out-File $EsPid
            while (-not (Ready "http://127.0.0.1:9200")) { Start-Sleep 3 }
        }
        Write-Host "elasticsearch ready on :9200"

        StartManifestServer
        YenteEnv
        if (-not (Ready "http://127.0.0.1:8090/healthz")) {
            Write-Host "starting yente..."
            $y = Start-Process -FilePath (Join-Path $Venv "Scripts\yente.exe") `
                -ArgumentList "serve" -WindowStyle Hidden -PassThru
            $y.Id | Out-File $YentePid
            while (-not (Ready "http://127.0.0.1:8090/healthz")) { Start-Sleep 3 }
        }
        Write-Host "yente ready on :8090 - run '.\yente.ps1 reindex' if the index is empty"
    }
    "reindex" {
        StartManifestServer
        YenteEnv
        Write-Host "pulling and indexing the OpenSanctions '$((Get-Content $Manifest | Select-String 'scope:').ToString().Split(':')[1].Trim())' collection..."
        & (Join-Path $Venv "Scripts\yente.exe") reindex
    }
    "stop" {
        foreach ($f in @($YentePid, $EsPid, (Join-Path $Tools "manifest.pid"))) {
            if (Test-Path $f) {
                Stop-Process -Id (Get-Content $f) -Force -ErrorAction SilentlyContinue
                Remove-Item $f
            }
        }
        # ES spawns a JVM child; stop any leftover bound to our data dir
        Get-Process java -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -like "$EsHome*" } |
            Stop-Process -Force -ErrorAction SilentlyContinue
        Write-Host "stopped"
    }
    "status" {
        "elasticsearch : " + $(if (Ready "http://127.0.0.1:9200") { "up on :9200" } else { "down" })
        "yente         : " + $(if (Ready "http://127.0.0.1:8090/healthz") { "up on :8090" } else { "down" })
    }
    default { Write-Host "usage: .\yente.ps1 start|stop|status|reindex" }
}
