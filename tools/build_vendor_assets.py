#!/usr/bin/env python3
"""Rebuild the vendored Web UI assets under src/docsifter/static/vendor/.

DocSifter reviews documentation on machines that are often offline or on a
closed network, so the Web UI must not reach a CDN to render. This script
downloads the upstream releases once, cuts Tailwind down to the utility classes
the UI actually references, and writes the result into the package.

Run it after changing the markup or the front-end scripts:

    python3 tools/build_vendor_assets.py

then review the diff and commit the regenerated files. It needs network access;
nothing at run time does.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = REPO_ROOT / "src" / "docsifter" / "static" / "vendor"

TAILWIND_VERSION = "2.2.19"
TAILWIND_URL = f"https://cdn.jsdelivr.net/npm/tailwindcss@{TAILWIND_VERSION}/dist/tailwind.min.css"

FONTAWESOME_VERSION = "6.0.0"
FONTAWESOME_BASE = f"https://cdnjs.cloudflare.com/ajax/libs/font-awesome/{FONTAWESOME_VERSION}"
# Only the styles the UI uses: fas (solid) and fab (brands). fa-regular is not
# referenced, and shipping it would add a webfont nothing loads.
FONTAWESOME_WEBFONTS = ("fa-solid-900.woff2", "fa-brands-400.woff2")

# Files scanned for class names. Every class in the UI is a literal token, in
# markup or in a string literal, so a plain token sweep finds them all.
SOURCE_FILES = (
    REPO_ROOT / "src" / "docsifter" / "templates" / "index.html",
    REPO_ROOT / "src" / "docsifter" / "static" / "js" / "app.js",
    REPO_ROOT / "src" / "docsifter" / "static" / "js" / "i18n.js",
)

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9:/._-]*")
# A class in a selector, with CSS escapes: ".md\:w-1\/2" -> "md:w-1/2".
SELECTOR_CLASS_RE = re.compile(r"\.((?:\\.|[A-Za-z0-9_-])+)")


def fetch(url: str) -> bytes:
    print(f"  fetching {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "docsifter-vendor-build"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return response.read()


def collect_used_tokens() -> set[str]:
    """Every token in the UI sources that could name a CSS class."""
    tokens: set[str] = set()
    for path in SOURCE_FILES:
        tokens.update(TOKEN_RE.findall(path.read_text(encoding="utf-8")))
    return tokens


def split_top_level(css: str) -> list[str]:
    """Split minified CSS into top-level blocks, keeping at-rules whole."""
    blocks, depth, start = [], 0, 0
    for index, char in enumerate(css):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                blocks.append(css[start : index + 1])
                start = index + 1
    return blocks


def unescape_class(name: str) -> str:
    return re.sub(r"\\(.)", r"\1", name)


def selector_is_used(selector: str, tokens: set[str]) -> bool:
    """Keep base styles, and keep a utility only if the UI names its class."""
    classes = SELECTOR_CLASS_RE.findall(selector)
    if not classes:
        # Element, :root, ::before and other base rules: preflight, keep it.
        return True
    return any(unescape_class(name) in tokens for name in classes)


def filter_rule(block: str, tokens: set[str]) -> str | None:
    prelude, _, body = block.partition("{")
    kept = [part for part in prelude.split(",") if selector_is_used(part, tokens)]
    if not kept:
        return None
    if len(kept) == len(prelude.split(",")):
        return block
    return ",".join(kept) + "{" + body


def subset_tailwind(css: str, tokens: set[str]) -> str:
    """Drop every utility rule the UI never references."""
    kept: list[str] = []
    for block in split_top_level(css):
        prelude = block.partition("{")[0].strip()

        if prelude.startswith("@media") or prelude.startswith("@supports"):
            inner = block[block.index("{") + 1 : block.rindex("}")]
            inner_kept = [
                filtered
                for rule in split_top_level(inner)
                if (filtered := filter_rule(rule, tokens))
            ]
            if inner_kept:
                kept.append(prelude + "{" + "".join(inner_kept) + "}")
            continue

        if prelude.startswith("@"):
            # @keyframes, @font-face, @charset: cheap and order-sensitive, keep.
            kept.append(block)
            continue

        filtered = filter_rule(block, tokens)
        if filtered:
            kept.append(filtered)

    return "".join(kept)


def build(offline: bool = False) -> None:
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    tokens = collect_used_tokens()
    print(f"scanned {len(SOURCE_FILES)} source file(s): {len(tokens)} candidate token(s)")

    print("tailwind:")
    tailwind_css = fetch(TAILWIND_URL).decode("utf-8")
    subset = subset_tailwind(tailwind_css, tokens)
    header = (
        f"/*! Tailwind CSS v{TAILWIND_VERSION} | MIT License | tailwindcss.com\n"
        " * Subset generated by tools/build_vendor_assets.py: only the utility\n"
        " * classes referenced by the DocSifter Web UI are kept. Re-run that\n"
        " * script after changing the markup or the front-end scripts. */\n"
    )
    (VENDOR_DIR / "tailwind.min.css").write_text(header + subset, encoding="utf-8")
    print(f"  {len(tailwind_css) / 1024:.0f} KB upstream -> {len(subset) / 1024:.0f} KB subset")

    print("font awesome:")
    fa_css = fetch(f"{FONTAWESOME_BASE}/css/all.min.css").decode("utf-8")
    # Upstream points at ../webfonts/; everything sits side by side here.
    fa_css = fa_css.replace("../webfonts/", "./")
    fa_header = (
        f"/*! Font Awesome Free {FONTAWESOME_VERSION} | fontawesome.com\n"
        " * Icons: CC BY 4.0 | Fonts: SIL OFL 1.1 | Code: MIT License\n"
        " * Vendored by tools/build_vendor_assets.py so the UI renders offline. */\n"
    )
    (VENDOR_DIR / "fontawesome.min.css").write_text(fa_header + fa_css, encoding="utf-8")

    for webfont in FONTAWESOME_WEBFONTS:
        data = fetch(f"{FONTAWESOME_BASE}/webfonts/{webfont}")
        (VENDOR_DIR / webfont).write_bytes(data)
        print(f"  {webfont}: {len(data) / 1024:.0f} KB")

    total = sum(path.stat().st_size for path in VENDOR_DIR.iterdir() if path.is_file())
    print(f"vendor total: {total / 1024:.0f} KB")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
