#!/bin/bash
# Zapretik Watchdog for Linux — аналог watchdog.py
# Следит за nfqws, перезапускает при падении

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NFQWS="${SCRIPT_DIR}/bin/nfqws"
PID_FILE="${SCRIPT_DIR}/.nfqws.pid"
LOG_FILE="${SCRIPT_DIR}/watchdog.log"
CHECK_INTERVAL=120  # секунды между проверками

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" >> "$LOG_FILE"
    echo "$msg"
}

is_running() {
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE")
        kill -0 "$pid" 2>/dev/null && return 0
    fi
    return 1
}

check_discord() {
    local status=0
    for url in "https://discord.com" "https://detector404.ru/discord"; do
        if ! curl -sf --max-time 5 "$url" >/dev/null 2>&1; then
            status=1
        fi
    done
    return $status
}

restart_nfqws() {
    log "Перезапуск nfqws..."
    pkill -f "nfqws" 2>/dev/null || true
    sleep 2
    "$SCRIPT_DIR/zapretik.sh" start >/dev/null 2>&1 &
    sleep 5
    if is_running; then
        log "nfqws восстановлен"
    else
        log "ОШИБКА: nfqws не запустился!"
    fi
}

log "Watchdog запущен"

while true; do
    if ! is_running; then
        log "nfqws не работает — перезапуск"
        restart_nfqws
    fi

    if ! check_discord; then
        log "Discord недоступен — перезапуск nfqws"
        restart_nfqws
    fi

    sleep "$CHECK_INTERVAL"
done
