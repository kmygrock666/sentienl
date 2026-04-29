"""Initial schema."""

from alembic import op
import sqlalchemy as sa


revision = "20260307_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stocks",
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("industry", sa.String(length=128), nullable=True),
        sa.Column("list_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("market", "symbol"),
    )
    op.create_table(
        "daily_prices",
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(18, 4), nullable=False),
        sa.Column("high", sa.Numeric(18, 4), nullable=False),
        sa.Column("low", sa.Numeric(18, 4), nullable=False),
        sa.Column("close", sa.Numeric(18, 4), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.Column("turnover", sa.Numeric(20, 0), nullable=True),
        sa.Column("adjusted_close", sa.Numeric(18, 4), nullable=True),
        sa.Column("data_version", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("market", "symbol", "trading_date"),
    )
    op.create_index("ix_daily_prices_trading_date", "daily_prices", ["trading_date"])
    op.create_index("ix_daily_prices_market_symbol_trading_date", "daily_prices", ["market", "symbol", "trading_date"])
    op.create_table(
        "institutional_flows",
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("foreign_net", sa.Integer(), nullable=True),
        sa.Column("investment_trust_net", sa.Integer(), nullable=True),
        sa.Column("dealer_net", sa.Integer(), nullable=True),
        sa.Column("total_net", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("market", "symbol", "trading_date"),
    )
    op.create_table(
        "margin_balances",
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("margin_balance", sa.Integer(), nullable=True),
        sa.Column("short_balance", sa.Integer(), nullable=True),
        sa.Column("margin_change", sa.Integer(), nullable=True),
        sa.Column("short_change", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("market", "symbol", "trading_date"),
    )
    op.create_table(
        "corporate_actions",
        sa.Column("action_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("cash_dividend", sa.Numeric(18, 4), nullable=True),
        sa.Column("stock_dividend_ratio", sa.Numeric(18, 8), nullable=True),
        sa.Column("adjustment_factor", sa.Numeric(18, 8), nullable=True),
        sa.Column("source", sa.String(length=256), nullable=True),
    )
    op.create_index("ix_corporate_actions_market_symbol_ex_date", "corporate_actions", ["market", "symbol", "ex_date"])
    op.create_table(
        "technical_indicators",
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("indicator_name", sa.String(length=64), nullable=False),
        sa.Column("params_hash", sa.String(length=128), nullable=False),
        sa.Column("calc_version", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Numeric(18, 8), nullable=False),
        sa.Column("source_field", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("market", "symbol", "trading_date", "indicator_name", "params_hash", "calc_version"),
    )
    op.create_table(
        "scan_results",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("score", sa.Numeric(18, 8), nullable=True),
        sa.Column("signals_json", sa.JSON(), nullable=True),
        sa.Column("data_version", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "market", "symbol", "strategy_id"),
    )
    op.create_table(
        "job_runs",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("job_name", sa.String(length=64), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("rows_in", sa.Integer(), nullable=True),
        sa.Column("rows_out", sa.Integer(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
    )
    op.create_table(
        "trading_calendar",
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("is_trading_day", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=128), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("exchange", "calendar_date"),
    )
    op.create_table(
        "strategies",
        sa.Column("strategy_id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "data_quarantine",
        sa.Column("quarantine_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_table", sa.String(length=64), nullable=False),
        sa.Column("source_pk_or_batch", sa.String(length=128), nullable=False),
        sa.Column("raw_payload_json", sa.JSON(), nullable=False),
        sa.Column("violated_rule", sa.String(length=64), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolution", sa.String(length=32), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("data_quarantine")
    op.drop_table("strategies")
    op.drop_table("trading_calendar")
    op.drop_table("job_runs")
    op.drop_table("scan_results")
    op.drop_table("technical_indicators")
    op.drop_index("ix_corporate_actions_market_symbol_ex_date", table_name="corporate_actions")
    op.drop_table("corporate_actions")
    op.drop_table("margin_balances")
    op.drop_table("institutional_flows")
    op.drop_index("ix_daily_prices_market_symbol_trading_date", table_name="daily_prices")
    op.drop_index("ix_daily_prices_trading_date", table_name="daily_prices")
    op.drop_table("daily_prices")
    op.drop_table("stocks")
