$logPath = "C:\sokuri\e2e_log.txt"
"E2E START $(Get-Date -Format o)" | Out-File $logPath -Encoding ASCII

function Probe($name, $url) {
  "--- $name : $url ---" | Out-File $logPath -Append -Encoding ASCII
  try {
    $r = Invoke-WebRequest -Uri $url -TimeoutSec 90 -UseBasicParsing
    "STATUS: $($r.StatusCode)" | Out-File $logPath -Append -Encoding ASCII
    $body = $r.Content
    if ($body.Length -gt 500) { $body = $body.Substring(0, 500) + "...(truncated)" }
    "BODY: $body" | Out-File $logPath -Append -Encoding ASCII
  } catch {
    "ERROR: $($_.Exception.Message)" | Out-File $logPath -Append -Encoding ASCII
    if ($_.Exception.Response) {
      "RESP_STATUS: $([int]$_.Exception.Response.StatusCode)" | Out-File $logPath -Append -Encoding ASCII
    }
  }
}

# 1) backend health (Render)
Probe "backend-health" "https://sokuri-backend.onrender.com/health"

# 2) backend OpenAPI (確認用)
Probe "backend-openapi" "https://sokuri-backend.onrender.com/openapi.json"

# 3) frontend top page (Vercel)
Probe "frontend-top" "https://sokuri.vercel.app/"

"E2E END $(Get-Date -Format o)" | Out-File $logPath -Append -Encoding ASCII
