"""Exercise packaging with a local source archive and the real Helm CLI."""

import io
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS = dict(
    line.split("=", 1)
    for line in (ROOT / "upstream.env").read_text().splitlines()
    if line and not line.startswith("#")
)
COMMIT = PINS["UPSTREAM_COMMIT"]
VERSION = PINS["CHART_VERSION"]


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copy(ROOT / "upstream.env", self.root)
        shutil.copytree(ROOT / "scripts", self.root / "scripts")
        self.fixture = self.root / "source.tgz"
        files = {
            f"dograh-{COMMIT}/deploy/helm/dograh/Chart.yaml": "apiVersion: v2\nname: dograh\nversion: 0.1.0\n",
            f"dograh-{COMMIT}/deploy/helm/dograh/values.yaml": "{}\n",
            f"dograh-{COMMIT}/deploy/helm/dograh/templates/configmap.yaml": "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: fixture\n",
            f"dograh-{COMMIT}/LICENSE": "fixture upstream license\n",
        }
        with tarfile.open(self.fixture, "w:gz") as archive:
            directory = tarfile.TarInfo(f"dograh-{COMMIT}/deploy/helm/dograh")
            directory.type = tarfile.DIRTYPE
            directory.mode = 0o755
            archive.addfile(directory)
            for name, content in files.items():
                data = content.encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        binary = self.root / "bin"
        binary.mkdir()
        curl = binary / "curl"
        curl.write_text(
            "#!/usr/bin/env python3\nimport os, shutil, sys\n"
            "from pathlib import Path\n"
            'Path(os.environ["CURL_CALLED"]).touch()\n'
            'if os.environ.get("CURL_FAIL"):\n    sys.exit(22)\n'
            f'assert "https://codeload.github.com/dograh-hq/dograh/tar.gz/{COMMIT}" in sys.argv\n'
            'shutil.copy(os.environ["FIXTURE"], sys.argv[sys.argv.index("--output") + 1])\n'
        )
        curl.chmod(0o755)
        self.env = dict(
            os.environ,
            PATH=str(binary) + os.pathsep + os.environ["PATH"],
            FIXTURE=str(self.fixture),
            CURL_CALLED=str(self.root / "curl-called"),
        )

    def package(self):
        return subprocess.run(
            ["bash", str(self.root / "scripts/package.sh")],
            cwd="/tmp",
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_package(self):
        result = self.package()
        self.assertEqual(result.returncode, 0, result.stderr)
        with tarfile.open(self.root / f"dist/dograh-{VERSION}.tgz") as archive:
            chart = archive.extractfile("dograh/Chart.yaml")
            self.assertIsNotNone(chart)
            assert chart is not None
            self.assertIn(f"version: {VERSION}", chart.read().decode())
            license_file = archive.extractfile("dograh/LICENSE")
            assert license_file is not None
            self.assertEqual(license_file.read(), b"fixture upstream license\n")
            provenance = archive.extractfile("dograh/UPSTREAM.txt")
            assert provenance is not None
            self.assertIn(COMMIT, provenance.read().decode())
            template = archive.extractfile("dograh/templates/configmap.yaml")
            assert template is not None
            self.assertIn(b"name: fixture", template.read())

    def test_invalid_pins_fail_before_download(self):
        for commit, version in (
            ("main", VERSION),
            (COMMIT, "0.1.0"),
            (COMMIT, "0.1.0-upstream.000000000000"),
        ):
            with self.subTest(commit=commit, version=version):
                (self.root / "upstream.env").write_text(
                    f"UPSTREAM_COMMIT={commit}\nCHART_VERSION={version}\n"
                )
                self.assertNotEqual(self.package().returncode, 0)
                self.assertFalse((self.root / "curl-called").exists())
                self.assertFalse((self.root / "dist").exists())

    def test_download_failure_does_not_package(self):
        self.env["CURL_FAIL"] = "true"
        self.assertNotEqual(self.package().returncode, 0)
        self.assertFalse((self.root / "dist").exists())


if __name__ == "__main__":
    unittest.main()
