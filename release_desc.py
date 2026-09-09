# -*- coding: utf-8 -*-
"""Единый шаблон описания релиза на GitVerse.

Используется и gitverse_release.py, и _edit_release.py, чтобы тексты
не расходились. build_desc(version) возвращает markdown-описание релиза.
"""
from typing import List, Optional

# Что нового по версиям (для верхней — список «Что нового»).
_CHANGES: dict = {
    "5.0.5": [
        "Единый источник версии: config.json, скрипт bump_version.py (main.py и care.py читают версию из config)",
        "gitverse_release.py: дебаг-скриншоты пишутся во временную папку, не засоряют рабочую",
        "Единый шаблон описания релиза (release_desc.py) для gitverse_release.py и _edit_release.py",
    ],
    "5.0.4": [
        "watchdog: корректное имя активной стратегии обхода (в т.ч. с пробелами и скобками, напр. «general (ALT2).bat»)",
    ],
}

# Краткая строка «Правки <версия>: …» для предыдущих версий.
_PREV_SUMMARY: List[str] = [
    "Правки v5.0.3: валидация версии X.Y.Z, DNS-timeout в care.py, автоочистка логов, уведомление о смене стратегии",
    "Правки v5.0.2: валидация типов в config.json, автообновление timestamp в status.json, проверка Discord перед уведомлением, fallback стратегии",
]


def build_desc(version: Optional[str] = None) -> str:
    """Markdown-описание релиза Zapretik."""
    ver = version or "5.0.5"
    tag = f"v{ver}"
    lines = [f"## Zapretik {ver}", "", "### Что нового:"]
    for item in _CHANGES.get(ver, ["Без изменений в скриптах (технический выпуск)."]):
        lines.append(f"- {item}")
    for s in _PREV_SUMMARY:
        lines.append(f"- {s}")
    lines += ["", "### Файлы:", f"- zaprerik-{tag}.rar — Windows"]
    return "\n".join(lines)


if __name__ == "__main__":
    print(build_desc())