import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    func,
    insert,
    select,
    update,
    text,
)

DATA_DIR = Path("data")
DEFAULT_SQLITE_URL = f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True, connect_args=connect_args)
metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String(255), nullable=False, unique=True),
    Column("password_hash", String(512), nullable=False),
    Column("created_at", String(64), nullable=False),
)

user_sessions = Table(
    "user_sessions",
    metadata,
    Column("token", String(255), primary_key=True),
    Column("user_id", Integer, nullable=False),
    Column("created_at", String(64), nullable=False),
    Column("expires_at", String(64), nullable=False),
)

analysis_history = Table(
    "analysis_history",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(128), nullable=False),
    Column("user_id", Integer, nullable=True),
    Column("input_url", Text, nullable=False),
    Column("normalized_url", Text, nullable=True),
    Column("source", String(64), nullable=True),
    Column("extraction_kind", String(64), nullable=True),
    Column("extracted_chars", Integer, nullable=False, default=0),
    Column("duration_ms", Integer, nullable=False, default=0),
    Column("summary", Text, nullable=True),
    Column("global_perspective", Text, nullable=True),
    Column("top_signal", Text, nullable=True),
    Column("left_pct", String(32), nullable=True),
    Column("center_pct", String(32), nullable=True),
    Column("right_pct", String(32), nullable=True),
    Column("result_json", Text, nullable=True),
    Column("created_at", String(64), nullable=False),
)

analysis_jobs = Table(
    "analysis_jobs",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("session_id", String(128), nullable=False),
    Column("user_id", Integer, nullable=True),
    Column("input_url", Text, nullable=False),
    Column("status", String(32), nullable=False),
    Column("error", Text, nullable=True),
    Column("result_json", Text, nullable=True),
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
)

feedback = Table(
    "feedback",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("analysis_id", Integer, nullable=True),
    Column("session_id", String(128), nullable=False),
    Column("user_id", Integer, nullable=True),
    Column("vote", String(8), nullable=False),
    Column("note", Text, nullable=True),
    Column("created_at", String(64), nullable=False),
)

events = Table(
    "events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(128), nullable=True),
    Column("user_id", Integer, nullable=True),
    Column("event_type", String(128), nullable=False),
    Column("metadata_json", Text, nullable=True),
    Column("created_at", String(64), nullable=False),
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> Dict[str, Any]:
    return dict(row._mapping)


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    metadata.create_all(engine)
    _run_sqlite_migrations_if_needed()


def _run_sqlite_migrations_if_needed() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return

    migrations = {
        "analysis_history": {
            "user_id": "INTEGER",
        },
        "analysis_jobs": {
            "user_id": "INTEGER",
        },
        "feedback": {
            "user_id": "INTEGER",
        },
        "events": {
            "user_id": "INTEGER",
        },
    }

    with engine.begin() as conn:
        for table_name, cols in migrations.items():
            existing = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            existing_names = {row[1] for row in existing}
            for col_name, col_type in cols.items():
                if col_name not in existing_names:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))


def create_user(email: str, password_hash: str) -> int:
    with engine.begin() as conn:
        exists = conn.execute(select(users.c.id).where(users.c.email == email.lower())).first()
        if exists:
            raise ValueError("Email already registered")

        result = conn.execute(
            insert(users).values(email=email.lower(), password_hash=password_hash, created_at=_utc_now_iso())
        )
        return int(result.inserted_primary_key[0])


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    with engine.begin() as conn:
        row = conn.execute(select(users).where(users.c.email == email.lower())).first()
    return _row_to_dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    with engine.begin() as conn:
        row = conn.execute(select(users).where(users.c.id == int(user_id))).first()
    return _row_to_dict(row) if row else None


def create_user_session(token: str, user_id: int, expires_at_iso: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(user_sessions).values(
                token=token,
                user_id=int(user_id),
                created_at=_utc_now_iso(),
                expires_at=expires_at_iso,
            )
        )


def get_user_by_session_token(token: str) -> Optional[Dict[str, Any]]:
    with engine.begin() as conn:
        session_row = conn.execute(select(user_sessions).where(user_sessions.c.token == token)).first()
        if not session_row:
            return None

        session_dict = _row_to_dict(session_row)
        if session_dict.get("expires_at") and session_dict["expires_at"] < _utc_now_iso():
            conn.execute(delete(user_sessions).where(user_sessions.c.token == token))
            return None

        user_row = conn.execute(select(users).where(users.c.id == session_dict["user_id"])).first()
        return _row_to_dict(user_row) if user_row else None


def delete_user_session(token: str) -> None:
    with engine.begin() as conn:
        conn.execute(delete(user_sessions).where(user_sessions.c.token == token))


