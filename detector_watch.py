import json
import datetime
from playwright.sync_api import sync_playwright

URL = "https://detector404.ru/"
LOG = r"C:\запрет\detector_trend.log"

STATUS_OK = {"Работает"}
STATUS_BAD = {"Жалобы", "Сбой сети", "Сбой"}
ALL_STATUS = STATUS_OK | STATUS_BAD

REGIONS = {
    "Москва", "Московская область", "Самарская область", "Санкт-Петербург",
    "Нижегородская область", "Нижегородская обл", "Омская область",
    "Ростовская область", "Казань", "Новосибирск", "Екатеринбург",
    "Владимирская область", "Астраханская область", "Республика Карелия",
    "Омская область",
}


def parse_pairs(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    pairs = []
    seen = set()
    for i in range(1, len(lines)):
        if lines[i] in ALL_STATUS:
            n = lines[i - 1]
            if n and n not in ALL_STATUS and n not in seen:
                seen.add(n)
                pairs.append((n, lines[i]))
    return pairs


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome", headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        page = browser.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_function(
            "document.body && document.body.innerText.includes('Жалобы')",
            timeout=30000,
        )
        text = page.evaluate("document.body.innerText")
        browser.close()

    pairs = parse_pairs(text)
    services = [(n, s) for n, s in pairs if n not in REGIONS and n.lower() != "discord"]
    regions = [(n, s) for n, s in pairs if n in REGIONS]
    bad = [(n, s) for n, s in services if s != "Работает"]

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary = {
        "ts": ts,
        "services_total": len(services),
        "services_ok": len(services) - len(bad),
        "services_bad": len(bad),
        "bad_services": bad,
        "regions": regions,
    }

    line = (f"{ts} | сервисов: {len(services)} "
            f"(ok {summary['services_ok']}, жалобы/сбой {len(bad)}) | "
            f"регионы_жалобы: " +
            ", ".join(n for n, s in regions if s != "Работает"))
    print(line)
    print("ПРОБЛЕМЫ: " + (", ".join(f"{n}={s}" for n, s in bad) or "нет"))
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
