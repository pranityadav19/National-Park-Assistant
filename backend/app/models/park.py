from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Park(Base):
    __tablename__ = "parks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    park_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), index=True)
    states: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    entrance_fee_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    operating_hours_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    weather_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sources: Mapped[list["ParkSourceChunk"]] = relationship(back_populates="park", cascade="all, delete-orphan")


class ParkSourceChunk(Base):
    __tablename__ = "park_source_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    park_id: Mapped[int | None] = mapped_column(ForeignKey("parks.id"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(50), index=True)
    source_url: Mapped[str] = mapped_column(String(600))
    section: Mapped[str | None] = mapped_column(String(120), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    park: Mapped[Park | None] = relationship(back_populates="sources")
