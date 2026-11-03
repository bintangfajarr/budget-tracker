"""
FastAPI dashboard backend.
Run: uvicorn dashboard.api:app --host 0.0.0.0 --port 8000
"""
from datetime import date
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
    db_cursor,
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
def summary(period: str = Query("month", enum=["today", "week", "month"]), user_id: int = None):
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


# ─── Serve React static build ────────────────────────────────────────────────

static_dir = os.path.join(os.path.dirname(__file__), "dashboard", "frontend", "dist")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
