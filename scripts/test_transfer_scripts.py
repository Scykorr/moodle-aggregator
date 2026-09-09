"""Static and layout checks for offline export/import scripts."""
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
IMAGE_NAMES = ("moodle-offline-5.2.tar", "mariadb-11.4.tar")


def _write_tars(directory: Path, size: int = 2 * 1024 * 1024) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    payload = b"x" * size
    for name in IMAGE_NAMES:
        (directory / name).write_bytes(payload)


def find_images_dir(root: Path, package_dir: Path | None = None) -> Path | None:
    """Mirrors Find-ImagesDir in import-and-start.ps1 (candidate order)."""
    candidates: list[Path] = []
    if package_dir is not None:
        package_dir = package_dir.resolve()
        candidates.extend([
            package_dir,
            package_dir / "images",
            package_dir / "transfer-package",
            package_dir / "transfer-package" / "images",
            (package_dir / "project" / ".." / "images"),
        ])
    walk = root.resolve()
    for _ in range(4):
        candidates.append(walk / "images")
        candidates.append(walk / "transfer-package" / "images")
        parent = walk.parent
        if parent == walk:
            break
        walk = parent
        candidates.append(walk / "images")

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            full = candidate.resolve()
        except OSError:
            continue
        if full in seen:
            continue
        seen.add(full)
        if all(
            (full / name).is_file() and (full / name).stat().st_size > 1024 * 1024
            for name in IMAGE_NAMES
        ):
            return full
    return None


def find_compose_root(start: Path) -> Path | None:
    """Mirrors Get-ComposeRoot in _common.ps1."""
    walk = start.resolve()
    for _ in range(6):
        if (walk / "docker-compose.yml").is_file():
            return walk
        parent = walk.parent
        if parent == walk:
            break
        walk = parent
    return None


class TransferScriptContentTests(unittest.TestCase):
    def test_required_files_exist(self) -> None:
        for name in (
            "_common.ps1",
            "export-for-transfer.ps1",
            "import-and-start.ps1",
            "stop.ps1",
            "export-for-transfer.cmd",
            "import-and-start.cmd",
            "stop.cmd",
        ):
            self.assertTrue((SCRIPTS / name).is_file(), name)

    def test_common_checks_native_exit_codes(self) -> None:
        text = (SCRIPTS / "_common.ps1").read_text(encoding="utf-8")
        self.assertIn("LASTEXITCODE", text)
        self.assertIn("docker.io/library/", text)
        self.assertIn("Get-ComposeRoot", text)
        self.assertIn("Import-DockerImageTar", text)

    def test_export_uses_absolute_save_and_rebuilds_project_dir(self) -> None:
        text = (SCRIPTS / "export-for-transfer.ps1").read_text(encoding="utf-8")
        self.assertIn('GetFullPath', text)
        self.assertIn('Remove-Item -LiteralPath $ProjectOut', text)
        self.assertIn('@("save", "-o", $TarPath, $Image)', text)
        self.assertIn("10MB", text)

    def test_import_does_not_rebuild_and_loads_absolute_tars(self) -> None:
        text = (SCRIPTS / "import-and-start.ps1").read_text(encoding="utf-8")
        self.assertIn("--no-build", text)
        self.assertIn("never", text)
        self.assertIn("Import-DockerImageTar", text)
        self.assertIn("GetFullPath", text)
        self.assertIn("COMPOSE_BAKE", text)

    def test_cmd_wrappers_bypass_execution_policy(self) -> None:
        for name in (
            "import-and-start.cmd",
            "export-for-transfer.cmd",
            "stop.cmd",
        ):
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertIn("ExecutionPolicy Bypass", text)
            self.assertIn("powershell.exe", text)

    def test_compose_mentions_loaded_image_tag(self) -> None:
        text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("image: moodle-offline:5.2", text)
        self.assertIn("pull_policy: missing", text)


class TransferLayoutTests(unittest.TestCase):
    def test_standard_transfer_package_layout(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            project = base / "transfer-package" / "project"
            images = base / "transfer-package" / "images"
            (project / "scripts").mkdir(parents=True)
            (project / "docker-compose.yml").write_text("services: {}\n")
            _write_tars(images)
            self.assertEqual(find_images_dir(project), images.resolve())
            self.assertEqual(
                find_compose_root(project / "scripts"), project.resolve()
            )

    def test_nested_scripts_still_find_compose(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "project"
            nested = project / "scripts" / "scripts"
            nested.mkdir(parents=True)
            (project / "docker-compose.yml").write_text("services: {}\n")
            self.assertEqual(find_compose_root(nested), project.resolve())

    def test_images_next_to_project(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            _write_tars(project / "images")
            self.assertEqual(
                find_images_dir(project), (project / "images").resolve()
            )

    def test_package_dir_can_be_images_folder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            images = Path(raw) / "usb" / "images"
            _write_tars(images)
            project = Path(raw) / "usb" / "project"
            project.mkdir(parents=True)
            self.assertEqual(find_images_dir(project, images), images.resolve())

    def test_rejects_tiny_or_missing_tars(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            images = project / "images"
            images.mkdir()
            (images / "moodle-offline-5.2.tar").write_bytes(b"too-small")
            (images / "mariadb-11.4.tar").write_bytes(b"x" * (2 * 1024 * 1024))
            self.assertIsNone(find_images_dir(project))


if __name__ == "__main__":
    unittest.main()
