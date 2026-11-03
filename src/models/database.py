"""
Database schema & connection management.
"""
import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

logger = logging.getLogger(__name__)


def get_connection():
    return psycopg2.connect(os.environ["DATABASE_URL"], cursor_factory=RealDictCursor)


@contextmanager
def db_cursor():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS categories (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,
    emoji       VARCHAR(10)  NOT NULL DEFAULT '💰',
    is_income   BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS transactions (
    id              SERIAL PRIMARY KEY,
    amount          BIGINT          NOT NULL,  -- in IDR cents (rupiah)
    type            VARCHAR(10)     NOT NULL CHECK (type IN ('debit','credit')),
    description     TEXT            NOT NULL,
    category_id     INTEGER         REFERENCES categories(id),
    source          VARCHAR(20)     NOT NULL DEFAULT 'manual', -- 'manual' | 'email'
    email_uid       VARCHAR(255),   -- IMAP UID to prevent duplicates
    merchant        VARCHAR(255),
    balance_after   BIGINT,
    transaction_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    telegram_user_id BIGINT
);

CREATE INDEX IF NOT EXISTS idx_transactions_at    ON transactions(transaction_at DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_cat   ON transactions(category_id);
CREATE INDEX IF NOT EXISTS idx_transactions_uid   ON transactions(email_uid);
CREATE INDEX IF NOT EXISTS idx_transactions_user  ON transactions(telegram_user_id);

CREATE TABLE IF NOT EXISTS budgets (
    id          SERIAL PRIMARY KEY,
    category_id INTEGER     NOT NULL REFERENCES categories(id),
    amount      BIGINT      NOT NULL, -- monthly limit in IDR
    month       DATE        NOT NULL, -- first day of the month
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (category_id, month)
);

CREATE TABLE IF NOT EXISTS settings (
    key         VARCHAR(100) PRIMARY KEY,
    value       TEXT
);
"""

DEFAULT_CATEGORIES = [
    ("Makanan & Minuman", "🍜", False),
    ("Transport",         "🚗", False),
    ("Belanja",           "🛍️", False),
    ("Tagihan & Utilitas","💡", False),
    ("Hiburan",           "🎮", False),
    ("Kesehatan",         "🏥", False),
    ("Pendidikan",        "📚", False),
    ("Tabungan & Investasi","💹", False),
    ("Gaji & Pemasukan",  "💵", True),
    ("Transfer Masuk",    "📥", True),
    ("Lain-lain",         "📌", False),
]


def init_db():
    """Initialize database schema and seed default categories."""
    with db_cursor() as cur:
        cur.execute(SCHEMA_SQL)
        for name, emoji, is_income in DEFAULT_CATEGORIES:
            cur.execute(
                """
                INSERT INTO categories (name, emoji, is_income)
                VALUES (%s, %s, %s)
                ON CONFLICT (name) DO NOTHING
                """,
                (name, emoji, is_income),
            )
    logger.info("Database initialized.")


def get_all_categories() -> list[dict]:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM categories ORDER BY is_income, name")
        return cur.fetchall()


def get_category_by_id(cat_id: int) -> dict | None:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM categories WHERE id = %s", (cat_id,))
        return cur.fetchone()


def insert_transaction(data: dict) -> dict:
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO transactions
                (amount, type, description, category_id, source, email_uid,
                 merchant, balance_after, transaction_at, telegram_user_id)
            VALUES
                (%(amount)s, %(type)s, %(description)s, %(category_id)s,
                 %(source)s, %(email_uid)s, %(merchant)s, %(balance_after)s,
                 %(transaction_at)s, %(telegram_user_id)s)
            RETURNING *
            """,
            data,
        )
        return cur.fetchone()


def email_uid_exists(uid: str) -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM transactions WHERE email_uid = %s", (uid,))
        return cur.fetchone() is not None


def get_summary(telegram_user_id: int, period: str = "month") -> list[dict]:
    """Return spending by category for current period."""
    period_filter = {
        "today":  "DATE(transaction_at) = CURRENT_DATE",
        "week":   "transaction_at >= DATE_TRUNC('week', NOW())",
        "month":  "transaction_at >= DATE_TRUNC('month', NOW())",
    }.get(period, "transaction_at >= DATE_TRUNC('month', NOW())")

    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                COALESCE(c.name, 'Tidak Terkategori') AS category,
                COALESCE(c.emoji, '📌') AS emoji,
                c.is_income,
                SUM(t.amount) AS total,
                COUNT(*) AS count
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE {period_filter}
              AND (%(uid)s IS NULL OR t.telegram_user_id = %(uid)s)
            GROUP BY c.name, c.emoji, c.is_income
            ORDER BY c.is_income, total DESC
            """,
            {"uid": telegram_user_id},
        )
        return cur.fetchall()


def get_recent_transactions(telegram_user_id: int, limit: int = 10) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT t.*, c.name AS category_name, c.emoji AS category_emoji
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.telegram_user_id = %s
            ORDER BY t.transaction_at DESC
            LIMIT %s
            """,
            (telegram_user_id, limit),
        )
        return cur.fetchall()


def update_transaction_category(tx_id: int, category_id: int):
    with db_cursor() as cur:
        cur.execute(
            "UPDATE transactions SET category_id = %s WHERE id = %s",
            (category_id, tx_id),
        )


def set_budget(category_id: int, amount: int, month_date):
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO budgets (category_id, amount, month)
            VALUES (%s, %s, %s)
            ON CONFLICT (category_id, month)
            DO UPDATE SET amount = EXCLUDED.amount
            """,
            (category_id, amount, month_date),
        )


def get_budgets_vs_actual(telegram_user_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
                c.name, c.emoji,
                b.amount AS budget,
                COALESCE(SUM(t.amount), 0) AS spent
            FROM budgets b
            JOIN categories c ON c.id = b.category_id
            LEFT JOIN transactions t
                ON t.category_id = b.category_id
                AND t.transaction_at >= DATE_TRUNC('month', NOW())
                AND t.type = 'debit'
                AND (%(uid)s IS NULL OR t.telegram_user_id = %(uid)s)
            WHERE b.month = DATE_TRUNC('month', NOW())
            GROUP BY c.name, c.emoji, b.amount
            ORDER BY (COALESCE(SUM(t.amount), 0)::float / b.amount) DESC
            """,
            {"uid": telegram_user_id},
        )
        return cur.fetchall()
