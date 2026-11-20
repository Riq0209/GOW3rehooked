#!/usr/bin/env python3
"""Apply the verified Xbox prompt patch bundle to a local game installation."""

import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile


WAD_DIR = Path("EXEC/WAD/PS4_LE")
ARCHIVES = ("R_UI.WAD", "R_PERM.WAD", "OLY150.WAD")
BLOCK_SIZE = 65536
TITLE = "GOW3rehooked Xbox Prompts"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(BLOCK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def locate(root, relative):
    for name in relative.parts:
        path = root / name
        if path.exists():
            root = path
        elif root.is_dir():
            matches = [p for p in root.iterdir() if p.name.casefold() == name.casefold()]
            if len(matches) != 1:
                return None
            root = matches[0]
        else:
            return None
    return root if root.is_file() else None


def make_copy(source, output, changes, entry):
    source_digest, output_digest = hashlib.sha256(), hashlib.sha256()
    blocks = set(entry["blocks"])
    with source.open("rb") as original, output.open("xb") as patched:
        for index, block in enumerate(iter(lambda: original.read(BLOCK_SIZE), b"")):
            source_digest.update(block)
            if index in blocks:
                xor = changes.read(len(block))
                if len(xor) != len(block):
                    raise ValueError("The installer ZIP is incomplete. Extract a fresh copy.")
                block = (int.from_bytes(block, "little") ^ int.from_bytes(xor, "little")).to_bytes(len(block), "little")
                blocks.remove(index)
            patched.write(block)
            output_digest.update(block)
    if source_digest.hexdigest() != entry["source"]:
        raise ValueError(f"{source.name} is from a different game copy. This bundle needs the game files used by the Windows test.")
    if blocks or changes.read(1) or output_digest.hexdigest() != entry["output"]:
        raise ValueError("The installer ZIP did not pass verification. Extract a fresh copy.")


def apply(game, bundle):
    game = game.resolve(strict=True)
    if locate(game, Path("eboot.bin")) is None:
        raise ValueError("Choose the folder containing eboot.bin.")
    mods = game.with_name(game.name + "-mods")
    target_dir = mods / WAD_DIR
    # Generated copies must stay outside the original game folder.
    if target_dir.resolve() != target_dir:
        raise ValueError("The mod folder points somewhere else. Select a game with a regular mod folder.")
    update = next((game.with_name(game.name + suffix) for suffix in ("-UPDATE", "-patch")
                   if game.with_name(game.name + suffix).is_dir()), None)
    lock = game.with_name(f".{game.name}.xbox-prompts.lock")
    with lock.open("x"):
        pass
    try:
        return apply_locked(game, bundle, update, target_dir)
    finally:
        lock.unlink()


def apply_locked(game, bundle, update, target_dir):
    with zipfile.ZipFile(bundle) as package, tempfile.TemporaryDirectory(
            prefix=".xbox-prompts-", dir=game.parent) as temporary:
        manifest = json.loads(package.read("manifest.json"))
        if manifest["block_size"] != BLOCK_SIZE:
            raise ValueError("This installer format is unsupported.")
        staged = []
        for name in ARCHIVES:
            entry = manifest["files"][name]
            relative = WAD_DIR / name
            source = (locate(update, relative) if update else None) or locate(game, relative)
            if source is None or source.stat().st_size != entry["size"]:
                raise ValueError(f"Could not find the matching original {name} in this game folder.")
            current = target_dir / name
            if current.is_symlink():
                raise ValueError(f"Move the linked {name} out of your mod folder first.")
            if current.is_file() and sha256(current) == entry["output"]:
                continue
            print(f"Preparing {name}...", flush=True)
            output = Path(temporary) / name
            with package.open(name + ".xor") as changes:
                make_copy(source, output, changes, entry)
            staged.append((current, output))
        if not staged:
            return "The latest Xbox prompts are already installed."

        originals = {}
        backup_dir = None
        for current, _ in staged:
            if current.exists():
                if backup_dir is None:
                    backup_dir = Path(tempfile.mkdtemp(prefix=game.name + "-xbox-backup-", dir=game.parent))
                previous = backup_dir / current.name
                shutil.copyfile(current, previous)
                originals[current] = previous
        target_dir.mkdir(parents=True, exist_ok=True)
        installed = []
        try:
            for current, output in staged:
                output.replace(current)
                installed.append(current)
        except OSError:
            for current in reversed(installed):
                if current in originals:
                    shutil.copyfile(originals[current], current)
                else:
                    current.unlink()
            raise
    message = "Latest Xbox prompts installed. Launch your usual GOW3rehooked Steam shortcut."
    if backup_dir:
        message += f"\n\nPrevious mod files saved in:\n{backup_dir}"
    return message


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path, nargs="?")
    args = parser.parse_args()
    dialog = shutil.which("kdialog") if args.game is None else None
    try:
        if args.game is not None:
            game = args.game
        elif dialog:
            result = subprocess.run([dialog, "--title", "Choose the GOW3 folder containing eboot.bin",
                                     "--getexistingdirectory", str(Path.home())],
                                    text=True, stdout=subprocess.PIPE)
            if result.returncode or not result.stdout.strip():
                return
            game = Path(result.stdout.rstrip("\r\n"))
        else:
            folder = input("Paste the full path to the game folder containing eboot.bin: ").strip()
            if not folder:
                return
            game = Path(folder)
        message = apply(game, Path(__file__).resolve().with_name("Xbox-Prompt-Data.zip"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as error:
        if dialog:
            subprocess.run([dialog, "--title", TITLE, "--error", html.escape(str(error))])
        raise SystemExit(str(error))
    print(message)
    if dialog:
        subprocess.run([dialog, "--title", TITLE, "--msgbox", html.escape(message)])
    elif args.game is None:
        input("Press Enter to close.")


if __name__ == "__main__":
    main()
