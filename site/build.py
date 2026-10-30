"""Assemble the site into single-file pages.

dist/index.html       page fragment for the claude.ai Artifact host (it supplies the document skeleton)
dist/standalone.html  complete HTML document for any static host (GitHub Pages, Netlify, S3 ...)
Usage: python3 build.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
D3 = '<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>'


def main():
    page = (ROOT / "src" / "page.html").read_text()
    data = (ROOT / "data" / "data.js").read_text()
    app = (ROOT / "src" / "app.js").read_text()
    scripts = f"{D3}\n<script>\n{data}</script>\n<script>\n{app}</script>\n"
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text(page + "\n" + scripts)
    head, body = page.split("</style>", 1)
    share = (  # link previews and favicon for public hosting (the artifact host supplies its own)
        '<meta property="og:type" content="website">\n'
        '<meta property="og:title" content="Greatest of All Time">\n'
        '<meta property="og:description" content="21 football legends, 16 criteria, a ranking you control and a Monte Carlo test of how stable it is.">\n'
        '<meta name="twitter:card" content="summary">\n'
        '<meta name="theme-color" content="#0f3d2d">\n'
        '<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22%3E%3Crect width=%2264%22 height=%2264%22 rx=%2212%22 fill=%22%230f3d2d%22/%3E%3Ccircle cx=%2232%22 cy=%2232%22 r=%2216%22 fill=%22none%22 stroke=%22%23edf3ee%22 stroke-width=%225%22/%3E%3Cline x1=%2232%22 y1=%220%22 x2=%2232%22 y2=%2264%22 stroke=%22%23edf3ee%22 stroke-width=%225%22/%3E%3C/svg%3E">\n'
    )
    standalone = (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f"{share}{head}</style>\n</head>\n<body>\n{body}\n{scripts}</body>\n</html>\n"
    )
    (out / "standalone.html").write_text(standalone)
    # The repository root's index.html is the hosted site (GitHub Pages, Vercel, Netlify, Cloudflare Pages)
    (ROOT.parent / "index.html").write_text(standalone)
    for f in ("index.html", "standalone.html"):
        print(f, (out / f).stat().st_size, "bytes")


if __name__ == "__main__":
    main()
