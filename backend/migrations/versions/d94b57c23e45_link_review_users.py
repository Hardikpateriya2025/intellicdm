"""Link new reviews to authenticated users."""
from alembic import op
import sqlalchemy as sa

revision = "d94b57c23e45"
down_revision = "c83a46b12d34"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "anomaly_reviews",
        sa.Column("reviewer_user_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_anomaly_reviews_reviewer_user_id",
        "anomaly_reviews", "users",
        ["reviewer_user_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_anomaly_reviews_reviewer_user_id",
        "anomaly_reviews",
        ["reviewer_user_id"],
    )


def downgrade():
    op.drop_index(
        "ix_anomaly_reviews_reviewer_user_id",
        table_name="anomaly_reviews",
    )
    op.drop_constraint(
        "fk_anomaly_reviews_reviewer_user_id",
        "anomaly_reviews",
        type_="foreignkey",
    )
    op.drop_column("anomaly_reviews", "reviewer_user_id")
