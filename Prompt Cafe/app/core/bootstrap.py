from sqlalchemy.orm import Session

from sqlalchemy import text

from app.db.database import SessionLocal
from app.db.models import User
from app.api.dependencies import hash_password


def _ensure_community_prompt_columns(db: Session) -> None:
    columns = {row[1] for row in db.execute(text("PRAGMA table_info(community_prompts)")).fetchall()}
    if "usage_guide" not in columns:
        db.execute(text("ALTER TABLE community_prompts ADD COLUMN usage_guide TEXT"))
        db.commit()


def _ensure_user_favorite_consistency(db: Session) -> None:
    # Existing SQLite databases need a small data migration before the unique index can be added.
    db.execute(
        text(
            """
            DELETE FROM user_favorites
            WHERE rowid NOT IN (
                SELECT MIN(rowid)
                FROM user_favorites
                GROUP BY user_id, community_prompt_id
            )
            """
        )
    )
    db.execute(
        text(
            """
            UPDATE community_prompts
            SET favorite_count = (
                SELECT COUNT(*)
                FROM user_favorites
                WHERE user_favorites.community_prompt_id = community_prompts.id
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_user_favorites_user_community_prompt
            ON user_favorites(user_id, community_prompt_id)
            """
        )
    )
    db.commit()


def _normalize_last_login_times(db: Session) -> None:
    # Login audit timestamps are stored in UTC and provide a reliable source for legacy rows
    # that were previously written using the server's local time.
    db.execute(
        text(
            """
            UPDATE users
            SET last_login_at = (
                SELECT MAX(audit_logs.created_at)
                FROM audit_logs
                WHERE audit_logs.actor_id = users.id
                  AND audit_logs.action = 'login'
            )
            WHERE EXISTS (
                SELECT 1
                FROM audit_logs
                WHERE audit_logs.actor_id = users.id
                  AND audit_logs.action = 'login'
            )
            """
        )
    )
    db.commit()


def _seed_community_prompts(db: Session) -> None:
    from app.db.models import CommunityPrompt, Prompt

    if db.query(CommunityPrompt).count() > 0:
        return

    prompts = db.query(Prompt).order_by(Prompt.created_at.asc()).all()
    if not prompts:
        return

    owner = db.query(User).filter(User.role == "user").first() or db.query(User).first()
    if not owner:
        return

    seeded = []
    for index, prompt in enumerate(prompts[:3], start=1):
        seeded.append(
            CommunityPrompt(
                prompt_id=prompt.id,
                user_id=owner.id,
                title_snapshot=prompt.title,
                system_prompt_snapshot=prompt.system_prompt,
                user_prompt_snapshot=prompt.user_prompt,
                tags_snapshot=prompt.tags or [],
                description=prompt.description,
                usage_guide="填写变量后运行。",
                status="approved" if index != 2 else "pending",
                view_count=10 * index,
                favorite_count=3 * index,
            )
        )

    if seeded:
        db.add_all(seeded)
        db.commit()


def init_admin():
    db: Session = SessionLocal()

    try:
        _ensure_community_prompt_columns(db)

        admin = (
            db.query(User)
            .filter(User.role == "admin")
            .first()
        )

        if admin:
            print("Admin already exists")
        else:
            default_admin = User(
                username="superadmin",
                email="superadmin@example.com",
                password_hash=hash_password("superadmin123"),
                role="admin",
                status="active",
            )

            db.add(default_admin)
            db.commit()

            print("Default admin created")

        _seed_community_prompts(db)
        _ensure_user_favorite_consistency(db)
        _normalize_last_login_times(db)

    finally:
        db.close()
