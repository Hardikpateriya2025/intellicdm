"""Create anomaly score history.

Revision ID: a61e24f90b12
Revises: 2076036f9d6d
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a61e24f90b12"
down_revision = "2076036f9d6d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "anomaly_score_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("encounter_id", sa.Uuid(), nullable=False),
        sa.Column(
            "collected_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("scoring_version", sa.String(100), nullable=False),
        sa.Column("anomaly_score", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("flagged_for_review", sa.Boolean(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["encounter_id"], ["encounters.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_anomaly_score_history_encounter_id",
        "anomaly_score_history",
        ["encounter_id"],
    )
    op.create_index(
        "ix_anomaly_score_history_created_at",
        "anomaly_score_history",
        ["created_at"],
    )


def downgrade():
    op.drop_index(
        "ix_anomaly_score_history_created_at",
        table_name="anomaly_score_history",
    )
    op.drop_index(
        "ix_anomaly_score_history_encounter_id",
        table_name="anomaly_score_history",
    )
    op.drop_table("anomaly_score_history")
