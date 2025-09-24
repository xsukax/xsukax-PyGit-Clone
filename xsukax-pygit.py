#!/usr/bin/env python3
"""
xsukax-pygit.py — Cross-platform 'git clone' utility by xsukax

Features:
- Clone from GitHub HTTPS URLs by downloading a snapshot ZIP of the default branch
- Clone from a local path by copying the directory tree (preserves .git if present)
- Works on Windows, Linux, and MacOS without requiring git tool
- Compatible with Python 3.7+

Limitations:
- No Git protocol support, no history for GitHub ZIP clones, no fetch/push operations
"""

import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Optional
from urllib import request, parse
from urllib.error import URLError, HTTPError


def is_url(s: str) -> bool:
    """Check if string is a valid HTTP/HTTPS URL."""
    try:
        u = parse.urlparse(s)
        return u.scheme in ("http", "https")
    except Exception:
        return False


def ensure_empty_dir(dest: Path) -> None:
    """Ensure destination directory exists and is empty."""
    if dest.exists():
        if dest.is_file():
            raise SystemExit(f"fatal: destination path '{dest}' exists and is a file")
        if any(dest.iterdir()):
            raise SystemExit(f"fatal: destination path '{dest}' already exists and is not empty")
    else:
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise SystemExit(f"fatal: cannot create directory '{dest}': {e}")


def derive_repo_name_from_url(url: str) -> str:
    """Extract repository name from GitHub URL."""
    p = [x for x in parse.urlparse(url).path.strip("/").split("/") if x]
    if len(p) >= 2:
        name = p[1]
        return name[:-4] if name.endswith(".git") else name
    return "repo"


def github_owner_repo(url: str):
    """Extract owner and repository name from GitHub URL."""
    u = parse.urlparse(url)
    if "github.com" not in u.netloc.lower():
        raise SystemExit("fatal: only GitHub HTTPS URLs are supported for remote clones")
    
    parts = [p for p in u.path.strip("/").split("/") if p]
    if len(parts) < 2:
        raise SystemExit("fatal: invalid GitHub URL (expected https://github.com/<owner>/<repo>[.git])")
    
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


def http_get_json(url: str):
    """Perform HTTP GET request and return JSON response."""
    req = request.Request(url, headers={"User-Agent": "xsukax-pygit/1.0"})
    try:
        with request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except (URLError, HTTPError, json.JSONDecodeError) as e:
        raise Exception(f"Failed to fetch JSON from {url}: {e}")


def http_get_bytes(url: str) -> bytes:
    """Perform HTTP GET request and return raw bytes."""
    req = request.Request(url, headers={"User-Agent": "xsukax-pygit/1.0"})
    try:
        with request.urlopen(req, timeout=60) as r:
            return r.read()
    except (URLError, HTTPError) as e:
        raise Exception(f"Failed to download from {url}: {e}")


def github_default_branch(owner: str, repo: str) -> str:
    """Get the default branch name from GitHub API, fallback to 'main'."""
    try:
        print(f"Fetching repository information for {owner}/{repo}...")
        meta = http_get_json(f"https://api.github.com/repos/{owner}/{repo}")
        branch = meta.get("default_branch")
        if branch:
            return branch
    except Exception as e:
        print(f"Warning: Could not fetch default branch ({e}), trying 'main'...")
    return "main"


def download_github_zip(owner: str, repo: str, branch: str) -> bytes:
    """Download ZIP archive of specified branch from GitHub."""
    url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{branch}"
    print(f"Downloading {owner}/{repo} (branch: {branch})...")
    return http_get_bytes(url)


def extract_zip_to(zip_bytes: bytes, dest: Path) -> None:
    """Extract ZIP archive to destination directory."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir = Path(tmpdir)
                print("Extracting archive...")
                zf.extractall(tmpdir)
                
                # Find the single top-level directory
                roots = [p for p in tmpdir.iterdir() if p.is_dir()]
                if len(roots) != 1:
                    raise SystemExit("fatal: unexpected archive layout - expected single root directory")
                
                root = roots[0]
                # Move contents from the root directory to destination
                for item in root.iterdir():
                    target = dest / item.name
                    if item.is_dir():
                        shutil.move(str(item), str(target))
                    else:
                        shutil.move(str(item), str(target))
    except zipfile.BadZipFile:
        raise SystemExit("fatal: downloaded file is not a valid ZIP archive")
    except Exception as e:
        raise SystemExit(f"fatal: failed to extract archive: {e}")


def clone_github(url: str, dest: Optional[Path] = None) -> None:
    """Clone a GitHub repository by downloading ZIP snapshot."""
    owner, repo = github_owner_repo(url)
    
    if dest is None:
        dest = Path(repo)
    dest = dest.resolve()
    
    print(f"Cloning into '{dest}'...")
    ensure_empty_dir(dest)

    branch = github_default_branch(owner, repo)
    
    try:
        data = download_github_zip(owner, repo, branch)
    except Exception:
        # Try fallback branch if the detected/default branch fails
        fallback = "master" if branch != "master" else "main"
        print(f"Branch '{branch}' failed, trying '{fallback}'...")
        try:
            data = download_github_zip(owner, repo, fallback)
            branch = fallback
        except Exception as e:
            raise SystemExit(f"fatal: failed to download GitHub archive: {e}")

    extract_zip_to(data, dest)
    print(f"Successfully cloned {owner}/{repo} (branch: {branch}) into '{dest}'")


def clone_local(src: str, dest: Optional[Path] = None) -> None:
    """Clone a local directory by copying it."""
    src_path = Path(src).expanduser().resolve()
    
    if not src_path.exists():
        raise SystemExit(f"fatal: source path '{src_path}' does not exist")
    if not src_path.is_dir():
        raise SystemExit(f"fatal: source path '{src_path}' is not a directory")
    
    if dest is None:
        dest = Path(src_path.name)
    dest = dest.resolve()
    
    print(f"Cloning local directory into '{dest}'...")
    
    if dest.exists():
        if dest.is_file():
            raise SystemExit(f"fatal: destination path '{dest}' exists and is a file")
        if any(dest.iterdir()):
            raise SystemExit(f"fatal: destination path '{dest}' already exists and is not empty")
        dest.rmdir()  # Remove empty directory for copytree
    
    try:
        shutil.copytree(src_path, dest)
        print(f"Successfully cloned local directory '{src_path}' into '{dest}'")
    except Exception as e:
        raise SystemExit(f"fatal: failed to copy directory: {e}")


def main(argv=None):
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="xsukax-pygit",
        description="Cross-platform git clone utility by xsukax",
        epilog="Examples:\n"
               "  %(prog)s clone https://github.com/user/repo.git\n"
               "  %(prog)s clone https://github.com/user/repo.git my-folder\n"
               "  %(prog)s clone /path/to/local/repo\n"
               "  %(prog)s clone /path/to/local/repo my-copy",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Clone command
    clone_parser = subparsers.add_parser('clone', help='Clone a repository')
    clone_parser.add_argument('source', help='GitHub HTTPS URL or local directory path')
    clone_parser.add_argument('destination', nargs='?', help='Destination directory (optional)')
    
    args = parser.parse_args(argv)
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    if args.command == 'clone':
        dest_path = Path(args.destination) if args.destination else None
        
        if is_url(args.source):
            clone_github(args.source, dest_path)
        else:
            clone_local(args.source, dest_path)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
