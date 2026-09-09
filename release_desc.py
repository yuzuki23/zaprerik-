# -*- coding: utf-8 -*-
"""Единый шаблон описания релиза на GitVerse.

Используется и gitverse_release.py, и _edit_release.py, чтобы тексты
не расходились. build_desc(version) возвращает markdown-описание релиза.
"""
from typing import Optional

# Что нового по текущей версии (для верхней — список «Что нового»).
_CHANGES: dict = {
    "5.0.6": [
        "service.bat: проверка обновлений переведена на GitVerse API (ссылка на старый GitHub-репозиторий не работала)",
        "bump_version.py: при повышении версии обновляет fallback-версии и в main.py, и в care.py",
    ],
    "5.0.5": [
        "Единый источник версии: config.json, скрипт bump_version.py (main.py и care.py читают версию из config)",
        "gitverse_release.py: дебаг-скриншоты пишутся во временную папку, не засоряют рабочую",
        "Единый шаблон описания релиза (release_desc.py) для gitverse_release.py и _edit_release.py",
    ],
    "5.0.4": [
        "watchdog: корректное имя активной стратегии обхода (в т.ч. с пробелами и скобками, напр. «general (ALT2).bat»)",
    ],
}

# Краткая строка «Правки vX.Y.Z: …» для предыдущих версий (выводится автоматически для всех версий старше текущей).
_VERSION_SUMMARIES: dict = {
    "5.0.5": "единый источник версии (config.json), bump_version.py, шаблон описания release_desc.py, скриншоты релизера во временную папку",
    "5.0.4": "watchdog: корректное имя активной стратегии обхода (пробелы и скобки в имени)",
    "5.0.3": "валидация версии X.Y.Z, DNS-timeout в care.py, автоочистка логов, уведомление о смене стратегии",
    "5.0.2": "валидация типов в config.json, автообновление timestamp в status.json, проверка Discord перед уведомлением, fallback стратегии",
}


def _version_key(ver: str) -> tuple:
    return tuple(int(part) for part in ver.split("."))


def build_desc(version: Optional[str] = None) -> str:
    """Markdown-описание релиза Zapretik."""
    ver = version or "5.0.6"
    tag = f"v{ver}"
    lines = [f"## Zapretik {ver}", "", "### Что нового:"]
    for item in _CHANGES.get(ver, ["Внутренние правки и обслуживание."]):
        lines.append(f"- {item}")

    prev = [v for v in sorted(_VERSION_SUMMARIES, key=_version_key, reverse=True) if v < ver]
    if prev:
        lines.append("")
        lines.append("### Правки:")
        for v in prev:
            lines.append(f"- Правки v{v}: {_VERSION_SUMMARIES[v]}")

    lines += ["", "### Файлы:", f"- zaprerik-{tag}.rar — Windows"]
    return "\n".join(lines)


if __name__ == "__main__":
    print(build_desc())