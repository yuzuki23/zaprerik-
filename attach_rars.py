import json
import os
import time
import urllib.request

import release

API = "https://api.github.com/repos/yuzuki23/zaprerik-/releases"


def get_releases():
    req = urllib.request.Request(API, headers={"Accept": "application/json", "User-Agent": "zapretik"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def attach_via_edit(page, tag, rar):
    page.goto(release.release_edit_url(tag), wait_until="domcontentloaded")
    page.wait_for_url(f"**/releases/edit/{tag}", timeout=60000)
    page.wait_for_selector(".ProseMirror", timeout=15000)
    page.wait_for_timeout(500)
    fi = page.locator('input[type="file"]')
    if fi.count() == 0:
        return False, "нет file input"
    fi.first.set_input_files(str(rar))
    page.wait_for_timeout(1500)
    save = page.locator('button:has-text("Сохранить")')
    if save.count() == 0:
        return False, "нет кнопки сохранения"
    save.first.scroll_into_view_if_needed()
    save.first.click()
    try:
        page.wait_for_function("() => !location.href.includes('/edit/')", timeout=30000)
        return True, page.url
    except Exception as e:
        return False, f"no-nav: {e}"


def has_attachment(tag, fname):
    rels = get_releases()
    for r in rels:  # GitHub returns array directly
        if r["tag_name"] == tag:
            for a in (r.get("assets") or []):
                if a.get("name") == fname:
                    return True
    return False


def main():
    ONLY = os.environ.get("ONLY")
    _, _, page = release.connect()
    tags = release.git_tags()
    if ONLY:
        tags = [t for t in tags if t == ONLY]
    rels = get_releases()
    by_tag = {r["tag_name"]: r for r in rels}  # GitHub uses tag_name
    prev = None
    for tag in tags:
        rar = release.build_rar_for_tag(tag)
        fname = rar.name
        if by_tag.get(tag) and has_attachment(tag, fname):
            print(f"[=] {tag}: уже прикреплено {fname}")
            prev = tag
            continue
        print(f"[*] {tag}: rar={rar.name}", flush=True)
        try:
            ok, msg = attach_via_edit(page, tag, rar)
            if not ok:
                print(f"  edit не прошёл ({msg}) -> удаляю и пересоздаю", flush=True)
                release.delete_release(page, tag)
                ok, msg = release.create_release(page, tag, prev, asset_path=rar)
            print(f"[{'+' if ok else '!'}] {tag}: {msg}", flush=True)
        except Exception as e:
            print(f"[!] {tag}: {e!r}", flush=True)
        prev = tag
        time.sleep(1)
    print("[*] готово", flush=True)


if __name__ == "__main__":
    main()
