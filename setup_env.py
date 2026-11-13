"""First-run setup: asks for the secret key and dealer login, saves them to .env.

Runs automatically from run.sh when .env has no SECRET_KEY. Re-run any time with:
    .venv/bin/python setup_env.py --force
"""
import getpass
import os
import secrets
import sys
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent / ".env"


def read_env(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def write_env(path: Path, values: dict) -> None:
    text = "".join(f"{k}={v}\n" for k, v in values.items())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # owner-only: it holds secrets
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def ask_secret(label: str, confirm: bool = False) -> str:
    while True:
        value = getpass.getpass(f"{label}: ")
        if not confirm or not value:
            return value
        if getpass.getpass("  Type it again to confirm: ") == value:
            return value
        print("  They did not match. Try again.")


def main(path: Path = ENV_PATH, force: bool = False) -> int:
    current = read_env(path)
    if current.get("SECRET_KEY") and not force:
        return 0
    if not sys.stdin.isatty():
        print("No SECRET_KEY set and no terminal to ask on. Create .env (see README) or set the "
              "SECRET_KEY / ADMIN_EMAIL / ADMIN_PASSWORD environment variables.", file=sys.stderr)
        return 1 if not os.environ.get("SECRET_KEY") else 0

    print("\nFirst-time setup (press Ctrl+C to cancel). Input for secrets is hidden.\n")
    key = ask_secret("Secret key (leave empty to generate a strong random one)")
    if not key:
        key = secrets.token_urlsafe(32)
        print("  Generated a random secret key.")
    elif len(key) < 16:
        print("  Note: that key is short and easier to guess. Fine for local testing, "
              "but use 16+ characters before going online.")

    default_email = current.get("ADMIN_EMAIL", "admin@gasagency.local")
    email = input(f"Dealer login email [{default_email}]: ").strip()
    email = (email or default_email).lower()
    password = ask_secret("Dealer password", confirm=True)
    while not password:
        print("  Password cannot be empty.")
        password = ask_secret("Dealer password", confirm=True)

    values = {**current, "SECRET_KEY": key, "ADMIN_EMAIL": email, "ADMIN_PASSWORD": password}
    write_env(path, values)
    print(f"\nSaved to {path.name} (owner-only, git-ignored). Starting the server...\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(force="--force" in sys.argv))
