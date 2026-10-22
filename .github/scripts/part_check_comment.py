"""Publish the part check images and post the report as a pull request comment.

The input directory comes from a workflow that ran code from a pull request.
Treat all of it as untrusted data: check the pull request number against the
GitHub API, copy only PNG files with safe names, and do not run anything from it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MARKER = "<!-- m17lib-check -->"
IMAGE_BRANCH = "part-check-images"
SAFE_PNG = re.compile(r"^[A-Za-z0-9._-]+\.png$")
MAX_IMAGE_BYTES = 3_000_000
MAX_COMMENT = 60_000


def gh(*args: str, data: dict | None = None) -> str:
    cmd = ["gh", "api", *args]
    if data is not None:
        cmd += ["--input", "-"]
    result = subprocess.run(cmd, input=json.dumps(data) if data else None, capture_output=True, text=True, check=True)
    return result.stdout


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def main() -> int:
    src = Path(sys.argv[1])
    repo = os.environ["REPO"]
    head_sha = os.environ["RUN_HEAD_SHA"]

    number = (src / "pr-number").read_text().strip()
    if not number.isdigit():
        raise SystemExit("invalid pull request number")
    pr = json.loads(gh(f"repos/{repo}/pulls/{number}"))
    if pr["head"]["sha"] != head_sha:
        print("The pull request has newer commits. Skip this result.")
        return 0

    images = [p for p in sorted(src.iterdir())
              if SAFE_PNG.match(p.name) and p.stat().st_size <= MAX_IMAGE_BYTES
              and p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"]
    folder = f"pr-{number}/{head_sha}"
    if images:
        publish_images(repo, folder, images)
    base_url = f"https://raw.githubusercontent.com/{repo}/{IMAGE_BRANCH}/{folder}/"
    names = {p.name for p in images}

    report_file = src / "report.md"
    report = report_file.read_text(encoding="utf-8") if report_file.is_file() else ""
    if not report.startswith(MARKER):
        report = f"{MARKER}\n## Library check\n\nThe check did not make a report. See the workflow log.\n"
    # Point image links to the published files. Remove links to files that were not published.
    report = re.sub(r'<img src="([^"/]+)"[^>]*>',
                    lambda m: f'<img src="{base_url}{m.group(1)}" width="260">' if m.group(1) in names else "",
                    report)
    report = report[:MAX_COMMENT] + f"\n\nWorkflow run: {os.environ['RUN_URL']}\n"

    comments = json.loads(gh(f"repos/{repo}/issues/{number}/comments", "--paginate", "--slurp"))
    existing = [c for page in comments for c in page
                if c["user"]["login"] == "github-actions[bot]" and c["body"].startswith(MARKER)]
    if existing:
        gh("-X", "PATCH", f"repos/{repo}/issues/comments/{existing[-1]['id']}", data={"body": report})
    else:
        gh("-X", "POST", f"repos/{repo}/issues/{number}/comments", data={"body": report})
    print(f"comment posted to pull request #{number}")
    return 0


def publish_images(repo: str, folder: str, images: list[Path]) -> None:
    """Commit the images to a separate branch, so that the comment can show them."""
    token = os.environ["GH_TOKEN"]
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        git(work, "init", "-q")
        git(work, "remote", "add", "origin", f"https://x-access-token:{token}@github.com/{repo}.git")
        if git(work, "fetch", "-q", "--depth", "1", "origin", IMAGE_BRANCH, check=False).returncode == 0:
            git(work, "checkout", "-q", "-b", IMAGE_BRANCH, "FETCH_HEAD")
        else:
            git(work, "checkout", "-q", "--orphan", IMAGE_BRANCH)
            (work / "README.md").write_text("Images for the part check comments. Do not merge this branch.\n")
        target = work / folder
        target.mkdir(parents=True, exist_ok=True)
        for image in images:
            shutil.copyfile(image, target / image.name)
        git(work, "add", "-A")
        git(work, "-c", "user.name=github-actions[bot]",
            "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "commit", "-q", "-m", f"Add part check images for {folder}")
        git(work, "push", "-q", "origin", IMAGE_BRANCH)


if __name__ == "__main__":
    sys.exit(main())
