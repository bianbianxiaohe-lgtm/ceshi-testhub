$log = "c:\TestHub\backend_build.log"
$marker = "c:\TestHub\deploy_done.log"
Set-Content -Path $marker -Value "WATCHER_STARTED"
$timeout = 900
$elapsed = 0
while ($elapsed -lt $timeout) {
    if (Select-String -Path $log -Pattern "BACKEND_BUILD_DONE" -Quiet) {
        if (Select-String -Path $log -Pattern "ERROR: process|ResolutionImpossible" -Quiet) {
            Add-Content -Path $marker -Value "BUILD_FAILED"
            exit 1
        }
        Add-Content -Path $marker -Value "BUILD_OK_DEPLOYING"
        Set-Location c:\TestHub
        docker compose up -d backend 2>&1 | Add-Content -Path $marker
        docker compose up -d frontend 2>&1 | Add-Content -Path $marker
        Add-Content -Path $marker -Value "DEPLOY_DONE"
        exit 0
    }
    Start-Sleep -Seconds 10
    $elapsed += 10
}
Add-Content -Path $marker -Value "BUILD_TIMEOUT"
exit 2
