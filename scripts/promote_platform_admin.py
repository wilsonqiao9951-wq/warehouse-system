import sys

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models import User


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.promote_platform_admin admin@example.com")
        return 2

    email = sys.argv[1].strip().lower()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if not user:
            print(f"User not found: {email}")
            return 1
        user.is_platform_admin = True
        user.is_active = True
        db.add(user)
        db.commit()
        print(f"Platform administrator enabled: {email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
