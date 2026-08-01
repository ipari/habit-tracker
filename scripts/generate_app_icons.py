from __future__ import annotations

import struct
import zlib
from math import hypot
from pathlib import Path

SUPERSAMPLE = 4
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "app" / "static" / "icons"
TRANSPARENT = (0, 0, 0, 0)
WHITE = (255, 255, 255, 255)
BORDER = (232, 232, 234, 255)
SHADOW = (17, 24, 39, 42)


def gradient(
    start: tuple[int, int, int, int],
    end: tuple[int, int, int, int],
    position: float,
) -> tuple[int, int, int, int]:
    amount = max(0.0, min(1.0, position))
    return tuple(
        round(first + (second - first) * amount)
        for first, second in zip(start, end, strict=True)
    )


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


def inside_rounded_rect(
    x: float,
    y: float,
    *,
    left: float,
    top: float,
    right: float,
    bottom: float,
    radius: float,
) -> bool:
    nearest_x = max(left + radius, min(right - radius, x))
    nearest_y = max(top + radius, min(bottom - radius, y))
    return (
        left <= x <= right
        and top <= y <= bottom
        and hypot(x - nearest_x, y - nearest_y) <= radius
    )


def icon_color(x: float, y: float, *, maskable: bool) -> tuple[int, int, int, int]:
    shadow_tile = inside_rounded_rect(
        x, y, left=28, top=35, right=484, bottom=491, radius=108
    )
    outer_tile = inside_rounded_rect(
        x, y, left=32, top=32, right=480, bottom=480, radius=104
    )
    if not outer_tile and not maskable:
        return SHADOW if shadow_tile else TRANSPARENT

    color = gradient(WHITE, (250, 250, 250, 255), (x + y) / 1024)
    inner_tile = inside_rounded_rect(
        x, y, left=36, top=36, right=476, bottom=476, radius=100
    )
    if outer_tile and not inner_tile:
        color = BORDER

    if hypot(x - 256, y - 256) <= 142:
        color = (52, 199, 89, 255)

    on_check = min(
        distance_to_segment(x, y, (194, 258), (236, 300)),
        distance_to_segment(x, y, (236, 300), (318, 208)),
    ) <= 17
    if on_check:
        color = WHITE
    return color


def png_chunk(name: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))


def create_icon(size: int, *, maskable: bool = False) -> bytes:
    rows = bytearray()
    samples_per_pixel = SUPERSAMPLE * SUPERSAMPLE
    for output_y in range(size):
        rows.append(0)
        for output_x in range(size):
            samples = []
            for sample_y in range(SUPERSAMPLE):
                for sample_x in range(SUPERSAMPLE):
                    x = (output_x + (sample_x + 0.5) / SUPERSAMPLE) * 512 / size
                    y = (output_y + (sample_y + 0.5) / SUPERSAMPLE) * 512 / size
                    samples.append(icon_color(x, y, maskable=maskable))

            alpha_sum = sum(sample[3] for sample in samples)
            alpha = round(alpha_sum / samples_per_pixel)
            if alpha_sum:
                red = round(sum(sample[0] * sample[3] for sample in samples) / alpha_sum)
                green = round(sum(sample[1] * sample[3] for sample in samples) / alpha_sum)
                blue = round(sum(sample[2] * sample[3] for sample in samples) / alpha_sum)
            else:
                red = green = blue = 0
            rows.extend((red, green, blue, alpha))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
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
    (OUTPUT_DIR / "app-icon-maskable-512.png").write_bytes(create_icon(512, maskable=True))


if __name__ == "__main__":
    main()
