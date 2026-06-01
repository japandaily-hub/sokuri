"PROBE $(Get-Date -Format o)" | Out-File C:\sokuri\probe_log.txt -Encoding ASCII
try {
  $r = Invoke-WebRequest -Uri "https://sokuri-backend.onrender.com/health" -TimeoutSec 60 -UseBasicParsing
  "STATUS: $($r.StatusCode)" | Out-File C:\sokuri\probe_log.txt -Append -Encoding ASCII
  "BODY: $($r.Content)" | Out-File C:\sokuri\probe_log.txt -Append -Encoding ASCII
} catch {
  "ERROR: $($_.Exception.Message)" | Out-File C:\sokuri\probe_log.txt -Append -Encoding ASCII
  if ($_.Exception.Response) {
    "RESP_STATUS: $($_.Exception.Response.StatusCode)" | Out-File C:\sokuri\probe_log.txt -Append -Encoding ASCII
  }
}
"END $(Get-Date -Format o)" | Out-File C:\sokuri\probe_log.txt -Append -Encoding ASCII
