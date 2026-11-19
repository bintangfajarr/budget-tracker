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

CREATE TABLE IF NOT EXISTS notes (
    id          SERIAL PRIMARY KEY,
    note_date   DATE         NOT NULL,
    title       VARCHAR(200),
    body        TEXT         NOT NULL,
    mood        VARCHAR(20),              -- optional: good | ok | bad
    tags        TEXT[]       NOT NULL DEFAULT '{}',
    source      VARCHAR(20)  NOT NULL DEFAULT 'web',   -- web | telegram
    telegram_user_id BIGINT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notes_date ON notes(note_date DESC);
CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_notes_tags ON notes USING GIN(tags);

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


def get_recent_transactions(telegram_user_id: int = None, limit: int = 10) -> list[dict]:
    """
    Most recent transactions.

    Email-imported rows have telegram_user_id NULL, since nobody typed them.
    Filtering strictly on that column hid every imported transaction from the
    dashboard. Passing None now means "everything", and a user id still
    includes the imported rows alongside that user's own entries.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT t.*, c.name AS category_name, c.emoji AS category_emoji
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE %(uid)s IS NULL
               OR t.telegram_user_id = %(uid)s
               OR t.telegram_user_id IS NULL
            ORDER BY t.transaction_at DESC
            LIMIT %(lim)s
            """,
            {"uid": telegram_user_id, "lim": limit},
        )
        return cur.fetchall()


def delete_transaction(tx_id: int) -> dict | None:
    """Remove a transaction. Returns the deleted row, or None if absent."""
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM transactions WHERE id = %s RETURNING *",
            (tx_id,),
        )
        return cur.fetchone()


def get_transaction(tx_id: int) -> dict | None:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT t.*, c.name AS category_name, c.emoji AS category_emoji
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.id = %s
            """,
            (tx_id,),
        )
        return cur.fetchone()


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


# ─── Notes ───────────────────────────────────────────────────────────────────

def insert_note(data: dict) -> dict:
    """Create a note. `data` keys: note_date, title, body, mood, tags,
    source, telegram_user_id."""
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO notes
                (note_date, title, body, mood, tags, source, telegram_user_id)
            VALUES
                (%(note_date)s, %(title)s, %(body)s, %(mood)s,
                 %(tags)s, %(source)s, %(telegram_user_id)s)
            RETURNING *
            """,
            data,
        )
        return cur.fetchone()


def update_note(note_id: int, data: dict) -> dict | None:
    """Patch a note. Only the keys present in `data` are written."""
    allowed = ("note_date", "title", "body", "mood", "tags")
    sets, params = [], {"id": note_id}
    for k in allowed:
        if k in data:
            sets.append(f"{k} = %({k})s")
            params[k] = data[k]
    if not sets:
        return get_note(note_id)

    sets.append("updated_at = NOW()")
    with db_cursor() as cur:
        cur.execute(
            f"UPDATE notes SET {', '.join(sets)} WHERE id = %(id)s RETURNING *",
            params,
        )
        return cur.fetchone()


def delete_note(note_id: int) -> bool:
    with db_cursor() as cur:
        cur.execute("DELETE FROM notes WHERE id = %s RETURNING id", (note_id,))
        return cur.fetchone() is not None


def get_note(note_id: int) -> dict | None:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM notes WHERE id = %s", (note_id,))
        return cur.fetchone()


def get_notes_by_date(note_date, telegram_user_id: int = None) -> list[dict]:
    """All notes for one specific day."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM notes
            WHERE note_date = %(d)s
              AND (%(uid)s IS NULL OR telegram_user_id = %(uid)s)
            ORDER BY created_at ASC
            """,
            {"d": note_date, "uid": telegram_user_id},
        )
        return cur.fetchall()


def get_notes_range(start, end, telegram_user_id: int = None) -> list[dict]:
    """All notes between two dates, inclusive."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM notes
            WHERE note_date BETWEEN %(s)s AND %(e)s
              AND (%(uid)s IS NULL OR telegram_user_id = %(uid)s)
            ORDER BY note_date DESC, created_at ASC
            """,
            {"s": start, "e": end, "uid": telegram_user_id},
        )
        return cur.fetchall()


