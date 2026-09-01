#!/bin/bash
# Zapretik for Linux — обёртка над nfqws (bol-van/zapret)
# Аналог main.py для Windows
# Совместимо с Arch Linux, Ubuntu, Debian, Fedora

set -euo pipefail

VERSION="4.0.3"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NFQWS="${SCRIPT_DIR}/bin/nfqws"
LOG_FILE="${SCRIPT_DIR}/zapretik.log"
PID_FILE="${SCRIPT_DIR}/.nfqws.pid"
LISTS_DIR="${SCRIPT_DIR}/lists"
BIN_DIR="${SCRIPT_DIR}/bin"

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo -e "$msg" | tee -a "$LOG_FILE"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        echo -e "${RED}Требуются права root! Запустите: sudo $0${NC}"
        exit 1
    fi
}

check_nfqws() {
    if [[ ! -f "$NFQWS" ]]; then
        echo -e "${YELLOW}nfqws не найден. Скачиваю с GitHub...${NC}"
        download_nfqws
    fi
}

download_nfqws() {
    mkdir -p "$BIN_DIR"
    local arch
    arch=$(uname -m)
    case "$arch" in
        x86_64)  arch="amd64" ;;
        aarch64) arch="arm64" ;;
        *)       echo "Архитектура $arch не поддерживается"; exit 1 ;;
    esac

    local url="https://github.com/bol-van/zapret/releases/latest/download/zapret-linux-${arch}.tar.gz"
    local tmp="/tmp/zapret.download.$$.tar.gz"

    if command -v curl &>/dev/null; then
        curl -L -o "$tmp" "$url"
    elif command -v wget &>/dev/null; then
        wget -O "$tmp" "$url"
    else
        echo "Нужен curl или wget"; exit 1
    fi

    tar xzf "$tmp" -C /tmp/
    cp /tmp/zapret-*/nfqws/nfqws "$NFQWS" 2>/dev/null || \
    cp /tmp/zapret-*/main/nfqws "$NFQWS" 2>/dev/null || \
    cp /tmp/zapret-*/nfqws "$NFQWS" 2>/dev/null
    chmod +x "$NFQWS"
    rm -rf "$tmp" /tmp/zapret-*
    log "nfqws установлен: $NFQWS"
}

stop_nfqws() {
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            log "nfqws остановлен (PID $pid)"
        fi
        rm -f "$PID_FILE"
    fi
    # На всякий случай — убить все nfqws
    pkill -f "nfqws" 2>/dev/null || true
}

is_running() {
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE")
        kill -0 "$pid" 2>/dev/null && return 0
    fi
    return 1
}

run_strategy() {
    local name="$1"
    shift
    local args=("$@")

    stop_nfqws
    log "Запуск стратегии: $name"
    log "Аргументы: nfqws ${args[*]}"

    "$NFQWS" "${args[@]}" &
    local pid=$!
    echo "$pid" > "$PID_FILE"
    log "nfqws запущен (PID $pid)"

    echo -e "${GREEN}Сервис запущен. Для остановки: $0 stop${NC}"
}

show_status() {
    if is_running; then
        local pid
        pid=$(cat "$PID_FILE")
        echo -e "${GREEN}Сервис работает (PID $pid)${NC}"
    else
        echo -e "${RED}Сервис остановлен${NC}"
    fi
}

show_menu() {
    echo -e "\n${BOLD}=== Zapretik v${VERSION} (Linux) ===${NC}\n"
    echo -e "${GREEN}1.${NC} Discord + YouTube (Стандарт)"
    echo -e "   фейковая подмена TLS + фрагментация пакетов"
    echo -e "${YELLOW}2.${NC} Только YouTube (Агрессивный)"
    echo -e "   перестановка сегментов + фрагментация"
    echo -e "${CYAN}3.${NC} Безопасный режим (Медленный)"
    echo -e "   только фрагментация, без фейков"
    echo -e "${RED}4.${NC} Остановить сервис"
    echo -e "${RED}0.${NC} Выход\n"
}

# Стратегии (аналог Windows версии)
strategy_1() {
    # Discord + YouTube (Стандарт)
    run_strategy "Стандарт" \
        --wf-tcp=443 \
        --wsize=2 \
        --split-pos=2 \
        --fake-tls \
        --dpi-desync=fake \
        --filter-tcp=443
}

strategy_2() {
    # Только YouTube (Агрессивный)
    run_strategy "Агрессивный" \
        --wf-tcp=443 \
        --wsize=1 \
        --split-pos=1 \
        --fake-tls \
        --dpi-desync=reorder \
        --filter-tcp=443
}

strategy_3() {
    # Безопасный режим
    run_strategy "Безопасный" \
        --wf-tcp=443 \
        --wsize=1 \
        --split-pos=1 \
        --filter-tcp=443
}

# General стратегия (из general.bat)
strategy_general() {
    local LISTS="${LISTS_DIR}/"
    run_strategy "General" \
        --wf-tcp=80,443,2053,2083,2087,2096,8443 \
        --wf-udp=443,19294-19344,50000-50100 \
        --filter-udp=443 --hostlist="${LISTS}list-general.txt" --hostlist="${LISTS}list-general-user.txt" \
        --hostlist-exclude="${LISTS}list-exclude.txt" --hostlist-exclude="${LISTS}list-exclude-user.txt" \
        --ipset-exclude="${LISTS}ipset-exclude.txt" --ipset-exclude="${LISTS}ipset-exclude-user.txt" \
        --dpi-desync=fake --dpi-desync-repeats=6 --new \
        --filter-tcp=443 --hostlist="${LISTS}list-general.txt" --hostlist="${LISTS}list-general-user.txt" \
        --hostlist-exclude="${LISTS}list-exclude.txt" --hostlist-exclude="${LISTS}list-exclude-user.txt" \
        --ipset-exclude="${LISTS}ipset-exclude.txt" --ipset-exclude="${LISTS}ipset-exclude-user.txt" \
        --dpi-desync=hostfakesplit --dpi-desync-repeats=4 --dpi-desync-fooling=ts,md5sig \
        --dpi-desync-hostfakesplit-mod=host=ozon.ru
}

show_version() {
    echo -e "${CYAN}Текущая версия: ${VERSION}${NC}"
}

# Основной цикл
main() {
    case "${1:-}" in
        stop)
            check_root
            stop_nfqws
            exit 0
            ;;
        status)
            show_status
            exit 0
            ;;
        start)
            check_root
            check_nfqws
            strategy_general
            exit 0
            ;;
    esac

    check_nfqws

    while true; do
        show_menu
        read -rp "Выберите режим: " choice
        case "$choice" in
            1) check_root; strategy_1 ;;
            2) check_root; strategy_2 ;;
            3) check_root; strategy_3 ;;
            4) check_root; stop_nfqws ;;
            5) show_version ;;
            0) exit 0 ;;
            *) echo -e "${RED}Неизвестный пункт${NC}" ;;
        esac
    done
}

main "$@"
