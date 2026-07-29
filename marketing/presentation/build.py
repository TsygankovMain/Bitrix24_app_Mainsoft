#!/usr/bin/env python3
"""Собирает три self-contained презентации из общих исходников.

    python3 marketing/presentation/build.py

Читает _src/ и пишет рядом cold.html, warm.html, agency.html — каждый файл
без единого внешнего запроса, открывается по file:// и отправляется клиенту
одним вложением.

Стили, движок слайдов и мокапы лежат в одном экземпляре: правка мокапа
автоматически попадает во все три презентации.
"""

import re
import sys
from pathlib import Path

SRC = Path(__file__).parent / "_src"
OUT = Path(__file__).parent

TRACKS = {
    "cold":   "Учёт трудозатрат в Битрикс24 — куда уходят часы вашей команды",
    "warm":   "Учёт трудозатрат в Битрикс24 — как это работает",
    "agency": "Учёт трудозатрат в Битрикс24 — для агентств",
}

MOCKUP_BLOCK = re.compile(
    r"<!--@mockup:([a-z0-9\-]+)-->(.*?)<!--@end-->",
    re.DOTALL,
)
MOCKUP_SLOT = re.compile(r"[ \t]*<!--mockup:([a-z0-9\-]+)-->")


def read(name: str) -> str:
    path = SRC / name
    if not path.exists():
        sys.exit(f"нет файла {path}")
    return path.read_text(encoding="utf-8")


def load_mockups() -> dict:
    raw = read("mockups.html")
    mockups = {key: body.strip() for key, body in MOCKUP_BLOCK.findall(raw)}
    if not mockups:
        sys.exit("в mockups.html не нашлось ни одного блока <!--@mockup:...-->")
    return mockups


def build(track: str, title: str, shell: str, css: str, js: str, mockups: dict) -> int:
    slides = read(f"{track}.html")
    used = []
    missing = []

    def substitute(match):
        key = match.group(1)
        if key not in mockups:
            missing.append(key)
            return match.group(0)
        used.append(key)
        return mockups[key]

    slides = MOCKUP_SLOT.sub(substitute, slides)
    if missing:
        sys.exit(f"{track}.html: нет мокапов {sorted(set(missing))}")

    html = (
        shell.replace("{{TITLE}}", title)
        .replace("{{CSS}}", css)
        .replace("{{JS}}", js)
        .replace("{{SLIDES}}", slides.strip())
    )

    target = OUT / f"{track}.html"
    target.write_text(html, encoding="utf-8")

    count = len(re.findall(r'<section class="slide\b', slides))
    size = len(html.encode("utf-8")) // 1024
    print(f"  {target.name:12} {count:2} слайдов · {len(used)} мокапов · {size} КБ")
    return count


def main() -> None:
    shell = read("shell.html")
    css = read("deck.css")
    js = read("deck.js")
    mockups = load_mockups()

    print(f"Мокапов в библиотеке: {len(mockups)}")
    for track, title in TRACKS.items():
        build(track, title, shell, css, js, mockups)
    print("Готово.")


if __name__ == "__main__":
    main()
