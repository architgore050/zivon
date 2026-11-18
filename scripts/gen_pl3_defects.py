#!/usr/bin/env python3
"""Generate the six remaining PL3 seeded-defect artifacts (one-time fixture script).

Each defect is a minimal otherwise-valid artifact document violating exactly
one hard-lint class, so DET-PL03-LINT can assert the expected rule id.
"""

from pathlib import Path

DEFECTS_DIR = (
    Path(__file__).resolve().parent.parent
    / "evals/goldens/personalized/artifacts/defects"
)

HEADER = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; frame-src 'none'; child-src 'none'; worker-src 'none'; media-src 'none'; form-action 'none'; base-uri 'none'">
  <style>body { background: #F6F0CF; color: #1C1B18; }</style>
</head>
<body>
  <main class="zn-art" aria-labelledby="art-title">
    <h1 id="art-title">@TITLE@</h1>
@BODY@    <p class="zn-art-read" aria-live="polite">seeded defect</p>
  </main>
  <script>
@SCRIPT@  </script>
</body>
</html>
"""

READY = "    window.parent.postMessage({ source: 'zivon-artifact', v: 1, type: 'ready' }, '*');\n"

CANVAS = (
    '    <canvas width="480" height="320" role="img" aria-label="@ARIA@"></canvas>\n'
)


def artifact(title: str, body: str, script: str) -> str:
    return (
        HEADER.replace("@TITLE@", title)
        .replace("@BODY@", body)
        .replace("@SCRIPT@", script)
    )


def main() -> None:
    DEFECTS_DIR.mkdir(parents=True, exist_ok=True)

    (DEFECTS_DIR / "eval.html").write_text(
        artifact(
            "Eval simulation",
            CANVAS.replace("@ARIA@", "A canvas that reaches for eval"),
            "    // Seeded defect SD-PL03-02: dynamic code evaluation.\n"
            "    // Expected lint rule: LINT_EVAL.\n"
            "    var fn = eval('(function () { return 1; })');\n" + READY,
        ),
        encoding="utf-8",
    )

    (DEFECTS_DIR / "localstorage.html").write_text(
        artifact(
            "Storage simulation",
            CANVAS.replace("@ARIA@", "A canvas that tries to persist state"),
            "    // Seeded defect SD-PL03-03: storage access from the opaque origin.\n"
            "    // Expected lint rule: LINT_STORAGE.\n"
            "    window.localStorage.setItem('zivon-defect', 'nope');\n" + READY,
        ),
        encoding="utf-8",
    )

    (DEFECTS_DIR / "form.html").write_text(
        artifact(
            "Form simulation",
            '    <form action="https://evil.example.com/collect">\n'
            '      <label for="q">Guess</label>\n'
            '      <input id="q" type="range" min="0" max="10" step="1" value="5">\n'
            "    </form>\n"
            + CANVAS.replace("@ARIA@", "A canvas beside a forbidden form"),
            READY,
        ),
        encoding="utf-8",
    )

    (DEFECTS_DIR / "topnav-link.html").write_text(
        artifact(
            "Top navigation simulation",
            '    <a href="https://evil.example.com/phish">click me</a>\n'
            + CANVAS.replace("@ARIA@", "A canvas beside a top-navigation anchor"),
            READY,
        ),
        encoding="utf-8",
    )

    (DEFECTS_DIR / "missing-label.html").write_text(
        artifact(
            "Unlabelled control simulation",
            '    <input id="a" type="range" min="0" max="10" step="1" value="5">\n'
            + CANVAS.replace("@ARIA@", "A canvas with an unlabelled control"),
            READY,
        ),
        encoding="utf-8",
    )

    # oversized: a valid document padded past the 120 KB cap with HTML comments
    pad = "<!-- " + ("z" * 200) + " -->\n"
    padded = artifact(
        "Oversized simulation",
        '    <label for="u">Object distance (cm)</label>\n'
        '    <input id="u" type="range" min="5" max="60" step="1" value="30">\n'
        + CANVAS.replace("@ARIA@", "A padded oversized artifact"),
        "    // Seeded defect SD-PL03-06: the artifact exceeds the 120 KB budget.\n"
        "    // Expected lint rule: LINT_SIZE.\n" + READY,
    ).replace("</head>", (pad * 700) + "</head>")
    (DEFECTS_DIR / "oversized.html").write_text(padded, encoding="utf-8")

    for name in (
        "eval",
        "localstorage",
        "form",
        "topnav-link",
        "missing-label",
        "oversized",
    ):
        path = DEFECTS_DIR / f"{name}.html"
        print(f"{path.name}: {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
