#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from collect import EvidenceInputError, collect_bundle
from test_collect import COMMIT, create_fixture


class MissingInputTests(unittest.TestCase):
    def test_missing_module_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gates, package, controlled, soak = create_fixture(root)
            (package / "ngx_http_grpc_web_module.so").unlink()
            with self.assertRaisesRegex(EvidenceInputError, "missing module artifact"):
                collect_bundle(
                    release_version="v0.1.0",
                    source={"commit": COMMIT, "dirty": False},
                    gates_path=gates,
                    package_dir=package,
                    controlled_dir=controlled,
                    soak_dir=soak,
                )

    def test_missing_checksum_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gates, package, controlled, soak = create_fixture(root)
            (package / "SHA256SUMS").unlink()
            with self.assertRaisesRegex(EvidenceInputError, "missing checksum file"):
                collect_bundle(
                    release_version="v0.1.0",
                    source={"commit": COMMIT, "dirty": False},
                    gates_path=gates,
                    package_dir=package,
                    controlled_dir=controlled,
                    soak_dir=soak,
                )

    def test_missing_controlled_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gates, package, controlled, soak = create_fixture(root)
            (controlled / "manifest.json").unlink()
            with self.assertRaisesRegex(EvidenceInputError, "missing controlled manifest"):
                collect_bundle(
                    release_version="v0.1.0",
                    source={"commit": COMMIT, "dirty": False},
                    gates_path=gates,
                    package_dir=package,
                    controlled_dir=controlled,
                    soak_dir=soak,
                )


if __name__ == "__main__":
    unittest.main()
