$py = 'C:\Users\Leonid\AppData\Local\Programs\Python\Python312\python.exe'
$script = Join-Path $PSScriptRoot 'weather_fetch.py'
& $py $script
if (Test-Path (Join-Path $PSScriptRoot 'weather_out.txt')) {
    Get-Content -LiteralPath (Join-Path $PSScriptRoot 'weather_out.txt') -Encoding UTF8
}
