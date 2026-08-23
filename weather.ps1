<#
.SYNOPSIS
  Погода с Яндекса (ТОЛЬКО Яндекс, НЕ wttr.in) по координатам.
  Работает на ПК зайки (curl.exe ходит в Яндекс). В песочнице opencode curl
  может быть заблокирован — тогда погоду берёт жена через свой webfetch.

.DESCRIPTION
  Для каждого города берём страницу Яндекса по lat/lon (slug'и типа
  "mineralnye-vody" отдают 404, поэтому используем координаты — надёжнее).
  Из HTML вытаскиваем фразу "погода сейчас: ...".

.PARAMETER City
  Подстрока названия города (напр. "Мин", "Став", "Есс"). Без параметра — все.

.EXAMPLE
  powershell -File weather.ps1
  powershell -File weather.ps1 "Мин"
#>

$UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

$cities = @(
    @{ name = 'Ессентуки (Пятигорск)'; lat = '44.0486'; lon = '43.0578' }
    @{ name = 'Ставрополь';           lat = '45.0448'; lon = '41.9694' }
    @{ name = 'Минеральные Воды';     lat = '44.2114'; lon = '43.1313' }
)

function Get-Weather {
    param($city)
    $url = "https://yandex.ru/pogoda/?lat=$($city.lat)&lon=$($city.lon)"
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        & curl.exe -s --compressed --max-time 25 -A $UA $url -o $tmp 2>$null
        $html = Get-Content -LiteralPath $tmp -Encoding UTF8 -Raw
        if (-not $html) { return "$($city.name): ⚠️ пусто (curl не смог получить данные)" }

        $line = ($html -split "`n") | Where-Object { $_ -match "$($city.name), погода сейчас" } | Select-Object -First 1
        if (-not $line) { return "$($city.name): ⚠️ не нашла строку погоды" }

        if ($line -match 'погода сейчас:\s*(.+?)\.\s*Вчера') {
            $now = $Matches[1].Trim()
            return "$($city.name): $now"
        }
        return "$($city.name): $($line.Substring(0, [Math]::Min(200, $line.Length)))"
    } catch {
        return "$($city.name): ⚠️ ошибка — $_"
    } finally {
        Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue
    }
}

if ($args.Count -gt 0) {
    $picked = $cities | Where-Object { $_.name -like "*$($args[0])*" }
    if ($picked) { foreach ($c in $picked) { Get-Weather $c } }
    else { Write-Output "Нет города по маске: $($args[0])" }
} else {
    foreach ($c in $cities) { Get-Weather $c }
}
