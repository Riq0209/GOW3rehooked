# SPDX-License-Identifier: GPL-2.0-or-later
"""Build an Xbox button prompt mod from a local God of War III Remastered dump."""

import argparse
import io
import os
from pathlib import Path
import shutil
import struct
import tempfile

from lyre import LYRE_CORNER, paint_lyre

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
except ModuleNotFoundError as error:
    if error.name != "PIL":
        raise
    Image = None


WAD_DIR = Path("EXEC/WAD/PS4_LE")
ARCHIVES = ("R_UI.WAD", "R_PERM.WAD", "OLY150.WAD")
HEADER = struct.Struct("<HHI56s")
DDS_HEADER_SIZE = 128

# Texture IDs and atlas orientation from SpartanPort's GPL-2.0-or-later glyph patcher.
# https://github.com/FelipePrado0/SpartanPort/blob/main/launcher-rust/src/runner/glyphs.rs
INLINE = {
    "TX1BBACF4D": "cross", "TXBA40AFD2": "circle",
    "TX64F3D812": "square", "TX573C282A": "triangle",
    "TX91A47980": "l1", "TX5CED5AE9": "r1",
    "TX6FC83ACE": "l2", "TX67E86446": "r2",
    "TX9AE3BA81": "l3", "TXFB33513A": "r3",
    "TX192AE9D1": "options", "TXD43D1443": "touchpad_right",
}
QTE = {
    "TX7FF61BF7": "cross", "TX9D590CC8": "circle",
    "TX1F5FC983": "square", "TXE8889579": "triangle",
}
ATLAS = {"TXFB91136E": ("l2", "l1"), "TX0FFF3CCB": ("r2", "r1")}
PROMPTS = INLINE.keys() | QTE.keys() | ATLAS.keys()
LEVEL_TEXTURES = {
    "TX2CDFA5F8": ("lyre", "diffuse"),
    "TX4158CBF9": ("lyre", "specular"),
    "TX0C09B6DB": ("lyre", "decal"),
    "TXF489D97F": ("lyre", "normal"),
    "TXEACA5E71": ("lyre", "glow"),
    "TXBD54B283": ("gold", "diffuse"),
    "TXCEE0EE2B": ("gold", "specular"),
}
FACES = {
    "cross": ("A", (123, 185, 100)),
    "circle": ("B", (221, 106, 109)),
    "square": ("X", (92, 156, 231)),
    "triangle": ("Y", (238, 201, 78)),
}
OTHER_LABELS = {
    "l1": "LB", "r1": "RB", "l2": "LT", "r2": "RT", "l3": "LS", "r3": "RS",
    "options": "MENU", "touchpad_right": "VIEW",
}
SCALE = 4


def letter(draw, label, center, height, max_width, color, stroke=0):
    font = ImageFont.load_default(size=max(1, int(height)))
    left, top, right, bottom = font.getbbox(label)
    size = max(1, int(font.size * min(height / (bottom - top), max_width / (right - left))))
    font = ImageFont.load_default(size=size)
    left, top, right, bottom = font.getbbox(label)
    draw.text((center[0] - (left + right) / 2, center[1] - (top + bottom) / 2),
              label, font=font, fill=color, stroke_width=stroke)


