#!/usr/bin/env python3

# Copyright 2026 gRPC authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

### Verifies that requirements.bazel.lock is the byte-identical output of
### `pip-compile --allow-unsafe --generate-hashes requirements.bazel.txt` run
### under the oldest supported Python version (matching the regen recipe
### documented in the header of requirements.bazel.txt). This keeps the lock
### in sync with the source requirements and guarantees it stays hash-pinned.

import difflib
import os
import shutil
import subprocess
import sys
import tempfile

PYTHON_DOCKER_IMAGE = "python:3.10"
REQUIREMENTS_TXT = "requirements.bazel.txt"
REQUIREMENTS_LOCK = "requirements.bazel.lock"


def repo_root():
    return (
        subprocess.check_output(["git", "rev-parse", "--show-toplevel"])
        .decode()
        .strip()
    )


def regenerate_lock(root, dest):
    """Run pip-compile in docker; write the regenerated lock to `dest`.

    Both files are copied into a tempdir so pip-compile sees the existing
    lock and preserves its pins where compatible (matching the contributor
    regen recipe in the requirements.bazel.txt header), without mutating
    the host repo.
    """
    with tempfile.TemporaryDirectory() as workdir:
        shutil.copy(
            os.path.join(root, REQUIREMENTS_TXT),
            os.path.join(workdir, REQUIREMENTS_TXT),
        )
        shutil.copy(
            os.path.join(root, REQUIREMENTS_LOCK),
            os.path.join(workdir, REQUIREMENTS_LOCK),
        )
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{workdir}:/work",
            "-w", "/work",
            PYTHON_DOCKER_IMAGE,
            "bash", "-c",
            "pip install --quiet --no-cache-dir pip-tools && "
            f"pip-compile --quiet --allow-unsafe --generate-hashes "
            f"--output-file={REQUIREMENTS_LOCK} {REQUIREMENTS_TXT} && "
            f"cat {REQUIREMENTS_LOCK}",
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            sys.stderr.write("pip-compile failed:\n")
            sys.stderr.write(result.stderr.decode())
            sys.exit(1)
        with open(dest, "wb") as f:
            f.write(result.stdout)


def main():
    root = repo_root()
    os.chdir(root)

    with tempfile.NamedTemporaryFile(suffix=".lock", delete=False) as tmp:
        regenerated_path = tmp.name
    try:
        regenerate_lock(root, regenerated_path)
        with open(REQUIREMENTS_LOCK) as f:
            committed = f.read()
        with open(regenerated_path) as f:
            regenerated = f.read()
        if committed == regenerated:
            return 0
        sys.stderr.write(
            f"{REQUIREMENTS_LOCK} is out of sync with {REQUIREMENTS_TXT}.\n\n"
            f"Regenerate from the repo root with:\n\n"
            f"  docker run -it --rm -v $(pwd):/grpc -w /grpc {PYTHON_DOCKER_IMAGE} \\\n"
            f"    bash -c 'pip install pip-tools && \\\n"
            f"             pip-compile --allow-unsafe --generate-hashes \\\n"
            f"               {REQUIREMENTS_TXT} -o {REQUIREMENTS_LOCK}'\n\n"
            f"Diff (committed vs regenerated):\n"
        )
        sys.stderr.writelines(
            difflib.unified_diff(
                committed.splitlines(keepends=True),
                regenerated.splitlines(keepends=True),
                fromfile=f"{REQUIREMENTS_LOCK} (committed)",
                tofile=f"{REQUIREMENTS_LOCK} (regenerated)",
            )
        )
        return 1
    finally:
        os.unlink(regenerated_path)


if __name__ == "__main__":
    sys.exit(main())
