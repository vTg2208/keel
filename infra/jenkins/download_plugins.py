"""Fetch the official resolved plugin lock with bounded concurrency and verified caching."""

import argparse
import hashlib
import http.client
import json
import re
import shutil
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DEFAULT_MIRROR = "https://sg.mirror.servanamanaged.com/jenkins/plugins"


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def download(item, cache, base_url=DEFAULT_MIRROR, retry_delay=1):
    name, version, checksum = item["name"], item["version"], item["sha256"]
    if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", value) for value in (name, version)):
        raise ValueError("Invalid plugin name/version in lock")
    target = cache / f"{name}-{version}.jpi"
    if target.exists() and digest(target) == checksum:
        return target
    cache.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    mirrors = (
        (
            base_url,
            "https://mirror.xmission.com/jenkins/plugins",
            "https://archives.jenkins.io/plugins",
        )
        if base_url == DEFAULT_MIRROR
        else (base_url,)
    )
    for attempt in range(5):
        url = f"{mirrors[attempt % len(mirrors)]}/{name}/{version}/{name}.hpi"
        try:
            with urllib.request.urlopen(url, timeout=30) as response, partial.open("wb") as output:
                shutil.copyfileobj(response, output, length=256 * 1024)
            if digest(partial) != checksum:
                raise ValueError("Plugin SHA-256 does not match official lock")
            partial.replace(target)
            print(f"Validated {name}:{version}", flush=True)
            return target
        except (OSError, http.client.HTTPException, ValueError):
            partial.unlink(missing_ok=True)
            if attempt == 4:
                raise
            time.sleep(retry_delay * 2**attempt)
    raise RuntimeError("Plugin download did not finish")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    parser.add_argument("--cache", type=Path, default=Path("/tmp/payops-plugin-archives"))
    parser.add_argument("--output", type=Path, default=Path("/usr/share/jenkins/ref/plugins"))
    args = parser.parse_args()
    plugins = json.loads(args.lock.read_text())["plugins"]
    paths = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        work = {pool.submit(download, item, args.cache): item for item in plugins}
        for future in as_completed(work):
            item = work[future]
            paths[item["name"]] = future.result()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, path in paths.items():
        shutil.copyfile(path, args.output / f"{name}.jpi")
    (args.output.parent / "plugins.lock.txt").write_text(
        "".join(f"{item['name']}:{item['version']}\n" for item in plugins)
    )
    print(f"Installed {len(paths)} pinned, checksum-verified plugins", flush=True)


if __name__ == "__main__":
    main()
