"""SQLAlchemy data models for review history."""

from contextlib import contextmanager
from datetime import timedelta
from typing import Any, Dict, List, Tuple

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .runtime import get_runtime_path, isoformat_utc, utcnow

Base = declarative_base()


class GitHubMonitorLog(Base):
    __tablename__ = "github_monitor_logs"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=utcnow)
    status = Column(String(50))  # success, error, warning, info
    message = Column(Text)
    details = Column(Text, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": isoformat_utc(self.timestamp),
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }


class GitHubReviewHistory(Base):
    __tablename__ = "github_review_history"

    id = Column(Integer, primary_key=True)
    repo_url = Column(String(255))
    pr_number = Column(Integer)
    pr_title = Column(Text)
    pr_url = Column(String(500))
    trigger_type = Column(String(50))  # webhook
    delivery_id = Column(String(100), nullable=True)
    head_sha = Column(String(64), nullable=True)
    status = Column(String(50))  # pending, processing, completed, failed, cancelled
    files_processed = Column(Integer, default=0)
    files_with_issues = Column(Integer, default=0)
    total_corrections = Column(Integer, default=0)
    processing_time = Column(Integer, nullable=True)  # seconds
    error_message = Column(Text, nullable=True)
    report_path = Column(String(500), nullable=True)
    email_sent = Column(Boolean, default=False)
    started_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "repo_url": self.repo_url,
            "pr_number": self.pr_number,
            "pr_title": self.pr_title,
            "pr_url": self.pr_url,
            "trigger_type": self.trigger_type,
            "delivery_id": self.delivery_id,
            "head_sha": self.head_sha,
            "status": self.status,
            "files_processed": self.files_processed,
            "files_with_issues": self.files_with_issues,
            "total_corrections": self.total_corrections,
            "processing_time": self.processing_time,
            "error_message": self.error_message,
            "report_path": self.report_path,
            "email_sent": self.email_sent,
            "started_at": isoformat_utc(self.started_at),
            "completed_at": isoformat_utc(self.completed_at),
        }


class GitHubMonitorConfig(Base):
    __tablename__ = "github_monitor_config"

    id = Column(Integer, primary_key=True)
    repo_url = Column(String(255))
    monitor_events = Column(JSON)
    is_running = Column(Boolean, default=False)
    webhook_enabled = Column(Boolean, default=False)
    webhook_secret = Column(Text, nullable=True)
    last_check = Column(DateTime, nullable=True)
    auto_review_enabled = Column(Boolean, default=True)
    email_notification_enabled = Column(Boolean, default=True)
    only_changed_files = Column(Boolean, default=True)
    review_model = Column(String(255), default="rule-based")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "repo_url": self.repo_url,
            "monitor_events": self.monitor_events or [],
            "is_running": self.is_running,
            "webhook_enabled": self.webhook_enabled,
            "webhook_secret_configured": bool(self.webhook_secret),
            "last_check": isoformat_utc(self.last_check),
            "auto_review_enabled": self.auto_review_enabled,
            "email_notification_enabled": self.email_notification_enabled,
            "only_changed_files": self.only_changed_files,
            "review_model": self.review_model or "rule-based",
            "created_at": isoformat_utc(self.created_at),
            "updated_at": isoformat_utc(self.updated_at),
        }


engine = None
Session = None
_database_path = None
_db_initialized = False


def _configure_database():
    global Session, _database_path, _db_initialized, engine
    database_path = get_runtime_path("github_monitor.db")
    if engine is None or _database_path != database_path:
        if engine is not None:
            engine.dispose()
        engine = create_engine(f"sqlite:///{database_path}")
        Session = sessionmaker(bind=engine)
        _database_path = database_path
        _db_initialized = False


def init_db():
    global _db_initialized
    _configure_database()
    Base.metadata.create_all(engine)
    _ensure_schema()
    _db_initialized = True


