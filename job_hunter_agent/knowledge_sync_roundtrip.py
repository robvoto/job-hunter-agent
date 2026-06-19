"""Round-trip knowledge sync between a desktop SQLite DB and AWS."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
from pathlib import Path

DEFAULT_AWS_HOST = os.environ.get(
    "JOB_HUNTER_SYNC_AWS_HOST",
    "ec2-32-236-144-98.ap-southeast-2.compute.amazonaws.com",
)
DEFAULT_SSH_KEY = os.environ.get("JOB_HUNTER_SYNC_SSH_KEY", "/tmp/KeyPair-JobHunter.pem")
DEFAULT_LOCAL_DB = os.environ.get("JOB_HUNTER_SYNC_LOCAL_DB")
DEFAULT_REMOTE_DB = os.environ.get(
    "JOB_HUNTER_SYNC_REMOTE_DB",
    "/var/lib/job-hunter/data/job_hunter.db",
)
DEFAULT_REMOTE_USER = os.environ.get("JOB_HUNTER_SYNC_REMOTE_USER", "ubuntu")
DEFAULT_REMOTE_TMP = os.environ.get("JOB_HUNTER_SYNC_REMOTE_TMP", "/tmp/desktop.db")
DEFAULT_REMOTE_APP_DIR = os.environ.get(
    "JOB_HUNTER_SYNC_REMOTE_APP_DIR",
    "/home/ubuntu/job-hunter-agent",
)


def _resolve_local_db(local_db: str | None) -> Path:
    if local_db:
        return Path(local_db).expanduser().resolve()

    env_path = os.environ.get("JOB_HUNTER_DB_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()

    for candidate in (Path("data/app.db"), Path("data/job_hunter.db")):
        resolved = candidate.expanduser().resolve()
        if resolved.exists():
            return resolved

    raise FileNotFoundError(
        "Could not find a local database. Pass --local-db or set JOB_HUNTER_DB_PATH."
    )


def _ssh_target(user: str, host: str) -> str:
    return f"{user}@{host}"


def _run_checked(command: list[str]) -> None:
    subprocess.run(command, check=True)


def sync_knowledge_roundtrip(
    *,
    host: str,
    key: str,
    local_db: str | None = None,
    remote_db: str = "/var/lib/job-hunter/data/job_hunter.db",
    remote_user: str = "ubuntu",
    remote_tmp: str = "/tmp/desktop.db",
    remote_app_dir: str = "/home/ubuntu/job-hunter-agent",
) -> Path:
    """Push the local DB to AWS, merge there, then pull the merged DB back."""
    local_db_path = _resolve_local_db(local_db)
    if not local_db_path.exists():
        raise FileNotFoundError(f"Local database does not exist: {local_db_path}")

    target = _ssh_target(remote_user, host)
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    ssh_prefix = [
        "ssh",
        "-i",
        key,
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        target,
    ]
    scp_prefix = [
        "scp",
        "-i",
        key,
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
    ]
    remote_merge_cmd = (
        f"cd {shlex.quote(remote_app_dir)} && "
        "uv run python -m job_hunter_agent.knowledge_sync "
        f"--left-db {shlex.quote(remote_tmp)} "
        f"--right-db {shlex.quote(remote_db)}"
    )

    print(f"Uploading {local_db_path} to {target}:{remote_tmp}")
    _run_checked([*scp_prefix, str(local_db_path), f"{target}:{remote_tmp}"])

    try:
        print(f"Merging knowledge on {target}")
        _run_checked([*ssh_prefix, remote_merge_cmd])

        local_tmp = local_db_path.with_name(f"{local_db_path.name}.syncing")
        print(f"Downloading merged DB to {local_tmp}")
        _run_checked([*scp_prefix, f"{target}:{remote_tmp}", str(local_tmp)])
        local_tmp.replace(local_db_path)
    finally:
        cleanup_cmd = f"rm -f {shlex.quote(remote_tmp)}"
        try:
            _run_checked([*ssh_prefix, cleanup_cmd])
        except Exception:
            pass

    return local_db_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Push a local Job Hunter DB to AWS, merge knowledge there, and pull the merged DB back."
    )
    parser.add_argument("--host", default=DEFAULT_AWS_HOST, help="AWS host or public DNS name.")
    parser.add_argument("--key", default=DEFAULT_SSH_KEY, help="SSH private key path.")
    parser.add_argument(
        "--local-db",
        default=DEFAULT_LOCAL_DB,
        help="Local SQLite DB path. Defaults to JOB_HUNTER_DB_PATH or data/app.db.",
    )
    parser.add_argument(
        "--remote-db",
        default=DEFAULT_REMOTE_DB,
        help="Remote AWS SQLite DB path.",
    )
    parser.add_argument("--remote-user", default=DEFAULT_REMOTE_USER, help="SSH user for the AWS host.")
    parser.add_argument("--remote-tmp", default=DEFAULT_REMOTE_TMP, help="Temporary file path on AWS.")
    parser.add_argument(
        "--remote-app-dir",
        default=DEFAULT_REMOTE_APP_DIR,
        help="App checkout directory on AWS.",
    )
    args = parser.parse_args(argv)

    sync_knowledge_roundtrip(
        host=args.host,
        key=args.key,
        local_db=args.local_db,
        remote_db=args.remote_db,
        remote_user=args.remote_user,
        remote_tmp=args.remote_tmp,
        remote_app_dir=args.remote_app_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
