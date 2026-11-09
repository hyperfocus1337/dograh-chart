"""Publishing must fail closed before it changes a registry tag."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS = dict(
    line.split("=", 1)
    for line in (ROOT / "upstream.env").read_text().splitlines()
    if line and not line.startswith("#")
)


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "scripts", self.root / "scripts")
        shutil.copy(ROOT / "upstream.env", self.root)
        dist = self.root / "dist"
        dist.mkdir()
        self.archive = dist / f"dograh-{PINS['CHART_VERSION']}.tgz"
        self.archive.write_bytes(b"validated fixture archive")
        (dist / "SHA256SUMS").write_text(
            hashlib.sha256(self.archive.read_bytes()).hexdigest()
            + "  dist/"
            + self.archive.name
            + "\n"
        )
        binary = self.root / "bin"
        binary.mkdir()
        curl = binary / "curl"
        curl.write_text(
            "#!/usr/bin/env python3\nimport json, os, sys\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            'output = Path(args[args.index("--output") + 1])\n'
            'if "https://ghcr.io/token" in args:\n'
            '    if os.environ.get("TOKEN_FAIL"):\n        sys.exit(22)\n'
            '    output.write_text(json.dumps({"token": "fixture-token"}))\n'
            "else:\n"
            '    if os.environ.get("TRANSPORT_FAIL"):\n        sys.exit(7)\n'
            '    assert "Authorization: Bearer fixture-token" in args\n'
            '    output.write_text(os.environ.get("MANIFEST_BODY", '
            '\'{"errors":[{"code":"MANIFEST_UNKNOWN"}]}\'))\n'
            '    print(os.environ.get("MANIFEST_STATUS", "404"), end="")\n'
        )
        curl.chmod(0o755)
        helm = binary / "helm"
        helm.write_text(
            "#!/usr/bin/env python3\nimport json, os, sys\n"
            'with open(os.environ["HELM_LOG"], "a") as stream:\n'
            '    stream.write(json.dumps(sys.argv[1:]) + "\\n")\n'
            'if sys.argv[1:3] == ["registry", "login"]:\n'
            "    sys.stdin.read()\n"
            '    if os.environ.get("LOGIN_FAIL"):\n        sys.exit(1)\n'
            'if sys.argv[1] == "push":\n'
            '    if os.environ.get("PUSH_FAIL"):\n        sys.exit(42)\n'
            '    print("Pushed fixture chart\\nDigest: sha256:fixture")\n'
        )
        helm.chmod(0o755)
        controls = {
            "TOKEN_FAIL",
            "TRANSPORT_FAIL",
            "MANIFEST_BODY",
            "MANIFEST_STATUS",
            "LOGIN_FAIL",
            "PUSH_FAIL",
        }
        self.env = {
            key: value for key, value in os.environ.items() if key not in controls
        }
        self.env.update(
            PATH=str(binary) + os.pathsep + os.environ["PATH"],
            GH_TOKEN="fixture-github-token",
            GITHUB_ACTOR="fixture-actor",
            GITHUB_REPOSITORY="hyperfocus1337/dograh-chart",
            GITHUB_STEP_SUMMARY=str(self.root / "summary"),
            HELM_LOG=str(self.root / "helm.jsonl"),
        )

    def publish(self):
        return subprocess.run(
            ["bash", str(self.root / "scripts/publish.sh")],
            cwd="/tmp",
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )

    def calls(self):
        log = self.root / "helm.jsonl"
        return (
            [json.loads(line) for line in log.read_text().splitlines()]
            if log.exists()
            else []
        )

    def test_absent_manifest_publishes_validated_archive(self):
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.calls()[-1],
            [
                "push",
                "dist/" + self.archive.name,
                "oci://ghcr.io/hyperfocus1337/dograh-chart",
            ],
        )
        self.assertIn("sha256:fixture", (self.root / "summary").read_text())

    def test_existing_version_never_pushes(self):
        self.env["MANIFEST_STATUS"] = "200"
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to replace", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_registry_errors_never_push(self):
        baseline = self.env.copy()
        for changes in (
            {"TOKEN_FAIL": "true"},
            {"TRANSPORT_FAIL": "true"},
            {"MANIFEST_STATUS": "401"},
            {"MANIFEST_STATUS": "403"},
            {"MANIFEST_STATUS": "429"},
            {"MANIFEST_STATUS": "500"},
            {"MANIFEST_BODY": "not JSON"},
            {"MANIFEST_BODY": '{"errors":[{"code":"DENIED"}]}'},
            {"MANIFEST_BODY": '{"errors":[]}'},
        ):
            with self.subTest(changes=changes):
                self.env = dict(baseline, **changes)
                self.assertNotEqual(self.publish().returncode, 0)
                self.assertEqual(self.calls(), [])

    def test_checksum_mismatch_never_pushes(self):
        self.archive.write_bytes(b"changed after validation")
        self.assertNotEqual(self.publish().returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_failed_push_is_not_reported_as_published(self):
        self.env["PUSH_FAIL"] = "true"
        result = self.publish()
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertFalse((self.root / "summary").exists())

    def test_failed_login_never_pushes(self):
        self.env["LOGIN_FAIL"] = "true"
        self.assertNotEqual(self.publish().returncode, 0)
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.calls()[0][:2], ["registry", "login"])
        self.assertFalse((self.root / "summary").exists())


if __name__ == "__main__":
    unittest.main()
