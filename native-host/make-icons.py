r"""
make-icons.py - draws the extension's three toolbar icons.

Run once; the PNGs it writes are checked in beside the extension. Uses only the
standard library, so there is nothing to install:

    ..\.venv\Scripts\python.exe make-icons.py

A blue circle with a white download arrow. Change COLOUR to recolour it.
"""

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "chrome-extension"
COLOUR = (59, 125, 221)  # the blue used for the progress badge


def png_bytes(size, pixels):
    """Assemble a PNG file. pixels is a list of rows of (r, g, b, a) tuples."""

    def chunk(tag, payload):
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    # Colour type 6 = RGBA, bit depth 8. Each row is prefixed with filter byte 0.
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    raw = bytearray()
    for row in pixels:
        raw.append(0)
        for r, g, b, a in row:
            raw += bytes((r, g, b, a))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def draw(size):
    """One icon: white arrow and bar on a filled blue circle."""
    rows = []
    centre = size / 2.0
    radius = size / 2.0 - 0.5

    for y in range(size):
        row = []
        for x in range(size):
            # Pixel centres, so the shapes sit straight at every size.
            px, py = x + 0.5, y + 0.5
            fx, fy = px / size, py / size  # 0..1, so one set of numbers fits all sizes

            inside_circle = (px - centre) ** 2 + (py - centre) ** 2 <= radius**2
            if not inside_circle:
                row.append((0, 0, 0, 0))
                continue

            # Arrow stem.
            white = 0.435 <= fx <= 0.565 and 0.20 <= fy <= 0.56
            # Arrow head: a triangle that narrows to a point at fy = 0.78.
            if 0.52 <= fy <= 0.78:
                half = 0.20 * (0.78 - fy) / 0.26
                if abs(fx - 0.5) <= half:
                    white = True
            # The line it lands on.
            if 0.82 <= fy <= 0.88 and 0.28 <= fx <= 0.72:
                white = True

            row.append((255, 255, 255, 255) if white else (*COLOUR, 255))
        rows.append(row)
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (16, 48, 128):
        path = OUT / f"icon{size}.png"
        path.write_bytes(png_bytes(size, draw(size)))
        print(f"wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
