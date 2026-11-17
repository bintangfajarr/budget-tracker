"""
FastAPI dashboard backend.
Run: uvicorn dashboard.api:app --host 0.0.0.0 --port 8000
"""
from datetime import date
from typing import Literal
from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os

from dotenv import load_dotenv
load_dotenv()

from src.models.database import (
    init_db,
    get_summary,
    get_recent_transactions,
    get_all_categories,
    get_budgets_vs_actual,
    set_budget,
    insert_transaction,
    update_transaction_category,
    email_uid_exists,
    db_cursor,
    insert_note,
    update_note,
    delete_note,
    get_note,
    get_notes_by_date,
    get_notes_range,
    get_month_calendar,
    get_year_calendar,
    search_notes,
    get_all_tags,
)

app = FastAPI(title="Budget Tracker API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


# ─── Health ──────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok"}


# ─── Summary ─────────────────────────────────────────────────────────────────

@app.get("/api/summary")
def summary(period: Literal["today", "week", "month"] = Query("month"), user_id: int = None):
    rows = get_summary(user_id, period)
    return {"period": period, "data": [dict(r) for r in rows]}


# ─── Transactions ─────────────────────────────────────────────────────────────

@app.get("/api/transactions")
def transactions(limit: int = 50, user_id: int = None):
    rows = get_recent_transactions(user_id, limit)
    return {"data": [dict(r) for r in rows]}


@app.get("/api/transactions/timeseries")
def timeseries(user_id: int = None, days: int = 30):
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
                DATE(transaction_at) AS day,
                type,
                SUM(amount) AS total
            FROM transactions
            WHERE transaction_at >= NOW() - INTERVAL '%s days'
              AND (%s IS NULL OR telegram_user_id = %s)
            GROUP BY day, type
            ORDER BY day
            """,
            (days, user_id, user_id),
        )
        rows = cur.fetchall()
    return {"data": [dict(r) for r in rows]}


class TransactionIn(BaseModel):
    amount: int
    type: str  # debit | credit
    description: str
    category_id: int | None = None
    merchant: str | None = None
    telegram_user_id: int | None = None


@app.post("/api/transactions")
def create_transaction(body: TransactionIn):
    from datetime import datetime
    row = insert_transaction({
        "amount": body.amount,
        "type": body.type,
        "description": body.description,
        "category_id": body.category_id,
        "source": "manual",
        "email_uid": None,
        "merchant": body.merchant,
        "balance_after": None,
        "transaction_at": datetime.now(),
        "telegram_user_id": body.telegram_user_id,
    })
    return dict(row)


class CategoryUpdate(BaseModel):
    category_id: int


@app.patch("/api/transactions/{tx_id}/category")
def patch_category(tx_id: int, body: CategoryUpdate):
    update_transaction_category(tx_id, body.category_id)
    return {"ok": True}


# ─── Categories ──────────────────────────────────────────────────────────────

@app.get("/api/categories")
def categories():
    return {"data": [dict(c) for c in get_all_categories()]}


# ─── Budget ──────────────────────────────────────────────────────────────────

@app.get("/api/budget")
def budget(user_id: int = None):
    rows = get_budgets_vs_actual(user_id)
    return {"data": [dict(r) for r in rows]}


class BudgetIn(BaseModel):
    category_id: int
    amount: int


@app.post("/api/budget")
def create_budget(body: BudgetIn):
    month = date.today().replace(day=1)
    set_budget(body.category_id, body.amount, month)
    return {"ok": True}



# ─── Email webhook (Google Apps Script) ──────────────────────────────────────
# Apps Script runs inside Google and POSTs transactions here, so no Gmail
# credentials are stored on this server.

import hmac
import logging as _logging

_wh_log = _logging.getLogger("email_webhook")

EMAIL_WEBHOOK_SECRET = os.environ.get("EMAIL_WEBHOOK_SECRET", "")


class EmailWebhookItem(BaseModel):
    """One email handed over by Apps Script."""
    message_id: str
    subject: str = ""
    body: str = ""
    sender: str = ""
    received_at: str | None = None


class EmailWebhookPayload(BaseModel):
    secret: str
    items: list[EmailWebhookItem]


@app.post("/api/email-webhook")
def email_webhook(payload: EmailWebhookPayload):
    """
    Accept Jago notification emails from Google Apps Script.

    Returns a per-item report so the Apps Script side can label/skip
    messages it has already delivered.
    """
    if not EMAIL_WEBHOOK_SECRET:
        raise HTTPException(503, "EMAIL_WEBHOOK_SECRET not configured on server")

    # constant-time compare so the secret can't be probed by timing
    if not hmac.compare_digest(payload.secret, EMAIL_WEBHOOK_SECRET):
        raise HTTPException(401, "invalid secret")

    from datetime import datetime

    from src.parsers.jago import parse_jago_email
    from src.services.categorizer import auto_categorize

    categories = {c["name"]: c["id"] for c in get_all_categories()}

    created, skipped, unparsed = [], [], []

    for item in payload.items:
        uid = f"gas:{item.message_id}"

        if email_uid_exists(uid):
            skipped.append(item.message_id)
            continue

        parsed = parse_jago_email(item.subject, item.body)
        if parsed is None:
            _wh_log.warning("unparsed: %s | %s", item.sender, item.subject[:80])
            unparsed.append({
                "message_id": item.message_id,
                "subject": item.subject[:120],
                "sender": item.sender[:80],
            })
            continue

        cat_name = auto_categorize(
            parsed.get("description", ""),
            parsed.get("merchant"),
            tx_type=parsed.get("type", "debit"),
        )

        tx_at = datetime.now()
        if item.received_at:
            for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    tx_at = datetime.strptime(item.received_at, fmt)
                    break
                except ValueError:
                    continue

        row = insert_transaction({
            "amount": parsed["amount"],
            "type": parsed["type"],
            "description": parsed["description"],
            "category_id": categories.get(cat_name) if cat_name else None,
            "source": "email",
            "email_uid": uid,
            "merchant": parsed.get("merchant"),
            "balance_after": parsed.get("balance_after"),
            "transaction_at": tx_at,
            "telegram_user_id": None,
        })

        _wh_log.info("saved id=%s amount=%s cat=%s", row["id"], parsed["amount"], cat_name)
        created.append({
            "id": row["id"],
            "message_id": item.message_id,
            "amount": parsed["amount"],
            "type": parsed["type"],
            "description": parsed["description"],
            "category": cat_name,
        })

    return {
        "ok": True,
        "created": len(created),
        "skipped": len(skipped),
        "unparsed": len(unparsed),
        "transactions": created,
        "unparsed_detail": unparsed,
    }


@app.post("/api/email-webhook/probe")
def email_webhook_probe(payload: EmailWebhookPayload):
    """
    Dry run: parse and report, write nothing to the database.
    Use this to confirm the Jago email format is understood.
    """
    if not EMAIL_WEBHOOK_SECRET:
        raise HTTPException(503, "EMAIL_WEBHOOK_SECRET not configured on server")
    if not hmac.compare_digest(payload.secret, EMAIL_WEBHOOK_SECRET):
        raise HTTPException(401, "invalid secret")

    from src.parsers.jago import parse_jago_email
    from src.services.categorizer import auto_categorize

    out = []
    for item in payload.items:
        parsed = parse_jago_email(item.subject, item.body)
        entry = {
            "message_id": item.message_id,
            "sender": item.sender[:80],
            "subject": item.subject[:120],
            "body_preview": item.body[:200],
            "parsed": parsed,
            "already_stored": email_uid_exists(f"gas:{item.message_id}"),
        }
        if parsed:
            entry["category"] = auto_categorize(
                parsed.get("description", ""),
                parsed.get("merchant"),
                tx_type=parsed.get("type", "debit"),
            )
        out.append(entry)

    return {"ok": True, "count": len(out), "results": out}


# ─── Notes & Calendar ────────────────────────────────────────────────────────

from datetime import date as _date, datetime as _datetime, timedelta as _timedelta


def _row(r):
    """psycopg2 row -> plain dict, with dates rendered as ISO strings."""
    if r is None:
        return None
    d = dict(r)
    for k, v in list(d.items()):
        if isinstance(v, _datetime):
            d[k] = v.isoformat()
        elif isinstance(v, _date):
            d[k] = v.isoformat()
    return d


class NoteIn(BaseModel):
    note_date: str | None = None          # YYYY-MM-DD, defaults to today
    title: str | None = None
    body: str
    mood: str | None = None               # good | ok | bad
    tags: list[str] = []
    source: str = "web"
    telegram_user_id: int | None = None


class NotePatch(BaseModel):
    note_date: str | None = None
    title: str | None = None
    body: str | None = None
    mood: str | None = None
    tags: list[str] | None = None


def _parse_day(s):
    if not s:
        return _date.today()
    try:
        return _date.fromisoformat(s)
    except ValueError:
        raise HTTPException(400, f"invalid date '{s}', expected YYYY-MM-DD")


@app.post("/api/notes")
def create_note(body: NoteIn):
    """Create a note. Used by both the web UI and the Telegram bot."""
    if not body.body or not body.body.strip():
        raise HTTPException(400, "body cannot be empty")
    if body.mood and body.mood not in ("good", "ok", "bad"):
        raise HTTPException(400, "mood must be one of: good, ok, bad")

    row = insert_note({
        "note_date": _parse_day(body.note_date),
        "title": (body.title or None),
        "body": body.body.strip(),
        "mood": body.mood,
        "tags": body.tags or [],
        "source": body.source,
        "telegram_user_id": body.telegram_user_id,
    })
    return _row(row)


@app.get("/api/notes")
def list_notes(day: str = None, start: str = None, end: str = None,
               q: str = None, limit: int = 100, user_id: int = None):
    """
    ?day=2026-11-17        one day
    ?start=..&end=..       a range
    ?q=keyword             search title/body/tags
    (none)                 last 30 days
    """
    if q:
        rows = search_notes(q, limit=limit, telegram_user_id=user_id)
    elif day:
        rows = get_notes_by_date(_parse_day(day), telegram_user_id=user_id)
    elif start or end:
        s = _parse_day(start) if start else _date.today() - _timedelta(days=30)
        e = _parse_day(end) if end else _date.today()
        rows = get_notes_range(s, e, telegram_user_id=user_id)
    else:
        rows = get_notes_range(_date.today() - _timedelta(days=30),
                               _date.today(), telegram_user_id=user_id)
    return {"data": [_row(r) for r in rows]}


@app.get("/api/notes-tags")
def notes_tags(user_id: int = None):
    return {"data": [dict(t) for t in get_all_tags(telegram_user_id=user_id)]}


@app.get("/api/notes/{note_id}")
def read_note(note_id: int):
    row = get_note(note_id)
    if row is None:
        raise HTTPException(404, "note not found")
    return _row(row)


@app.patch("/api/notes/{note_id}")
def patch_note(note_id: int, body: NotePatch):
    if get_note(note_id) is None:
        raise HTTPException(404, "note not found")

    data = {}
    if body.note_date is not None:
        data["note_date"] = _parse_day(body.note_date)
    if body.title is not None:
        data["title"] = body.title or None
    if body.body is not None:
        if not body.body.strip():
            raise HTTPException(400, "body cannot be empty")
        data["body"] = body.body.strip()
    if body.mood is not None:
        if body.mood and body.mood not in ("good", "ok", "bad"):
            raise HTTPException(400, "mood must be one of: good, ok, bad")
        data["mood"] = body.mood or None
    if body.tags is not None:
        data["tags"] = body.tags

    return _row(update_note(note_id, data))


@app.delete("/api/notes/{note_id}")
def remove_note(note_id: int):
    if not delete_note(note_id):
        raise HTTPException(404, "note not found")
    return {"ok": True}


@app.get("/api/calendar/{year}/{month}")
def calendar_month(year: int, month: int, user_id: int = None):
    """Per-day rollup for the month grid: notes plus money moved."""
    if not 1 <= month <= 12:
        raise HTTPException(400, "month must be 1-12")
    if not 1970 <= year <= 2200:
        raise HTTPException(400, "year out of range")

    rows = [_row(r) for r in get_month_calendar(year, month, telegram_user_id=user_id)]
    return {
        "year": year,
        "month": month,
        "days": rows,
        "totals": {
            "notes": sum(r["note_count"] for r in rows),
            "transactions": sum(r["tx_count"] for r in rows),
            "spent": sum(int(r["spent"]) for r in rows),
            "received": sum(int(r["received"]) for r in rows),
            "days_with_notes": sum(1 for r in rows if r["note_count"] > 0),
        },
    }


@app.get("/api/calendar/{year}")
def calendar_year(year: int, user_id: int = None):
    """Per-month rollup for the year view."""
    if not 1970 <= year <= 2200:
        raise HTTPException(400, "year out of range")

    rows = [_row(r) for r in get_year_calendar(year, telegram_user_id=user_id)]
    return {
        "year": year,
        "months": rows,
        "totals": {
            "notes": sum(r["note_count"] for r in rows),
            "transactions": sum(r["tx_count"] for r in rows),
            "spent": sum(int(r["spent"]) for r in rows),
            "received": sum(int(r["received"]) for r in rows),
            "days_with_notes": sum(r["days_with_notes"] for r in rows),
        },
    }


# ─── Serve React static build ────────────────────────────────────────────────

static_dir = os.path.join(os.path.dirname(__file__), "dashboard", "frontend", "dist")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")