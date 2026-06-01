"START $(Get-Date -Format o)" | Out-File C:\sokuri\push_log.txt -Encoding ASCII
try {
  Set-Location C:\sokuri
  "PWD: $(Get-Location)" | Out-File C:\sokuri\push_log.txt -Append -Encoding ASCII
  $statusOut = & git status --short 2>&1 | Out-String
  "STATUS:`n$statusOut" | Out-File C:\sokuri\push_log.txt -Append -Encoding ASCII
  $logOut = & git log --oneline -3 2>&1 | Out-String
  "LOG:`n$logOut" | Out-File C:\sokuri\push_log.txt -Append -Encoding ASCII
  "PUSHING..." | Out-File C:\sokuri\push_log.txt -Append -Encoding ASCII
  $pushOut = & git push 2>&1 | Out-String
  "PUSH RESULT:`n$pushOut" | Out-File C:\sokuri\push_log.txt -Append -Encoding ASCII
  $remoteOut = & git ls-remote origin main 2>&1 | Out-String
  "REMOTE NOW:`n$remoteOut" | Out-File C:\sokuri\push_log.txt -Append -Encoding ASCII
} catch {
  "ERROR: $_" | Out-File C:\sokuri\push_log.txt -Append -Encoding ASCII
}
"END $(Get-Date -Format o)" | Out-File C:\sokuri\push_log.txt -Append -Encoding ASCII
