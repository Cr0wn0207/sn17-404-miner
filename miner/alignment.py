"""A deterministic silhouette shortlist; final adoption always needs visual votes.

Only analysis masks are produced. No reference pixels become output textures.
No fitted weights or benchmark labels are used.
"""

import io
import math
import statistics

from PIL import Image, ImageChops, ImageFilter

SIDE = 96


def foreground(image, *, reference=False):
    with Image.open(io.BytesIO(image)) as original:
        rgb = original.convert("RGB")
        rgb.thumbnail((384, 384), Image.Resampling.BILINEAR)
    width, height = rgb.size
    border = [rgb.getpixel((x, y)) for x in range(width) for y in (0, height - 1)]
    border += [rgb.getpixel((x, y)) for y in range(height) for x in (0, width - 1)]
    background = tuple(int(statistics.median(p[c] for p in border)) for c in range(3)) if reference else (255, 255, 255)
    if reference and sum(sum(abs(p[c] - background[c]) for c in range(3)) for p in border) > len(border) * 36:
        return None
    difference = ImageChops.difference(rgb, Image.new("RGB", rgb.size, background))
    channels = difference.split()
    distance = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    mask = distance.point(lambda value: 255 if value > (36 if reference else 24) else 0)
    # Remove isolated compression speckles. A failure to segment disables search.
    mask = mask.filter(ImageFilter.MedianFilter(3))
    count = sum(mask.histogram()[1:])
    if not .015 * width * height < count < .90 * width * height:
        return None
    box = mask.getbbox()
    mask = mask.crop(box)
    aspect = mask.width / mask.height
    side = max(mask.size)
    square = Image.new("L", (side, side))
    square.paste(mask, ((side - mask.width) // 2, (side - mask.height) // 2))
    return square.resize((SIDE, SIDE), Image.Resampling.BILINEAR).tobytes(), aspect


def similarity(reference, grid):
    target = foreground(reference, reference=True)
    if target is None:
        return None
    target_mask, target_aspect = target
    scores = []
    with Image.open(io.BytesIO(grid)) as image:
        for index in range(4):
            x, y = index % 2, index // 2
            tile = image.crop((x * image.width // 2, y * image.height // 2,
                               (x + 1) * image.width // 2, (y + 1) * image.height // 2))
            buffer = io.BytesIO()
            tile.save(buffer, "PNG")
            view = foreground(buffer.getvalue())
            if view is None:
                scores.append(-2.)
                continue
            mask, aspect = view
            intersection = sum(min(a, b) for a, b in zip(target_mask, mask))
            union = sum(max(a, b) for a, b in zip(target_mask, mask))
            scores.append(intersection / union - .20 * abs(math.log(aspect / target_aspect)))
    return round(sum(scores) / 4, 8)
