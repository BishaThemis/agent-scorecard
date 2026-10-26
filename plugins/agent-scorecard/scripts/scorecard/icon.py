"""App icon drawn in code: three rising bars (silver, accent, gold) on a dark tile with a thin border,
matching the dashboard theme. No image files or packages: PNG is encoded by hand with zlib, and ICO
files simply embed those PNGs."""
import base64
import struct
import zlib
from pathlib import Path

TILE = (0x1B, 0x1F, 0x26)      # card
BORDER = (0x3D, 0x46, 0x54)    # border
BARS = ((0xB9, 0xC1, 0xCD), (0x8A, 0xA4, 0xFF), (0xEC, 0xD2, 0x5E))   # silver, accent, gold
SIZES = (16, 32, 48, 256)


def _inside(cx: float, cy: float, size: float, inset: float, radius: float) -> float:
    """Coverage (0..1) of a rounded square inset by `inset`, with a one-pixel soft edge."""
    lo, hi = inset, size - inset
    r = max(radius - inset, 0.5)
    dx = max(lo + r - cx, 0, cx - (hi - r))
    dy = max(lo + r - cy, 0, cy - (hi - r))
    if cx < lo - 0.5 or cx > hi + 0.5 or cy < lo - 0.5 or cy > hi + 0.5:
        return 0.0
    return max(0.0, min(1.0, r + 0.5 - (dx * dx + dy * dy) ** 0.5))


def _pixels(size: int) -> list[list[tuple[int, int, int, int]]]:
    u = size / 32
    radius = 7 * u
    border = max(1.0, 1.5 * u)
    bars = ((6, 8), (13, 13), (20, 19))      # (x, height) on a 32-unit grid, bars 6 units wide
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            cx, cy = x + 0.5, y + 0.5
            outer = _inside(cx, cy, size, 0, radius)
            color = BORDER if _inside(cx, cy, size, border, radius) < 0.5 else TILE
            for (bx, bh), bar in zip(bars, BARS):
                if bx * u <= cx < (bx + 6) * u and (26 - bh) * u <= cy < 26 * u:
                    color = bar
            row.append((*color, round(outer * 255)))
        rows.append(row)
    return rows


def png(size: int) -> bytes:
    raw = b"".join(b"\x00" + bytes(c for px in row for c in px) for row in _pixels(size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)   # 8-bit RGBA
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def write_ico(path: Path) -> None:
    images = [png(s) for s in SIZES]
    offset = 6 + 16 * len(images)
    out = struct.pack("<HHH", 0, 1, len(images))
    for size, data in zip(SIZES, images):
        dim = 0 if size >= 256 else size   # 0 means 256 in the ICO directory
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    Path(path).write_bytes(out + b"".join(images))


def photo_data(size: int = 32) -> str:
    """Base64 PNG for tk.PhotoImage(data=...)."""
    return base64.b64encode(png(size)).decode("ascii")
