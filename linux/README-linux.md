# Zapretik for Linux

Обёртка над [nfqws](https://github.com/bol-van/zapret) для обхода DPI-блокировок Discord и YouTube в Linux.

Аналог [Zapretik для Windows](https://github.com/yuzuki23/zaprerik-), адаптированный под Linux (Arch, Ubuntu, Debian, Fedora).

## Установка

### Автоматическая (Arch Linux)
```bash
git clone https://github.com/yuzuki23/zaprerik- linux
cd linux
sudo bash install.sh
```

### Ручная
```bash
# Зависимости
sudo pacman -S nfqws  # Arch Linux
# или скачайте nfqws с https://github.com/bol-van/zapret/releases

# Запуск
chmod +x zapretik.sh
sudo ./zapretik.sh
```

## Использование

```bash
# Интерактивное меню
sudo ./zapretik.sh

# Запуск стратегии General
sudo ./zapretik.sh start

# Остановка
sudo ./zapretik.sh stop

# Статус
./zapretik.sh status
```

### Systemd (рекомендуется)
```bash
sudo systemctl start zapretik    # запуск
sudo systemctl enable zapretik   # автозапуск
sudo systemctl status zapretik   # статус
```

## Стратегии

| № | Название | Описание |
|---|----------|----------|
| 1 | Discord + YouTube (Стандарт) | фейковая подмена TLS + фрагментация |
| 2 | Только YouTube (Агрессивный) | перестановка сегментов + фрагментация |
| 3 | Безопасный режим (Медленный) | только фрагментация |
| G | General | полная стратегия из general.bat |

## Файлы

- `zapretik.sh` — основной скрипт (аналог main.py)
- `zapretik.service` — systemd-сервис (аналог service.bat)
- `zapretik-watchdog.sh` — сторож (аналог watchdog.py)
- `lists/` — списки доменов
- `bin/` — бинарники nfqws

## Требования

- Linux (Arch, Ubuntu, Debian, Fedora)
- nfqws (bol-van/zapret)
- root-права
- curl или wget
