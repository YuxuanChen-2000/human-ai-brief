"""Publish the local Git history through GitHub's official Git Database API.

Uses an existing GitHub CLI login; no credentials are printed or saved here.
Only fast-forwards main, and verifies content hashes before updating the ref.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import base64
import datetime as dt
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def git(*args, binary=False, input=None):
    result = subprocess.run(["git", *args], cwd=ROOT, input=input, capture_output=True, check=True)
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gh", default="gh")
    parser.add_argument("--repository", default="YuxuanChen-2000/human-ai-brief")
    args = parser.parse_args()
    site = json.loads((ROOT / "config" / "site.json").read_text(encoding="utf-8"))
    if args.repository != site["repository"]:
        raise RuntimeError("Repository must match config/site.json")
    repo = args.repository

    def api(path, method="GET", body=None, allow404=False):
        command = [args.gh, "api", "--method", method, path]
        if body is not None:
            command.extend(["--input", "-"])
        result = subprocess.run(command, cwd=ROOT, input=json.dumps(body, ensure_ascii=False).encode() if body is not None else None, capture_output=True)
        if result.returncode:
            if allow404 and (b"HTTP 404" in result.stderr or b"Git Repository is empty" in result.stdout + result.stderr):
                return None
            raise RuntimeError(method + " " + path + ": " + result.stderr.decode("utf-8", errors="replace"))
        return json.loads(result.stdout) if result.stdout.strip() else None

    account = api("user")
    if account["login"].lower() != repo.split("/")[0].lower():
        raise RuntimeError("GitHub login does not match the intended owner")
    info = api("repos/" + repo, allow404=True)
    if info is None:
        info = api("user/repos", "POST", {"name": repo.split("/")[1], "private": False, "description": site["description"]})
    if info["private"]:
        raise RuntimeError("Refusing to change an existing private repository")
    if not (ROOT / ".git").exists():
        git("init", "--initial-branch=main")
    if Path(git("rev-parse", "--show-toplevel")).resolve() != ROOT.resolve():
        raise RuntimeError("Unexpected Git root")
    if git("branch", "--show-current") != "main":
        raise RuntimeError("Expected main branch")
    git("config", "user.name", account["login"])
    git("config", "user.email", f"{account['id']}+{account['login']}@users.noreply.github.com")
    git("add", "dist", "config", "scripts", "tests", "data", ".github", ".gitignore", "README.md")
    if git("diff", "--cached", "--name-only"):
        git("commit", "-m", "Prepare HumanAIBrief public website")
    remote = api(f"repos/{repo}/git/ref/heads/main", allow404=True)
    local_history = git("rev-list", "HEAD").splitlines()
    if remote is None or remote["object"]["sha"] not in local_history:
        if remote is None and info.get("size", 0) > 0:
            raise RuntimeError("Existing nonempty repository has no main branch; inspect it first")
        # GitHub's Git Database API requires an initialized repository. Create a
        # small seed through the Contents API, then import its exact Git objects.
        seed = b"# HumanAIBrief\n\nPreparing the human-AI collaboration literature website.\n"
        identity = {"name": account["login"], "email": f"{account['id']}+{account['login']}@users.noreply.github.com"}
        if remote is None:
            initial = api(f"repos/{repo}/contents/README.md", "PUT", {"message": "Initialize HumanAIBrief", "content": base64.b64encode(seed).decode(), "branch": "main", "author": identity, "committer": identity})
            seed_sha = initial["commit"]["sha"]
        else:
            seed_sha = remote["object"]["sha"]
        seed_commit = api(f"repos/{repo}/git/commits/{seed_sha}")
        blob = git("hash-object", "-w", "--stdin", input=seed)
        seed_tree = git("mktree", input=f"100644 blob {blob}\tREADME.md\n".encode())
        if seed_tree != seed_commit["tree"]["sha"] or seed_commit["parents"] or seed_commit["message"] != "Initialize HumanAIBrief":
            raise RuntimeError("Seed tree mismatch")
        patch = subprocess.run([args.gh, "api", f"repos/{repo}/commits/{seed_sha}", "-H", "Accept: application/vnd.github.patch"], capture_output=True, check=True).stdout.decode()
        offset = parsedate_to_datetime(next(line[6:] for line in patch.splitlines() if line.startswith("Date: "))).strftime("%z")
        def identity_line(person):
            timestamp = int(dt.datetime.fromisoformat(person["date"].replace("Z", "+00:00")).timestamp())
            return f"{person['name']} <{person['email']}> {timestamp} {offset}"
        raw = (f"tree {seed_tree}\nauthor {identity_line(seed_commit['author'])}\ncommitter {identity_line(seed_commit['committer'])}\n\n{seed_commit['message']}").encode()
        def object_sha(payload):
            return hashlib.sha1(b"commit " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
        if object_sha(raw) != seed_sha:
            verification = seed_commit.get("verification", {})
            if verification.get("payload") and verification.get("signature"):
                header, message = verification["payload"].split("\n\n", 1)
                signature = verification["signature"].rstrip("\n").replace("\n", "\n ")
                raw = (header + "\ngpgsig " + signature + "\n\n" + message).encode()
        if object_sha(raw) != seed_sha:
            raise RuntimeError("Cannot verify seed commit; local history was preserved")
        git("hash-object", "-t", "commit", "-w", "--stdin", input=raw)
        previous = git("rev-parse", "HEAD")
        git("update-ref", "refs/heads/local-before-api-" + previous[:7], previous)
        git("update-ref", "refs/heads/main", seed_sha, previous)
        git("add", "dist", "config", "scripts", "tests", ".github", ".gitignore", "README.md")
        git("commit", "-m", "Publish HumanAIBrief with four human-AI research topics")
        remote = api(f"repos/{repo}/git/ref/heads/main")
    head = git("rev-parse", "HEAD")
    if remote and remote["object"]["sha"] not in git("rev-list", "HEAD").splitlines():
        raise RuntimeError("Remote has new or unrelated history; inspect and synchronize before publishing")
    pending = git("rev-list", "--reverse", "HEAD" if not remote else remote["object"]["sha"] + "..HEAD").splitlines()
    uploaded = {line.split()[2] for line in git("ls-tree", "-r", remote["object"]["sha"]).splitlines()} if remote else set()
    for commit in pending:
        entries = []
        for line in git("ls-tree", "-r", commit).splitlines():
            metadata, path = line.split("\t", 1)
            mode, kind, sha = metadata.split()
            entries.append({"path": path, "mode": mode, "type": kind, "sha": sha})

        def upload(entry):
            sha = entry["sha"]
            payload = git("cat-file", "blob", sha, binary=True)
            if len(payload) > 1_000_000:
                print(f"Uploading {entry['path']} ({len(payload)} bytes)", flush=True)
            response = api(f"repos/{repo}/git/blobs", "POST", {"content": base64.b64encode(payload).decode(), "encoding": "base64"})
            if response["sha"] != sha:
                raise RuntimeError("Uploaded blob hash mismatch: " + entry["path"])
            return sha

        todo = {entry["sha"]: entry for entry in entries if entry["sha"] not in uploaded}
        with ThreadPoolExecutor(max_workers=3) as pool:
            for sha in pool.map(upload, todo.values()):
                uploaded.add(sha)
        tree = api(f"repos/{repo}/git/trees", "POST", {"tree": entries})
        if tree["sha"] != git("rev-parse", commit + "^{tree}"):
            raise RuntimeError("Uploaded tree hash mismatch")
        fields = git("show", "-s", "--format=%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI%x00%B", commit).split("\0", 6)
        author_name, author_email, author_date, committer_name, committer_email, committer_date, message = fields
        parents = git("show", "-s", "--format=%P", commit).split()
        created = api(f"repos/{repo}/git/commits", "POST", {"message": message.rstrip("\n") + "\n", "tree": tree["sha"], "parents": parents,
                      "author": {"name": author_name, "email": author_email, "date": author_date},
                      "committer": {"name": committer_name, "email": committer_email, "date": committer_date}})
        if created["sha"] != commit:
            raise RuntimeError("Commit hash mismatch; main was not changed")
        print("Verified commit " + commit[:7], flush=True)
    if remote is None:
        api(f"repos/{repo}/git/refs", "POST", {"ref": "refs/heads/main", "sha": head})
    elif remote["object"]["sha"] != head:
        api(f"repos/{repo}/git/refs/heads/main", "PATCH", {"sha": head, "force": False})
    print("Published main: https://github.com/" + repo, flush=True)
    pages = api(f"repos/{repo}/pages", allow404=True)
    api(f"repos/{repo}/pages", "POST" if pages is None else "PUT", {"build_type": "workflow"})
    # An OAuth-authenticated ref update triggers the push workflow. Dispatch only
    # when no source changed, avoiding a duplicate full collection on each publish.
    if not pending:
        api(f"repos/{repo}/actions/workflows/daily-update.yml/dispatches", "POST", {"ref": "main"})
    print("Pages configured; deployment requested.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Publish failed: " + str(error), file=sys.stderr)
        sys.exit(1)



