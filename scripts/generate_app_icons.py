from __future__ import annotations

import struct
import zlib
from math import hypot
from pathlib import Path

SUPERSAMPLE = 4
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "app" / "static" / "icons"


def distance_to_segment(
    x: float, y: float, start: tuple[float, float], end: tuple[float, float]
) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    position = max(0.0, min(1.0, ((x - start[0]) * dx + (y - start[1]) * dy) / length_squared))
    nearest_x = start[0] + position * dx
    nearest_y = start[1] + position * dy
    return hypot(x - nearest_x, y - nearest_y)


def is_white(x: float, y: float) -> bool:
    circle_distance = hypot(x - 256, y - 256)
    on_circle = 117 <= circle_distance <= 155
    on_check = min(
        distance_to_segment(x, y, (183, 258), (233, 308)),
        distance_to_segment(x, y, (233, 308), (334, 196)),
    ) <= 21
    return on_circle or on_check


def png_chunk(name: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))


def create_icon(size: int) -> bytes:
    rows = bytearray()
    for output_y in range(size):
        rows.append(0)
        for output_x in range(size):
            white_samples = 0
            for sample_y in range(SUPERSAMPLE):
                for sample_x in range(SUPERSAMPLE):
                    x = (output_x + (sample_x + 0.5) / SUPERSAMPLE) * 512 / size
                    y = (output_y + (sample_y + 0.5) / SUPERSAMPLE) * 512 / size
                    white_samples += is_white(x, y)
            channel = round(255 * white_samples / (SUPERSAMPLE * SUPERSAMPLE))
            rows.extend((channel, channel, channel))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(bytes(rows), level=9))
        + png_chunk(b"IEND", b"")
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for size in (180, 192, 512):
        (OUTPUT_DIR / f"app-icon-{size}.png").write_bytes(create_icon(size))


if __name__ == "__main__":
    main()