def _ensure_schema():
    _configure_database()

    def ensure_columns(conn, table_name: str, columns: Dict[str, str]):
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
        existing = {row[1] for row in rows}
        if not existing:
            return
        for name, ddl in columns.items():
            if name not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")

    with engine.connect() as conn:
        ensure_columns(
            conn,
            "github_monitor_config",
            {
                "repo_url": "repo_url TEXT",
                "monitor_events": "monitor_events TEXT",
                "is_running": "is_running BOOLEAN DEFAULT 0",
                "webhook_enabled": "webhook_enabled BOOLEAN DEFAULT 0",
                "webhook_secret": "webhook_secret TEXT",
                "last_check": "last_check DATETIME",
                "auto_review_enabled": "auto_review_enabled BOOLEAN DEFAULT 1",
                "email_notification_enabled": "email_notification_enabled BOOLEAN DEFAULT 1",
                "only_changed_files": "only_changed_files BOOLEAN DEFAULT 1",
                "review_model": "review_model TEXT DEFAULT 'rule-based'",
                "created_at": "created_at DATETIME",
                "updated_at": "updated_at DATETIME",
            },
        )
        ensure_columns(
            conn,
            "github_review_history",
            {
                "repo_url": "repo_url TEXT",
                "pr_number": "pr_number INTEGER",
                "pr_title": "pr_title TEXT",
                "pr_url": "pr_url TEXT",
                "trigger_type": "trigger_type TEXT",
                "delivery_id": "delivery_id TEXT",
                "head_sha": "head_sha TEXT",
                "status": "status TEXT",
                "files_processed": "files_processed INTEGER DEFAULT 0",
                "files_with_issues": "files_with_issues INTEGER DEFAULT 0",
                "total_corrections": "total_corrections INTEGER DEFAULT 0",
                "processing_time": "processing_time INTEGER",
                "error_message": "error_message TEXT",
                "report_path": "report_path TEXT",
                "email_sent": "email_sent BOOLEAN DEFAULT 0",
                "started_at": "started_at DATETIME",
                "completed_at": "completed_at DATETIME",
            },
        )
        conn.exec_driver_sql(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_github_review_delivery
            ON github_review_history(delivery_id)
            WHERE delivery_id IS NOT NULL
            """
        )
        conn.commit()


@contextmanager
def get_session():
    global _db_initialized
    _configure_database()
    if not _db_initialized:
        init_db()
        _db_initialized = True
    session = Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def purge_github_history_older_than(days: int) -> Tuple[int, int, List[str]]:
    """Delete review history and monitor logs past the cutoff.

    Returns the row counts removed plus the report files those reviews owned, so
    the caller can delete them alongside the rows that referenced them.
    """
    cutoff = utcnow() - timedelta(days=days)

    with get_session() as session:
        expired = (
            session.query(GitHubReviewHistory).filter(GitHubReviewHistory.started_at < cutoff).all()
        )
        report_paths = [review.report_path for review in expired if review.report_path]
        review_count = len(expired)
        for review in expired:
            session.delete(review)

        log_count = (
            session.query(GitHubMonitorLog)
            .filter(GitHubMonitorLog.timestamp < cutoff)
            .delete(synchronize_session=False)
        )

    return review_count, log_count, report_paths


def recover_interrupted_reviews() -> List[int]:
    """Mark webhook reviews interrupted by a previous process as failed."""
    message = "Review interrupted by service restart"
    recovered = []
    with get_session() as session:
        reviews = (
            session.query(GitHubReviewHistory)
            .filter(GitHubReviewHistory.status.in_(["pending", "processing"]))
            .all()
        )
        for review in reviews:
            review.status = "failed"
            review.error_message = message
            review.completed_at = utcnow()
            session.add(
                GitHubMonitorLog(
                    status="error",
                    message=f"PR #{review.pr_number} review interrupted",
                    details=message,
                )
            )
            recovered.append(review.id)
    return recovered