def lyre_letter(size, label, center, cap, color, stroke=0, outline=0):
    canvas = Image.new("RGBA", tuple(dim * SCALE for dim in size))
    x, y = (value * SCALE for value in center)
    letter(ImageDraw.Draw(canvas), label, (x, y), cap * SCALE, 155 * SCALE, color,
           stroke=max(stroke, outline // 2) * SCALE)
    return canvas.resize(size, Image.Resampling.LANCZOS)


def render_round_face(label, color, size):
    w, h = (dim * SCALE for dim in size)
    cx, cy = w / 2, h / 2
    radius = min(w, h) * 0.46

    def bounds(inset):
        r = radius * (1 - inset)
        return cx - r, cy - r, cx + r, cy + r

    canvas = Image.new("RGB", (w, h), (26, 26, 30))
    rim_mask = Image.new("L", (w, h))
    ImageDraw.Draw(rim_mask).ellipse(bounds(0.035), fill=255)
    charcoal_rim = Image.linear_gradient("L").point(lambda y: round(42 + 30 * (1 - y / 255) ** 3))
    canvas.paste(charcoal_rim.resize((w, h), Image.Resampling.BILINEAR).convert("RGB"), mask=rim_mask)
    draw = ImageDraw.Draw(canvas)
    draw.ellipse(bounds(0.105), fill=(31, 31, 35))
    letter(draw, label, (cx, cy), radius * 1.1, radius * 1.3, color)

    # Supersample color and coverage separately. Keeping the edge color under the
    # transparent pixels gives the DDS encoder a clean contour.
    coverage = Image.new("L", (w, h))
    ImageDraw.Draw(coverage).ellipse(bounds(0), fill=255)
    face = canvas.resize(size, Image.Resampling.BOX)
    face.putalpha(coverage.resize(size, Image.Resampling.BOX))
    return face


def render_button(button, size, inline):
    w, h = (dim * SCALE for dim in size)
    center = (w / 2, h / 2)
    label, color = FACES[button] if button in FACES else (OTHER_LABELS[button], (242, 242, 242))
    if inline and button in FACES:
        return render_round_face(label, color, size)
    canvas = Image.new("RGBA", (w, h))
    draw = ImageDraw.Draw(canvas)
    if inline:
        x, y = w * 0.04, h * 0.16
        draw.rounded_rectangle((x, y, w - x, h - y), min(w, h) * 0.13,
                               fill=(26, 26, 30), outline=(121, 121, 128), width=SCALE)
        letter(draw, label, center, h * 0.36, w * 0.76, color)
    else:
        letter(draw, label, center, h * 0.57, w * 0.66, color)
        background = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        background.alpha_composite(canvas.filter(ImageFilter.GaussianBlur(2.5 * SCALE)))
        background.alpha_composite(canvas)
        canvas = background
    return canvas.resize(size, Image.Resampling.LANCZOS)


def render_prompt(texture, size):
    if texture in INLINE:
        return render_button(INLINE[texture], size, inline=True)
    if texture in QTE:
        return render_button(QTE[texture], size, inline=False)
    w, h = size
    if h % 2:
        raise ValueError("shoulder button atlas must have two equal halves")
    canvas = Image.new("RGBA", size, (0, 0, 0, 255))
    for row, button in enumerate(ATLAS[texture]):
        half_size = (w, h // 2)
        half = Image.new("RGBA", half_size, (0, 0, 0, 255))
        # The game samples the upper glyph rotated and both glyphs closer to the dividing line.
        half.paste(render_button(button, half_size, inline=False), (0, -(h * 12 // 256)))
        if row == 0:
            half = half.transpose(Image.Transpose.ROTATE_180)
        canvas.paste(half, (0, row * half_size[1]))
    return canvas


def encode_strip(image, fourcc, length):
    with io.BytesIO() as stream:
        image.save(stream, "DDS", pixel_format=fourcc)
        data = stream.getvalue()
    if data[84:88] != fourcc.encode("ascii") or len(data) != DDS_HEADER_SIZE + length:
        raise ValueError(f"Pillow returned an invalid {fourcc} block row")
    return data[DDS_HEADER_SIZE:]


def mip_sizes(width, height, remaining, block_size, allow_footer):
    while remaining:
        stride = (width + 3) // 4 * block_size
        length = stride * ((height + 3) // 4)
        if length > remaining:
            break
        yield width, height, stride, length
        remaining -= length
        if width == height == 1:
            break
        width, height = max(1, width // 2), max(1, height // 2)
    if remaining and not allow_footer:
        raise ValueError(f"incomplete DDS mip chain ({remaining} extra bytes)")


def encode_levels(pixels, image, fourcc, before=None, region=None):
    block_size = 8 if fourcc == "DXT1" else 16
    offset = 0
    for level, (w, h, stride, length) in enumerate(
            mip_sizes(*image.size, len(pixels), block_size, allow_footer=region is not None)):
        resized = image if level == 0 else image.resize((w, h), Image.Resampling.LANCZOS)
        x0, y0, x1, y1 = 0, 0, w, h
        if region and w > 8 and h > 8:
            left, top, right, bottom = (coord >> level for coord in region)
            x0, y0 = left // 4 * 4, top // 4 * 4
            x1, y1 = min(w, (right + 3) // 4 * 4), min(h, (bottom + 3) // 4 * 4)
        if before is not None:
            original = before if level == 0 else before.resize((w, h), Image.Resampling.LANCZOS)
            changed = ImageChops.difference(resized, original)
        row_length = (x1 - x0 + 3) // 4 * block_size
        for y in range(y0, y1, 4):
            row = (x0, y, x1, min(y + 4, h))
            if before is not None and not changed.crop(row).getbbox(alpha_only=False):
                continue
            blocks = encode_strip(resized.crop(row), fourcc, row_length)
            start = offset + y // 4 * stride + x0 // 4 * block_size
            if before is None:
                pixels[start:start + row_length] = blocks
            else:
                for i, x in enumerate(range(x0, x1, 4)):
                    if changed.crop((x, y, min(x + 4, w), row[3])).getbbox(alpha_only=False):
                        begin = i * block_size
                        pixels[start + begin:start + begin + block_size] = blocks[begin:begin + block_size]
        offset += length
    if not offset:
        raise ValueError("DDS has no complete mip level")


def patch_texture(entry, texture):
    dds = entry.find(b"DDS ")
    if dds < 0 or dds + DDS_HEADER_SIZE > len(entry):
        raise ValueError("missing DDS header")
    header = entry[dds:dds + DDS_HEADER_SIZE]
    header_size = struct.unpack_from("<I", header, 4)[0]
    h, w = struct.unpack_from("<II", header, 12)
    fourcc = header[84:88]
    if header_size != 124 or not (1 <= w <= 2048 and 1 <= h <= 2048) or fourcc not in (b"DXT1", b"DXT5"):
        raise ValueError(f"unsupported DDS layout ({w}x{h}, {fourcc!r})")
    fourcc = fourcc.decode("ascii")
    mode = "RGB" if fourcc == "DXT1" else "RGBA"
    start = dds + DDS_HEADER_SIZE
    pixels = bytearray(entry[start:])
    if texture in LEVEL_TEXTURES:
        form, kind = LEVEL_TEXTURES[texture]
        expected = 512 if kind == "glow" else 2048
        expected_codec = "DXT5" if kind == "normal" else "DXT1"
        if w != expected or h != expected or fourcc != expected_codec:
            raise ValueError(f"unexpected lyre texture format ({w}x{h}, {fourcc})")
        with Image.open(io.BytesIO(entry[dds:])) as decoded:
            before = decoded.convert(mode)
        painted = paint_lyre(before, form, kind, lyre_letter, FACES)
        region = tuple(coord // (2048 // w) for coord in LYRE_CORNER)
        encode_levels(pixels, painted, fourcc, before=before, region=region)
    else:
        encode_levels(pixels, render_prompt(texture, (w, h)).convert(mode), fourcc)
    return start, pixels


def patch_archive(path, targets):
    found = set()
    count = 0
    with path.open("r+b") as file:
        end = os.fstat(file.fileno()).st_size
        offset = 0
        while offset + HEADER.size <= end:
            file.seek(offset)
            tag, _, size, name = HEADER.unpack(file.read(HEADER.size))
            name = name.split(b"\0", 1)[0].decode("latin1")
            if tag == 0 and name == "EntityCount":
                size = 0  # Level WADs store a count in this marker's size field.
            payload = offset + HEADER.size
            if payload + size > end:
                raise ValueError(f"{path.name}: WAD entry at 0x{offset:x} extends past the end")
            texture = name[:10].upper()
            if name.lower().endswith(".dds") and texture in targets:
                # Bound the only allocations controlled by a WAD entry.
                if size > 8 * 1024 * 1024:
                    raise ValueError(f"{path.name}: {name}: unexpected texture size")
                try:
                    start, pixels = patch_texture(file.read(size), texture)
                except (OSError, ValueError) as error:
                    raise ValueError(f"{path.name}: {name}: {error}") from error
                file.seek(payload + start)
                file.write(pixels)
                found.add(texture)
                count += 1
            offset = payload + ((size + 15) & ~15)
    return found, count


def locate(root, relative):
    # Match Rehooked's case-insensitive lookup on Linux when the dump uses different casing.
    for part in relative.parts:
        exact = root / part
        if exact.exists():
            root = exact
        elif root.is_dir():
            matches = [path for path in root.iterdir() if path.name.casefold() == part.casefold()]
            if len(matches) > 1:
                raise ValueError(f"ambiguous filename {part} in {root}")
            if not matches:
                return None
            root = matches[0]
        else:
            return None
    return root if root.is_file() else None


def build(game, output):
    if locate(game, Path("eboot.bin")) is None:
        raise ValueError(f"eboot.bin is missing from {game}")
    if os.path.lexists(output):
        raise ValueError(f"{output} already exists. Use --output to build into a new folder.")
    if not output.parent.is_dir():
        raise ValueError(f"output parent directory does not exist: {output.parent}")
    updates = next((root for suffix in ("-UPDATE", "-patch")
                    if (root := game.with_name(game.name + suffix)).is_dir()), None)
    sources = {}
    for name in ARCHIVES:
        relative = WAD_DIR / name
        source = (locate(updates, relative) if updates else None) or locate(game, relative)
        if source is not None:
            sources[name] = source
    if "R_UI.WAD" not in sources:
        raise ValueError(f"could not find {WAD_DIR / 'R_UI.WAD'} in the game or update folder")

    with tempfile.TemporaryDirectory(prefix=".xbox-prompts-", dir=output.parent) as temp:
        stage = Path(temp) / "mod"
        (stage / WAD_DIR).mkdir(parents=True)
        summary = {}
        ui_textures = set()
        for name, source in sources.items():
            print(f"Patching {name}...", flush=True)
            target = stage / WAD_DIR / name
            shutil.copyfile(source, target)
            is_lyre = name == "OLY150.WAD"
            found, count = patch_archive(target, LEVEL_TEXTURES if is_lyre else PROMPTS)
            if is_lyre and found and found != LEVEL_TEXTURES.keys():
                missing = ", ".join(sorted(LEVEL_TEXTURES.keys() - found))
                raise ValueError(f"{name}: missing known lyre textures ({missing})")
            if not is_lyre:
                ui_textures.update(found)
            if count:
                summary[name] = count
            else:
                target.unlink()
        if missing := PROMPTS - ui_textures:
            raise ValueError("the prompt archives are missing known textures (" + ", ".join(sorted(missing)) + ")")
        if os.path.lexists(output):
            raise ValueError(f"{output} appeared during generation. Choose another output folder.")
        stage.rename(output)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path, help="game folder containing eboot.bin and EXEC")
    parser.add_argument("--output", type=Path, help="new output folder (default: sibling <game-folder>-mods)")
    args = parser.parse_args()

    if Image is None:
        parser.exit(1, "Xbox prompts require Pillow. Install it with: python3 -m pip install 'Pillow>=12.1'\n")

    game = args.game.resolve()
    output = args.output.absolute() if args.output else game.parent / (game.name + "-mods")
    try:
        summary = build(game, output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Xbox prompts: {error}\n")
    print(f"Created {output}")
    for name, count in summary.items():
        print(f"  {name}: {count} Xbox textures")
    for name in ARCHIVES[1:]:
        if name not in summary:
            print(f"  {name}: no matching textures found; original archive will be used")


if __name__ == "__main__":
    main()
