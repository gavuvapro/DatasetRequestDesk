"""Management CLI: `python -m app.cli <command>`.

Commands:
    seed-users            Create users from seed/users.json (idempotent).
    import-csv <path>     Import episodes from a CSV file (idempotent).
    create-user <email> <password> <role> [name] [organisation]
"""
import argparse
import json
import sys

from app.config import settings
from app.database import SessionLocal
from app.core.security import hash_password


def _seed_users(path: str) -> None:
    from app.models import User
    from app.models.user import UserRole

    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)

    db = SessionLocal()
    created, existing = 0, 0
    try:
        for entry in raw:
            email = str(entry["email"]).strip().lower()
            if db.query(User).filter(User.email == email).first():
                existing += 1
                continue
            role = UserRole(str(entry["role"]).strip().lower())
            user = User(
                email=email,
                password_hash=hash_password(str(entry["password"])),
                role=role,
                name=str(entry.get("name", email)).strip(),
                organisation=entry.get("organisation"),
            )
            db.add(user)
            created += 1
        db.commit()
    finally:
        db.close()
    print(json.dumps({"users_created": created, "users_existing": existing}))


def _import_csv(path: str) -> None:
    from app.services.import_service import import_csv

    db = SessionLocal()
    try:
        report = import_csv(db, path)
    finally:
        db.close()
    print(json.dumps(report, indent=2))


def _create_user(email: str, password: str, role: str, name: str, organisation: str) -> None:
    from app.models import User
    from app.models.user import UserRole

    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == email.lower()).first():
            print(json.dumps({"error": f"user {email} already exists"}))
            sys.exit(1)
        user = User(
            email=email.strip().lower(),
            password_hash=hash_password(password),
            role=UserRole(role.lower()),
            name=name or email,
            organisation=organisation or None,
        )
        db.add(user)
        db.commit()
        print(json.dumps({"created": user.email, "role": user.role.value}))
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli", description="Dataset Request Desk management CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("seed-users", help="Seed users from the users JSON file")

    p_import = sub.add_parser("import-csv", help="Import episodes from a CSV file")
    p_import.add_argument("path", help="Path to the CSV file")

    p_user = sub.add_parser("create-user", help="Create a single user")
    p_user.add_argument("email")
    p_user.add_argument("password")
    p_user.add_argument("role", choices=["admin", "operator", "client"])
    p_user.add_argument("--name", default="")
    p_user.add_argument("--organisation", default="")

    args = parser.parse_args()

    if args.command == "seed-users":
        _seed_users(settings.seed_users_file)
    elif args.command == "import-csv":
        _import_csv(args.path)
    elif args.command == "create-user":
        _create_user(args.email, args.password, args.role, args.name, args.organisation)


if __name__ == "__main__":
    main()
