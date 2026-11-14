"""Mailbox: sent and received messages, threaded.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-14 12:30:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mail_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("direction", sa.String(3), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("thread_id", UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", UUID(as_uuid=True), sa.ForeignKey("sending_accounts.id", ondelete="SET NULL")),
        sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="SET NULL")),
        sa.Column("recipient_id", UUID(as_uuid=True), sa.ForeignKey("campaign_recipients.id", ondelete="SET NULL")),
        sa.Column("contact_id", UUID(as_uuid=True), sa.ForeignKey("contacts.id", ondelete="SET NULL")),
        sa.Column("from_addr", sa.String(320), nullable=False),
        sa.Column("from_name", sa.String(200)),
        sa.Column("to_addr", sa.String(320), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_text", sa.Text()),
        sa.Column("body_html", sa.Text()),
        sa.Column("message_id_hdr", sa.String(500)),
        sa.Column("in_reply_to", sa.String(500)),
        sa.Column("error", sa.Text()),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sent_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mail_messages_workspace_id", "mail_messages", ["workspace_id"])
    op.create_index("ix_mail_messages_folder", "mail_messages", ["workspace_id", "direction", "created_at"])
    op.create_index("ix_mail_messages_thread", "mail_messages", ["thread_id", "created_at"])
    op.create_index("ix_mail_messages_contact", "mail_messages", ["contact_id"])
    op.create_index("ix_mail_messages_unread", "mail_messages", ["workspace_id"],
                    postgresql_where=sa.text("direction = 'in' AND NOT is_read"))
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON mail_messages TO bep_app")
    op.execute("ALTER TABLE mail_messages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE mail_messages FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY mail_messages_workspace_isolation ON mail_messages
          USING (current_setting('app.bypass_rls', true) = 'on'
                 OR workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid)
          WITH CHECK (current_setting('app.bypass_rls', true) = 'on'
                 OR workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid)
    """)


def downgrade() -> None:
    op.drop_table("mail_messages")
