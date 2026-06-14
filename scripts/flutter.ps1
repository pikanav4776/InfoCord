# Refreshes User PATH then runs Flutter (use if `flutter` is not recognized in Cursor).
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
& flutter @args
exit $LASTEXITCODE
