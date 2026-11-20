# SPDX-License-Identifier: GPL-2.0-or-later
"""Repaint the lyre's button discs while preserving the surrounding level art.

Disc coordinates and restoration routines adapted from SpartanPort's GPL-2.0-or-later
scripts/glyphs.py, by the SpartanPort contributors:
https://github.com/FelipePrado0/SpartanPort/blob/main/scripts/glyphs.py
"""

import math

LYRE_CORNER = (1536, 0, 2048, 512)
LYRE_DISCS = {"cross": (167, 110), "circle": (395, 110), "square": (167, 335), "triangle": (395, 333)}
LYRE_RADIUS = 110
LYRE_FORMS = {
    "lyre": {"inner": 0.76, "cap": 104, "dark": False},
    "gold": {"inner": 0.68, "cap": 80, "dark": True},
}
LYRE_DIM, LYRE_DECAL, LYRE_SHINE, LYRE_RIM, LYRE_RELIEF = 0.62, 0.83, 190, 80, 1.2
GOLD_LINE = 8


def lyre_level(band, mask, fraction):
    """The value below which `fraction` of the pixels of `band` (an L image) under `mask` fall."""
    histogram = band.histogram(mask=mask)
    wanted, seen = sum(histogram) * fraction, 0
    for value, count in enumerate(histogram):
        seen += count
        if seen >= wanted:
            return value
    return 255


def lyre_letter_mask(disc, inner, dark=False, enclosed=True):
    """An L mask of the letter on `disc` (a square around one disc) and its carved edge, a 5 px
    margin: the pixels inside `inner` brighter (`dark`: darker) than the disc's own interior,
    which is the larger part of it, in the brightest channel. An engraved shape (`dark`) takes
    what it encloses with it, unless `enclosed` is off."""
    from PIL import ImageChops, ImageDraw, ImageFilter
    red, green, blue = disc.split()[:3]
    bright = ImageChops.lighter(red, ImageChops.lighter(green, blue))
    interior = lyre_level(bright, inner, 0.5)
    if dark:
        threshold = interior - (interior - lyre_level(bright, inner, 0.001)) * 0.35
        mask = bright.point(lambda v: 255 if v < threshold else 0)
    else:
        threshold = interior + (lyre_level(bright, inner, 0.999) - interior) * 0.35
        mask = bright.point(lambda v: 255 if v > threshold else 0)
    mask = ImageChops.multiply(ImageChops.multiply(mask, inner).filter(ImageFilter.MaxFilter(11)), inner)
    if dark and enclosed:
        outside = ImageChops.lighter(mask, ImageChops.invert(inner))
        left, top, right, bottom = inner.getbbox()
        # flood from clear points towards the edge, off the diagonals, in every part of the disc
        # the shape's lines divide; what stays unreached is enclosed
        for reach, angle in ((f * (right - left) / 2, a) for f in (0.9, 0.85, 0.8) for a in (15, 75, 105, 165, 195, 255, 285, 345)):
            seed = (int(disc.width / 2 + reach * math.cos(math.radians(angle))),
                    int(disc.height / 2 - reach * math.sin(math.radians(angle))))
            if not outside.getpixel(seed):
                ImageDraw.floodfill(outside, seed, 128)
        mask = ImageChops.lighter(mask, outside.point(lambda v: 255 if v == 0 else 0))
    return mask


