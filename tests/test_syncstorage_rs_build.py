#!/usr/bin/env python3
"""Unit tests of the Sync image build changes on Dockerfile fixtures, no network.

Usage: python3 tests/test_syncstorage_rs_build.py [-v]
"""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("syncstorage_rs_build", os.path.join(ROOT, ".github", "scripts", "syncstorage-rs-build.py"))
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

# as upstream's Dockerfile has them (0.24.0)
UPSTREAM = """COPY --from=planner /app/recipe.json recipe.json

RUN --mount=type=cache,target=/usr/local/cargo/registry,sharing=locked \\
    --mount=type=cache,target=/usr/local/cargo/git,sharing=locked \\
    --mount=type=cache,target=/app/target,sharing=locked \\
    set -x && \\
    cargo chef cook --release --recipe-path recipe.json

RUN --mount=type=cache,target=/app/target,sharing=locked \\
    cargo install --path ./syncserver --locked --root /app
"""


class DropCacheMounts(unittest.TestCase):
    def test_upstream(self):
        text, count = build.drop_cache_mounts(UPSTREAM)
        self.assertEqual(count, 4)
        self.assertEqual(text, """COPY --from=planner /app/recipe.json recipe.json

RUN set -x && \\
    cargo chef cook --release --recipe-path recipe.json

RUN cargo install --path ./syncserver --locked --root /app
""")

    def test_same_line_and_field_order(self):
        text, count = build.drop_cache_mounts("RUN --mount=target=/app/target,type=cache cargo build\n")
        self.assertEqual((text, count), ("RUN cargo build\n", 1))

    def test_other_mounts_kept(self):
        line = "RUN --mount=type=secret,id=token --mount=type=bind,source=x,target=/x make\n"
        self.assertEqual(build.drop_cache_mounts(line), (line, 0))
        self.assertEqual(build.drop_cache_mounts("RUN --mount=type=cache,target=/c --mount=type=secret,id=t make\n"),
                         ("RUN --mount=type=secret,id=t make\n", 1))


class WheelMount(unittest.TestCase):
    copy = "COPY --from=builder /app/wheels /tmp/wheels\n"
    pip = ("pip3 install --no-index --find-links=/tmp/wheels -r /app/requirements.txt && \\\n"
           "    if [ -s extra.txt ]; then pip3 install --find-links=/tmp/wheels -r extra.txt; fi && \\\n")
    install = "RUN " + pip + "    rm -rf /tmp/wheels /root/.cache/pip\n"

    def test_only_the_install_mounts_the_wheels(self):
        setup = "RUN groupadd app\n"
        self.assertEqual(build.mount_wheels(self.copy + setup + self.install),
                         setup + "RUN --mount=type=bind,from=builder,source=/app/wheels,target=/tmp/wheels "
                         + self.pip + "    rm -rf /root/.cache/pip\n")

    def test_changed_consumers_keep_upstream_copy(self):
        for dockerfile in (self.copy, self.install, self.copy + self.install + "RUN ls /tmp/wheels\n",
                           self.copy + self.install.replace("rm -rf", "ls")):
            with self.subTest(dockerfile=dockerfile):
                self.assertEqual(build.mount_wheels(dockerfile), dockerfile)

    def test_prepare_applies_runtime_changes_even_without_cargo_cache_mounts(self):
        with tempfile.TemporaryDirectory() as checkout:
            path = Path(checkout) / "Dockerfile"
            path.write_text("FROM chef AS builder\nRUN cargo install\nFROM debian\n" + self.copy + self.install)
            env = {"SERVICE_TAG": "0.24.0", "SERVICE_REPOSITORY_NAME": "mozilla-services/syncstorage-rs",
                   "BUILD_URL": "local"}
            with patch.dict(os.environ, env), patch.object(build.subprocess, "run") as git:
                git.return_value.stdout = "test-commit\n"
                self.assertEqual(build.main([checkout]), 0)
            builder, runtime = path.read_text().split("FROM debian\n")
            self.assertIn("ENV CARGO_PROFILE_RELEASE_STRIP=debuginfo\n", builder)
            self.assertNotIn("CARGO_PROFILE", runtime)
            self.assertNotIn(self.copy, runtime)
            self.assertIn("from=builder,source=/app/wheels,target=/tmp/wheels", runtime)


if __name__ == "__main__":
    unittest.main()
