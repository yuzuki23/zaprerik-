# -*- coding: utf-8 -*-
"""Тост-уведомления в системном трее (через PowerShell NotifyIcon).

Общая реализация для care.py и watchdog.py: отправляет тост, не блокируя
вызывающий процесс (Popen + Application.Run в отдельном powershell).
"""
import os
import subprocess
from pathlib import Path


def _safe(text: str, limit: int = 200) -> str:
    """Подготавливает текст для встраивания в одинарные кавычки PowerShell:
    убирает переносы строк и типографические апострофы вместо служебных."""
    return str(text).replace("\r", " ").replace("\n", " ").replace("'", "’")[:limit]


def notify(title: str, text: str) -> None:
    """Показывает тост в трее. title/text — любые строки, экранирование внутри."""
    path = Path(os.environ.get("TEMP", r"C:\запрет")) / "care_notify.ps1"
    ps1 = (
        "Add-Type -AssemblyName System.Windows.Forms\n"
        "Add-Type -AssemblyName System.Drawing\n"
        "$n=New-Object System.Windows.Forms.NotifyIcon\n"
        "$n.Icon=[System.Drawing.SystemIcons]::Information\n"
        "$n.Visible=$true\n"
        f"$n.ShowBalloonTip(15000,'{_safe(title)}','{_safe(text)}',[System.Windows.Forms.ToolTipIcon]::Info)\n"
        "$t=New-Object System.Windows.Forms.Timer\n"
        "$t.Interval=16000\n"
        "$t.Add_Tick({$n.Visible=$false;$n.Dispose();[System.Windows.Forms.Application]::Exit()})\n"
        "$t.Start()\n"
        "[System.Windows.Forms.Application]::Run()\n"
    )
    try:
        path.write_text(ps1, encoding="utf-8-sig")
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
             "-ExecutionPolicy", "Bypass", "-File", str(path)],
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except Exception:
        pass