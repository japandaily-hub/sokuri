param([Parameter(Mandatory=$true)][string]$Message)
$ErrorActionPreference = "Stop"
Set-Location C:\sokuri
# include root-level files (render.yaml, docker-compose.yml, README.md, DEPLOY.md, etc.) + tracked subdirs
git add -A
git commit -m "$Message"
git push
Start-Sleep -Seconds 2