def lyre_fill(disc, mask, inner, others, slide=None):
    """`disc` with the pixels under `mask` replaced by the disc's own interior texture: taken
    from `others`, the other discs (each with its mask), matched to this disc's shading, where
    they show no letter, then from the disc turned about its centre, then from the median
    colour. `slide`, the mask of the letter alone, puts the disc's own texture slid sideways
    first (the engraved gold discs)."""
    from PIL import Image, ImageChops, ImageFilter
    clean = ImageChops.subtract(inner, mask)
    medians = tuple(lyre_level(band, clean, 0.5) for band in disc.split())

    def shading(image, hole):
        """The slow changes of tone across `image`, with `hole` filled by the tone around it."""
        around = ImageChops.subtract(ImageChops.multiply(hole.filter(ImageFilter.MaxFilter(25)), inner), hole)
        flat = image.copy()
        flat.paste(tuple(lyre_level(band, around, 0.5) for band in image.split()), mask=hole)
        return flat.filter(ImageFilter.GaussianBlur(10))

    # another disc's pixels are brought to this disc's shading: lighter centre, darker edge
    tone = shading(disc, mask)
    sources = [(ImageChops.add(other, ImageChops.subtract(tone, shading(other, other_mask), 1, 128), 1, -128), other_mask)
               for other, other_mask in others]
    sources += [(source.transpose(turn), source_mask.transpose(turn))
                for source, source_mask in list(sources) for turn in (Image.Transpose.ROTATE_90, Image.Transpose.ROTATE_180, Image.Transpose.ROTATE_270)]
    sources += [(disc.rotate(angle, Image.Resampling.BICUBIC), mask.rotate(angle, Image.Resampling.BICUBIC).point(lambda v: 255 if v else 0))
                for angle in (90, 270, 180, 45, 135, 225, 315, 30, 60, 120, 150, 210, 240, 300, 330)]
    sources.reverse()
    if slide is not None:
        matched = ImageChops.add(disc, ImageChops.subtract(tone, shading(disc, slide), 1, 128), 1, -128)
        for dx, dy in ((40, 0), (-40, 0), (0, 40), (0, -40), (28, 28), (-28, 28), (28, -28), (-28, -28)):
            sources.append((ImageChops.offset(matched, dx, dy),
                            ImageChops.lighter(ImageChops.offset(mask, dx, dy), ImageChops.invert(ImageChops.offset(inner, dx, dy)))))
    filled = disc.copy()
    filled.paste(medians, mask=mask)
    # the best source last, each blended in over the earlier ones with a soft edge
    for source, source_mask in sources:
        usable = ImageChops.subtract(mask, source_mask).filter(ImageFilter.MinFilter(5))
        if usable.getbbox():
            filled = Image.composite(source, filled, ImageChops.multiply(usable.filter(ImageFilter.GaussianBlur(2)), mask))
    result = disc.copy()
    result.paste(filled, mask=mask.filter(ImageFilter.GaussianBlur(1)))
    return result, medians


