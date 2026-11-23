"""Rebuild the Windows and Steam Deck downloads using Python's standard library.

Run from the checkout: python tools/xbox-prompts/package.py
"""

from pathlib import Path
import zipfile


def main():
    source = Path(__file__).resolve().parent / "deck-updater"
    assets = source.parents[2] / "assets"
    common = ("apply.py", "Xbox-Prompt-Data.zip", "START HERE.txt")
    for platform, launcher in (("Windows", "Apply Xbox Prompts.cmd"),
                               ("Steam-Deck", "Apply Xbox Prompts.desktop")):
        target = assets / f"Xbox-Prompt-Updater-{platform}.zip"
        # Validate all inputs before replacing a download.
        files = {name: (source / name).read_bytes() for name in (*common, launcher)}
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as package:
            for name, data in files.items():
                entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = (0o100755 if name.endswith(".desktop") else 0o100644) << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                if name.endswith(".cmd"):
                    data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                package.writestr(entry, data)
        print(f"Created {target}")


if __name__ == "__main__":
    main()
