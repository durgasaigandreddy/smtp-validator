"""Admin CLI.  docker compose run --rm api python -m app.cli <command>"""
import argparse

from .auth import create_key
from .db import init_db, q


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-key")
    c.add_argument("name")
    c.add_argument("--admin", action="store_true")
    sub.add_parser("list-keys")
    r = sub.add_parser("revoke-key")
    r.add_argument("id", type=int)
    sub.add_parser("init-db")
    a = p.parse_args()

    init_db()
    if a.cmd == "create-key":
        print("API key (shown once, store it safely):")
        print(create_key(a.name, a.admin))
    elif a.cmd == "list-keys":
        for k in q("SELECT id, name, is_admin, active, created_at FROM api_keys ORDER BY id"):
            print(k)
    elif a.cmd == "revoke-key":
        q("UPDATE api_keys SET active = false WHERE id = %s", (a.id,))
        print("revoked")
    elif a.cmd == "init-db":
        print("schema ready")


if __name__ == "__main__":
    main()