def log_event(
    session_id: str,
    event_type: str,
    metadata_payload: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None,
) -> None:
    payload = json.dumps(metadata_payload or {})
    with engine.begin() as conn:
        conn.execute(
            insert(events).values(
                session_id=session_id,
                user_id=user_id,
                event_type=event_type,
                metadata_json=payload,
                created_at=_utc_now_iso(),
            )
        )


def save_history(record: Dict[str, Any]) -> int:
    with engine.begin() as conn:
        result = conn.execute(
            insert(analysis_history).values(
                session_id=record["session_id"],
                user_id=record.get("user_id"),
                input_url=record["input_url"],
                normalized_url=record.get("normalized_url"),
                source=record.get("source"),
                extraction_kind=record.get("extraction_kind"),
                extracted_chars=int(record.get("extracted_chars", 0)),
                duration_ms=int(record.get("duration_ms", 0)),
                summary=record.get("summary"),
                global_perspective=record.get("global_perspective"),
                top_signal=record.get("top_signal"),
                left_pct=str(record.get("left_pct", "")),
                center_pct=str(record.get("center_pct", "")),
                right_pct=str(record.get("right_pct", "")),
                result_json=json.dumps(record.get("result_json", {})),
                created_at=_utc_now_iso(),
            )
        )
        return int(result.inserted_primary_key[0])


def list_history(
    session_id: str,
    limit: int = 12,
    *,
    user_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    with engine.begin() as conn:
        if user_id is not None:
            query = (
                select(
                    analysis_history.c.id,
                    analysis_history.c.input_url,
                    analysis_history.c.source,
                    analysis_history.c.extraction_kind,
                    analysis_history.c.left_pct,
                    analysis_history.c.center_pct,
                    analysis_history.c.right_pct,
                    analysis_history.c.created_at,
                )
                .where(analysis_history.c.user_id == int(user_id))
                .order_by(analysis_history.c.id.desc())
                .limit(limit)
            )
        else:
            query = (
                select(
                    analysis_history.c.id,
                    analysis_history.c.input_url,
                    analysis_history.c.source,
                    analysis_history.c.extraction_kind,
                    analysis_history.c.left_pct,
                    analysis_history.c.center_pct,
                    analysis_history.c.right_pct,
                    analysis_history.c.created_at,
                )
                .where(analysis_history.c.session_id == session_id)
                .order_by(analysis_history.c.id.desc())
                .limit(limit)
            )

        rows = conn.execute(query).all()
    return [_row_to_dict(r) for r in rows]


def create_job(job_id: str, session_id: str, input_url: str, user_id: Optional[int] = None) -> None:
    now = _utc_now_iso()
    with engine.begin() as conn:
        conn.execute(
            insert(analysis_jobs).values(
                id=job_id,
                session_id=session_id,
                user_id=user_id,
                input_url=input_url,
                status="queued",
                error=None,
                result_json=None,
                created_at=now,
                updated_at=now,
            )
        )


def update_job_status(
    job_id: str,
    status: str,
    *,
    error: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(analysis_jobs)
            .where(analysis_jobs.c.id == job_id)
            .values(
                status=status,
                error=error,
                result_json=json.dumps(result) if result is not None else None,
                updated_at=_utc_now_iso(),
            )
        )


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with engine.begin() as conn:
        row = conn.execute(select(analysis_jobs).where(analysis_jobs.c.id == job_id)).first()
    if not row:
        return None
    payload = _row_to_dict(row)
    payload["result_json"] = json.loads(payload["result_json"]) if payload.get("result_json") else None
    return payload


def save_feedback(
    session_id: str,
    vote: str,
    note: str = "",
    analysis_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(feedback).values(
                analysis_id=analysis_id,
                session_id=session_id,
                user_id=user_id,
                vote=vote,
                note=note[:600],
                created_at=_utc_now_iso(),
            )
        )


def get_metrics() -> Dict[str, Any]:
    with engine.begin() as conn:
        analyses = conn.execute(select(func.count()).select_from(analysis_history)).scalar_one()
        feedback_total = conn.execute(select(func.count()).select_from(feedback)).scalar_one()
        positive = conn.execute(
            select(func.count()).select_from(feedback).where(feedback.c.vote == "up")
        ).scalar_one()
        negative = conn.execute(
            select(func.count()).select_from(feedback).where(feedback.c.vote == "down")
        ).scalar_one()
        jobs_total = conn.execute(select(func.count()).select_from(analysis_jobs)).scalar_one()
        failed_jobs = conn.execute(
            select(func.count()).select_from(analysis_jobs).where(analysis_jobs.c.status == "failed")
        ).scalar_one()
        users_total = conn.execute(select(func.count()).select_from(users)).scalar_one()

    return {
        "analyses_total": int(analyses or 0),
        "feedback_total": int(feedback_total or 0),
        "feedback_up": int(positive or 0),
        "feedback_down": int(negative or 0),
        "jobs_total": int(jobs_total or 0),
        "jobs_failed": int(failed_jobs or 0),
        "users_total": int(users_total or 0),
    }