def get_month_calendar(year: int, month: int, telegram_user_id: int = None) -> list[dict]:
    """
    Per-day rollup for one month: note count, moods, and the money moved
    that day. Drives the calendar grid.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            WITH days AS (
                SELECT generate_series(
                    make_date(%(y)s, %(m)s, 1),
                    (make_date(%(y)s, %(m)s, 1) + INTERVAL '1 month - 1 day')::date,
                    '1 day'
                )::date AS d
            ),
            n AS (
                SELECT note_date AS d,
                       COUNT(*) AS note_count,
                       ARRAY_REMOVE(ARRAY_AGG(DISTINCT mood), NULL) AS moods,
                       (ARRAY_AGG(COALESCE(NULLIF(title,''), LEFT(body, 60))
                                  ORDER BY created_at))[1] AS first_title
                FROM notes
                WHERE note_date >= make_date(%(y)s, %(m)s, 1)
                  AND note_date <  make_date(%(y)s, %(m)s, 1) + INTERVAL '1 month'
                  AND (%(uid)s IS NULL OR telegram_user_id = %(uid)s)
                GROUP BY note_date
            ),
            t AS (
                SELECT DATE(transaction_at) AS d,
                       COUNT(*) AS tx_count,
                       COALESCE(SUM(CASE WHEN type='debit'  THEN amount END), 0) AS spent,
                       COALESCE(SUM(CASE WHEN type='credit' THEN amount END), 0) AS received
                FROM transactions
                WHERE transaction_at >= make_date(%(y)s, %(m)s, 1)
                  AND transaction_at <  make_date(%(y)s, %(m)s, 1) + INTERVAL '1 month'
                GROUP BY DATE(transaction_at)
            )
            SELECT days.d AS date,
                   COALESCE(n.note_count, 0) AS note_count,
                   COALESCE(n.moods, '{}') AS moods,
                   n.first_title,
                   COALESCE(t.tx_count, 0) AS tx_count,
                   COALESCE(t.spent, 0) AS spent,
                   COALESCE(t.received, 0) AS received
            FROM days
            LEFT JOIN n ON n.d = days.d
            LEFT JOIN t ON t.d = days.d
            ORDER BY days.d
            """,
            {"y": year, "m": month, "uid": telegram_user_id},
        )
        return cur.fetchall()


def get_year_calendar(year: int, telegram_user_id: int = None) -> list[dict]:
    """Per-month rollup for a whole year."""
    with db_cursor() as cur:
        cur.execute(
            """
            WITH months AS (
                SELECT generate_series(
                    make_date(%(y)s, 1, 1),
                    make_date(%(y)s, 12, 1),
                    '1 month'
                )::date AS m
            ),
            n AS (
                SELECT DATE_TRUNC('month', note_date)::date AS m,
                       COUNT(*) AS note_count,
                       COUNT(DISTINCT note_date) AS days_with_notes
                FROM notes
                WHERE EXTRACT(YEAR FROM note_date) = %(y)s
                  AND (%(uid)s IS NULL OR telegram_user_id = %(uid)s)
                GROUP BY 1
            ),
            t AS (
                SELECT DATE_TRUNC('month', transaction_at)::date AS m,
                       COUNT(*) AS tx_count,
                       COALESCE(SUM(CASE WHEN type='debit'  THEN amount END), 0) AS spent,
                       COALESCE(SUM(CASE WHEN type='credit' THEN amount END), 0) AS received
                FROM transactions
                WHERE EXTRACT(YEAR FROM transaction_at) = %(y)s
                GROUP BY 1
            )
            SELECT months.m AS month,
                   EXTRACT(MONTH FROM months.m)::int AS month_num,
                   COALESCE(n.note_count, 0) AS note_count,
                   COALESCE(n.days_with_notes, 0) AS days_with_notes,
                   COALESCE(t.tx_count, 0) AS tx_count,
                   COALESCE(t.spent, 0) AS spent,
                   COALESCE(t.received, 0) AS received
            FROM months
            LEFT JOIN n ON n.m = months.m
            LEFT JOIN t ON t.m = months.m
            ORDER BY months.m
            """,
            {"y": year, "uid": telegram_user_id},
        )
        return cur.fetchall()


def search_notes(q: str, limit: int = 50, telegram_user_id: int = None) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM notes
            WHERE (title ILIKE %(q)s OR body ILIKE %(q)s OR %(raw)s = ANY(tags))
              AND (%(uid)s IS NULL OR telegram_user_id = %(uid)s)
            ORDER BY note_date DESC, created_at DESC
            LIMIT %(lim)s
            """,
            {"q": f"%{q}%", "raw": q, "lim": limit, "uid": telegram_user_id},
        )
        return cur.fetchall()


def get_all_tags(telegram_user_id: int = None) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT tag, COUNT(*) AS count
            FROM notes, UNNEST(tags) AS tag
            WHERE (%(uid)s IS NULL OR telegram_user_id = %(uid)s)
            GROUP BY tag
            ORDER BY count DESC, tag ASC
            """,
            {"uid": telegram_user_id},
        )
        return cur.fetchall()
