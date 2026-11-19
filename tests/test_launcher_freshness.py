"""Tests for the packaged launcher's frontend freshness detection."""
from __future__ import annotations

import importlib
import os
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import launcher  # noqa: E402


class FrontendFreshnessTests(unittest.TestCase):
    """The launcher must rebuild whenever a React source file is newer than the build."""

    def setUp(self) -> None:
        self._saved_dist = launcher.FRONTEND_DIST
        self._saved_frontend = launcher.FRONTEND_DIR
        self._saved_run = launcher.run_npm_build

    def tearDown(self) -> None:
        launcher.FRONTEND_DIST = self._saved_dist
        launcher.FRONTEND_DIR = self._saved_frontend
        launcher.run_npm_build = self._saved_run

    def _fake_tree(self, tmp: Path) -> tuple[Path, Path, Path]:
        frontend = tmp / "frontend"
        src = frontend / "src" / "components"
        src.mkdir(parents=True)
        component = src / "Workspace.tsx"
        component.write_text("export const x = 1;\n", encoding="utf-8")

        dist = frontend / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")
        (dist / "assets" / "index-abc.js").write_text("console.log(1);\n", encoding="utf-8")
        return frontend, dist, component

    def test_rebuilds_when_a_nested_source_file_is_newer_than_the_build(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            frontend, dist, component = self._fake_tree(Path(directory))
            launcher.FRONTEND_DIR = frontend
            launcher.FRONTEND_DIST = dist

            built = {"called": False}

            def fake_build() -> bool:
                built["called"] = True
                return True

            launcher.run_npm_build = fake_build

            # Make the build artifacts older than the edited component.
            old = time.time() - 600
            for path in dist.rglob("*"):
                if path.is_file():
                    os.utime(path, (old, old))
            os.utime(dist, (old, old))
            os.utime(component, (time.time(), time.time()))

            self.assertTrue(launcher.build_frontend())
            self.assertTrue(built["called"], "an edited React component must trigger a rebuild")

    def test_does_not_rebuild_when_the_build_is_newer_than_the_sources(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            frontend, dist, component = self._fake_tree(Path(directory))
            launcher.FRONTEND_DIR = frontend
            launcher.FRONTEND_DIST = dist

            built = {"called": False}

            def fake_build() -> bool:
                built["called"] = True
                return True

            launcher.run_npm_build = fake_build

            old = time.time() - 600
            os.utime(component, (old, old))
            now = time.time()
            for path in dist.rglob("*"):
                if path.is_file():
                    os.utime(path, (now, now))
            os.utime(dist, (now, now))

            self.assertTrue(launcher.build_frontend())
            self.assertFalse(built["called"], "a fresh build must not trigger a rebuild")

    def test_rebuilds_when_only_a_dist_file_is_stale(self) -> None:
        """A stale build must be detected even when dist/'s directory mtime is newer."""
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            frontend, dist, component = self._fake_tree(Path(directory))
            launcher.FRONTEND_DIR = frontend
            launcher.FRONTEND_DIST = dist

            built = {"called": False}

            def fake_build() -> bool:
                built["called"] = True
                return True

            launcher.run_npm_build = fake_build

            # The build artifacts are stale, the source has since been edited,
            # and dist/'s directory mtime is newer than both (a stray file was
            # deleted after the build). Only the newest-file comparison catches this.
            old = time.time() - 600
            for path in dist.rglob("*"):
                if path.is_file():
                    os.utime(path, (old, old))
            os.utime(component, (time.time() - 300, time.time() - 300))
            os.utime(dist, (time.time(), time.time()))

            self.assertTrue(launcher.build_frontend())
            self.assertTrue(
                built["called"],
                "a stale build must be detected even when dist/'s directory mtime is newer",
            )


if __name__ == "__main__":
    unittest.main()
