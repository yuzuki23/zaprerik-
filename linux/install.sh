#!/bin/bash
# Zapretik Installer for Arch Linux
# Устанавливает Zapretik и systemd-сервис

set -euo pipefail

INSTALL_DIR="/opt/zapretik"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
    echo "Требуются права root: sudo $0"
    exit 1
fi

echo "Устанавливаю Zapretik в $INSTALL_DIR..."

# Копирование файлов
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/zapretik.sh"
chmod +x "$INSTALL_DIR/zapretik-watchdog.sh"

# Установка nfqws если нет
if [[ ! -f "$INSTALL_DIR/bin/nfqws" ]]; then
    echo "Скачиваю nfqws..."
    cd "$INSTALL_DIR"
    bash zapretik.sh stop 2>/dev/null || true
    bash -c 'source zapretik.sh; download_nfqws' 2>/dev/null || \
    bash zapretik.sh 0 2>/dev/null || true
fi

# systemd сервис
cp "$INSTALL_DIR/zapretik.service" /etc/systemd/system/
systemctl daemon-reload

echo ""
echo "Установка завершена!"
echo ""
echo "Использование:"
echo "  Меню:           sudo $INSTALL_DIR/zapretik.sh"
echo "  Сервис:         sudo systemctl start zapretik"
echo "  Автозапуск:     sudo systemctl enable zapretik"
echo "  Статус:         systemctl status zapretik"
echo "  Остановить:     sudo systemctl stop zapretik"
echo ""
echo "Для Arch Linux также доступен AUR-пакет: zapretik-bin"
