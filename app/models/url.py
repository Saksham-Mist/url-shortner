"""SQLAlchemy ORM models for shortened URLs and their click events."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Url(Base):
    """A single shortened URL and its metadata."""

    __tablename__ = "urls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    short_code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False, index=True)

    long_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    clicks: Mapped[list["Click"]] = relationship(back_populates="url", cascade="all, delete-orphan")


class Click(Base):
    """A single click/redirect event recorded against a shortened URL."""

    __tablename__ = "clicks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    url_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("urls.id", ondelete="CASCADE"), nullable=False)
    clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    referrer: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    url: Mapped["Url"] = relationship(back_populates="clicks")

    __table_args__ = (
        # Composite, url_id-leading: serves both "total clicks" (COUNT WHERE
        # url_id = X) and "clicks per day" (WHERE url_id = X ORDER BY
        # clicked_at) from a single index, without slowing down the
        # per-redirect INSERT with more indexes than necessary.
        Index("idx_clicks_url_id_clicked_at", "url_id", "clicked_at"),
    )
