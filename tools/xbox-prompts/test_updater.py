"""Installer checks using synthetic archives; no game files required."""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


spec = importlib.util.spec_from_file_location("updater", Path(__file__).parent / "deck-updater/apply.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.game = self.root / "Game with spaces"
        self.game.mkdir()
        (self.game / "eboot.bin").touch()
        self.originals = self.game / updater.WAD_DIR
        self.originals.mkdir(parents=True)
        self.targets = self.game.with_name(self.game.name + "-mods") / updater.WAD_DIR
        self.bundle = self.root / "data.zip"
        self.source = b"original" * 10000  # Two blocks, including a partial final block.
        self.output = b"modified" * 10000
        manifest = {"block_size": updater.BLOCK_SIZE, "files": {}}
        with zipfile.ZipFile(self.bundle, "w") as package:
            for name in updater.ARCHIVES:
                (self.originals / name).write_bytes(self.source)
                manifest["files"][name] = {
                    "size": len(self.source),
                    "source": hashlib.sha256(self.source).hexdigest(),
                    "output": hashlib.sha256(self.output).hexdigest(),
                    "blocks": [0, 1],
                }
                package.writestr(name + ".xor", bytes(a ^ b for a, b in zip(self.source, self.output)))
            package.writestr("manifest.json", json.dumps(manifest))

    def test_install_and_repeat_preserve_originals_and_saves(self):
        saves = self.game / "_rehooked_/saves/save.dat"
        saves.parent.mkdir(parents=True)
        saves.write_bytes(b"save")
        updater.apply(self.game, self.bundle)
        for name in updater.ARCHIVES:
            self.assertEqual((self.targets / name).read_bytes(), self.output)
            self.assertEqual((self.originals / name).read_bytes(), self.source)
        self.assertEqual(saves.read_bytes(), b"save")
        self.assertIn("already installed", updater.apply(self.game, self.bundle))
        self.assertFalse(list(self.root.glob("*-xbox-backup-*")))

    def test_existing_mod_is_backed_up_and_unrelated_files_stay(self):
        self.targets.mkdir(parents=True)
        (self.targets / "R_UI.WAD").write_bytes(b"previous mod")
        (self.targets / "OTHER.WAD").write_bytes(b"unrelated")
        updater.apply(self.game, self.bundle)
        backups = list(self.root.glob("*-xbox-backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "R_UI.WAD").read_bytes(), b"previous mod")
        self.assertEqual((self.targets / "OTHER.WAD").read_bytes(), b"unrelated")

    def test_wrong_source_installs_nothing(self):
        (self.originals / updater.ARCHIVES[-1]).write_bytes(b"x" * len(self.source))
        with self.assertRaisesRegex(ValueError, "does not match"):
            updater.apply(self.game, self.bundle)
        self.assertFalse(self.targets.exists())
        self.assertFalse(list(self.root.glob(".*.lock")))

    def test_incomplete_patch_installs_nothing(self):
        with zipfile.ZipFile(self.bundle) as package:
            manifest = package.read("manifest.json")
        with zipfile.ZipFile(self.bundle, "w") as package:
            package.writestr("manifest.json", manifest)
            package.writestr("R_UI.WAD.xor", b"short")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            updater.apply(self.game, self.bundle)
        self.assertFalse(self.targets.exists())

    def test_failed_install_restores_previous_mod(self):
        self.targets.mkdir(parents=True)
        (self.targets / "R_UI.WAD").write_bytes(b"previous mod")
        replace = Path.replace

        def fail_second(source, target):
            if target.name == "R_PERM.WAD":
                raise OSError("simulated write failure")
            return replace(source, target)

        with patch.object(Path, "replace", fail_second):
            with self.assertRaisesRegex(OSError, "simulated"):
                updater.apply(self.game, self.bundle)
        self.assertEqual((self.targets / "R_UI.WAD").read_bytes(), b"previous mod")
        self.assertFalse((self.targets / "R_PERM.WAD").exists())

    def test_concurrent_installer_is_rejected(self):
        lock = self.game.with_name(f".{self.game.name}.xbox-prompts.lock")
        lock.touch()
        with self.assertRaisesRegex(ValueError, "Another Xbox prompt installer"):
            updater.apply(self.game, self.bundle)
        self.assertTrue(lock.exists())


if __name__ == "__main__":
    unittest.main()