def lyre_dome(disc, inner, radius):
    """The normal map `disc` (RGBA: X in alpha, Y in green) with the raised letter smoothed away:
    the disc is a dome, so its normals point outward by an amount that depends on the distance
    from the centre; that profile, the median at each distance, replaces the pixels that stray
    from it (the letter's edges, with a margin)."""
    from PIL import Image, ImageChops, ImageFilter
    red, green, blue, alpha = disc.split()
    x_band, y_band = alpha.load(), green.load()
    size = disc.width
    centre = size / 2 - 0.5
    inside = inner.load()
    slant = [[] for _ in range(size)]  # outward tilt by distance, in pixels
    for y in range(size):
        for x in range(size):
            if inside[x, y]:
                dx, dy = x - centre, y - centre
                distance = (dx * dx + dy * dy) ** 0.5
                if distance >= 1:
                    slant[int(distance)].append(((128 - x_band[x, y]) * dx + (y_band[x, y] - 128) * dy) / distance)
    profile = [sorted(values)[len(values) // 2] if values else 0 for values in slant]
    dome_x, dome_y = Image.new('L', disc.size, 128), Image.new('L', disc.size, 128)
    put_x, put_y = dome_x.load(), dome_y.load()
    for y in range(size):
        for x in range(size):
            if inside[x, y]:
                dx, dy = x - centre, y - centre
                distance = (dx * dx + dy * dy) ** 0.5
                if distance >= 1:
                    tilt = profile[int(distance)] / distance
                    put_x[x, y] = max(0, min(255, round(128 - tilt * dx)))
                    put_y[x, y] = max(0, min(255, round(128 + tilt * dy)))
    strays = ImageChops.lighter(ImageChops.difference(alpha, dome_x), ImageChops.difference(green, dome_y))
    mask = ImageChops.multiply(strays.point(lambda v: 255 if v > 24 else 0), inner)
    mask = ImageChops.multiply(mask.filter(ImageFilter.MaxFilter(11)), inner).filter(ImageFilter.GaussianBlur(1))
    alpha.paste(dome_x, mask=mask)
    green.paste(dome_y, mask=mask)
    return Image.merge('RGBA', (red, green, blue, alpha))


def lyre_relief(image, height):
    """The normal map `image` (RGBA) with `height` (an L image: the letters) raised on it: the
    slopes of its edges tilt the normals, as the game's own letters do."""
    from PIL import Image, ImageChops, ImageFilter
    red, green, blue, alpha = image.split()
    smooth = height.filter(ImageFilter.GaussianBlur(1.5))
    tilt_x = ImageChops.subtract(ImageChops.offset(smooth, -1, 0), ImageChops.offset(smooth, 1, 0), LYRE_RELIEF, 128)
    tilt_y = ImageChops.subtract(ImageChops.offset(smooth, 0, -1), ImageChops.offset(smooth, 0, 1), LYRE_RELIEF, 128)
    alpha = ImageChops.add(alpha, tilt_x, 1, -128)
    green = ImageChops.subtract(green, tilt_y, 1, 128)
    return Image.merge('RGBA', (red, green, blue, alpha))


def paint_lyre(image, form, kind, draw_letter, labels):
    """The level texture `image` (the lyre's or the gold mechanism's, of `kind`) with its four
    discs showing the gamepad buttons: the letter is replaced by the disc's own interior (black in
    the glow mask) and the host button's letter drawn in its place."""
    from PIL import Image, ImageDraw, ImageFilter
    look = LYRE_FORMS[form]
    shrink = 2048 // image.width
    x0, y0, x1, y1 = (v // shrink for v in LYRE_CORNER)
    normal = kind == 'normal'
    corner = image.crop((x0, y0, x1, y1)).convert('RGBA' if normal else 'RGB')
    radius = LYRE_RADIUS // shrink
    inner = Image.new('L', (2 * radius, 2 * radius), 0)
    ImageDraw.Draw(inner).ellipse((radius * (1 - look['inner']), radius * (1 - look['inner']),
                                   radius * (1 + look['inner']), radius * (1 + look['inner'])), fill=255)
    boxes = {button: (cx // shrink - radius, cy // shrink - radius, cx // shrink + radius, cy // shrink + radius)
             for button, (cx, cy) in LYRE_DISCS.items()}
    medians = {}
    if kind == 'glow':
        for box in boxes.values():
            corner.paste((0, 0, 0), box, mask=inner)
    elif normal:
        for button, box in boxes.items():
            corner.paste(lyre_dome(corner.crop(box), inner, radius), box)
    else:
        discs = {button: corner.crop(box) for button, box in boxes.items()}
        masks = {button: lyre_letter_mask(disc, inner, look['dark']) for button, disc in discs.items()}
        # as sources the discs only lose their letters: what a shape encloses is good texture
        lettered = {button: lyre_letter_mask(disc, inner, look['dark'], enclosed=False) for button, disc in discs.items()}
        for button, box in boxes.items():
            others = [(discs[other], lettered[other]) for other in discs if other != button]
            filled, medians[button] = lyre_fill(discs[button], masks[button], inner, others,
                                                lettered[button] if look['dark'] else None)
            corner.paste(filled, box)
    size = (LYRE_CORNER[2] - LYRE_CORNER[0], LYRE_CORNER[3] - LYRE_CORNER[1])
    letters = Image.new('RGBA', size, (0, 0, 0, 0))
    for button, centre in LYRE_DISCS.items():
        label, color = labels[button]
        if form == 'gold':  # a line engraved into the gold: a light bevel around a dark groove
            median = medians.get(button, (156, 116, 60))
            if kind == 'diffuse':  # the far wall of the groove catches the light
                light = tuple(min(255, int(c * 1.2)) for c in median)
                lit = (centre[0] + 2, centre[1] + 2)
                letters.alpha_composite(draw_letter(size, label, lit, look['cap'], light, outline=GOLD_LINE + 5).filter(ImageFilter.GaussianBlur(1.5)))
                groove = tuple(int(c * 0.5) for c in median)
            else:
                groove = tuple(int(c * 0.9) for c in median)
            letters.alpha_composite(draw_letter(size, label, centre, look['cap'], groove, outline=GOLD_LINE).filter(ImageFilter.GaussianBlur(0.6)))
            continue
        if kind == 'diffuse':
            color = tuple(int(c * LYRE_DIM) for c in color)
        elif kind == 'decal':
            color = tuple(int(c * LYRE_DECAL) for c in color)
        elif kind == 'specular':  # light grey with the dark rim of a carved edge
            letters.alpha_composite(draw_letter(size, label, centre, look['cap'], (LYRE_RIM,) * 3, stroke=2))
            color = (LYRE_SHINE,) * 3
        else:
            color = (255, 255, 255)
        letters.alpha_composite(draw_letter(size, label, centre, look['cap'], color))
    if shrink > 1:
        letters = letters.resize(corner.size, Image.Resampling.LANCZOS)
    if normal:
        base = lyre_relief(corner, letters.split()[3])
    else:
        base = corner.convert('RGBA')
        base.alpha_composite(letters)
    out = image.convert('RGBA' if normal else 'RGB')
    out.paste(base if normal else base.convert('RGB'), (x0, y0))
    return out
