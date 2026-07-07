"""Initial web database.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-07
"""

from __future__ import annotations

from alembic import op

from audio_salvage_hunter.web.database import Base
from audio_salvage_hunter.web import models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
