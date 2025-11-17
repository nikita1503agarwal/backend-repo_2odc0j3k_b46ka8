import os
import sqlite3
from datetime import datetime, timedelta
from typing import List, Optional, Generator, Any, Dict

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from schemas_sql import (
    SupplierCreate,
    SupplierRead,
    CategoryCreate,
    CategoryRead,
    ProductCreate,
    ProductRead,
    ProductUpdate,
    MovementCreate,
    MovementRead,
)

app = FastAPI(title="Inventory + Analytics API (SQLite)")

# ---------------------- CORS ----------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------- Database helpers ----------------------
SQLITE_URL = os.getenv("SQL_DATABASE_URL", "sqlite:///./inventory.db")

def _sqlite_path(url: str) -> str:
    # accept formats: sqlite:///path, sqlite:////absolute, or plain file path
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "", 1)
    return url

DB_PATH = _sqlite_path(SQLITE_URL)


def get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                address TEXT
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL DEFAULT 0,
                cost REAL NOT NULL DEFAULT 0,
                quantity INTEGER NOT NULL DEFAULT 0,
                reorder_level INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                category_id INTEGER,
                supplier_id INTEGER,
                FOREIGN KEY(category_id) REFERENCES categories(id),
                FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                change INTEGER NOT NULL,
                reason TEXT NOT NULL,
                reference TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(product_id) REFERENCES products(id)
            )
            """
        )
        conn.commit()


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/")
def read_root():
    return {"message": "Inventory + Analytics API (SQLite) is running"}

# ---------------------- Suppliers ----------------------
@app.post("/suppliers", response_model=SupplierRead)
def create_supplier(payload: SupplierCreate, conn: sqlite3.Connection = Depends(get_conn)):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO suppliers(name, email, phone, address) VALUES(?,?,?,?)",
        (payload.name, payload.email, payload.phone, payload.address),
    )
    conn.commit()
    supplier_id = cur.lastrowid
    row = conn.execute("SELECT * FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
    return row_to_dict(row)

@app.get("/suppliers", response_model=List[SupplierRead])
def list_suppliers(conn: sqlite3.Connection = Depends(get_conn)):
    rows = conn.execute("SELECT * FROM suppliers ORDER BY id DESC").fetchall()
    return [row_to_dict(r) for r in rows]

# ---------------------- Categories ----------------------
@app.post("/categories", response_model=CategoryRead)
def create_category(payload: CategoryCreate, conn: sqlite3.Connection = Depends(get_conn)):
    try:
        conn.execute("INSERT INTO categories(name) VALUES(?)", (payload.name,))
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Category name already exists")
    row = conn.execute("SELECT * FROM categories WHERE name=?", (payload.name,)).fetchone()
    return row_to_dict(row)

@app.get("/categories", response_model=List[CategoryRead])
def list_categories(conn: sqlite3.Connection = Depends(get_conn)):
    rows = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
    return [row_to_dict(r) for r in rows]

# ---------------------- Products ----------------------
@app.post("/products", response_model=ProductRead)
def create_product(payload: ProductCreate, conn: sqlite3.Connection = Depends(get_conn)):
    # Enforce unique SKU
    existing = conn.execute("SELECT id FROM products WHERE sku=?", (payload.sku,)).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="SKU already exists")
    conn.execute(
        """
        INSERT INTO products(sku, name, description, price, cost, quantity, reorder_level, is_active, category_id, supplier_id)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            payload.sku,
            payload.name,
            payload.description,
            payload.price,
            payload.cost,
            payload.quantity,
            payload.reorder_level,
            1 if payload.is_active else 0,
            payload.category_id,
            payload.supplier_id,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM products WHERE sku=?", (payload.sku,)).fetchone()
    d = row_to_dict(row)
    d["is_active"] = bool(d["is_active"])  # cast back to bool
    return d

@app.get("/products", response_model=List[ProductRead])
def list_products(
    q: Optional[str] = Query(default=None, description="Search by name or SKU"),
    category_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    only_active: bool = True,
    conn: sqlite3.Connection = Depends(get_conn),
):
    sql = "SELECT * FROM products WHERE 1=1"
    params: List[Any] = []
    if only_active:
        sql += " AND is_active=1"
    if q:
        sql += " AND (name LIKE ? OR sku LIKE ?)"
        like = f"%{q}%"
        params += [like, like]
    if category_id:
        sql += " AND category_id=?"
        params.append(category_id)
    if supplier_id:
        sql += " AND supplier_id=?"
        params.append(supplier_id)
    sql += " ORDER BY id DESC"
    rows = conn.execute(sql, params).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = row_to_dict(r)
        d["is_active"] = bool(d["is_active"])  # cast bool
        out.append(d)
    return out

@app.get("/products/{product_id}", response_model=ProductRead)
def get_product(product_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Product not found")
    d = row_to_dict(row)
    d["is_active"] = bool(d["is_active"])  # cast bool
    return d

@app.patch("/products/{product_id}", response_model=ProductRead)
def update_product(product_id: int, payload: ProductUpdate, conn: sqlite3.Connection = Depends(get_conn)):
    row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Product not found")
    data = payload.model_dump(exclude_unset=True)
    if not data:
        d = row_to_dict(row)
        d["is_active"] = bool(d["is_active"])  # cast bool
        return d
    fields = []
    params: List[Any] = []
    for k, v in data.items():
        if k == "is_active":
            v = 1 if v else 0
        fields.append(f"{k}=?")
        params.append(v)
    params.append(product_id)
    sql = f"UPDATE products SET {', '.join(fields)} WHERE id=?"
    conn.execute(sql, params)
    conn.commit()
    row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    d = row_to_dict(row)
    d["is_active"] = bool(d["is_active"])  # cast bool
    return d

@app.delete("/products/{product_id}")
def delete_product(product_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    row = conn.execute("SELECT id FROM products WHERE id=?", (product_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Product not found")
    conn.execute("DELETE FROM products WHERE id=?", (product_id,))
    conn.commit()
    return {"status": "deleted"}

# ---------------------- Inventory Movements ----------------------
@app.post("/movements", response_model=MovementRead)
def create_movement(payload: MovementCreate, conn: sqlite3.Connection = Depends(get_conn)):
    prod = conn.execute("SELECT quantity FROM products WHERE id=?", (payload.product_id,)).fetchone()
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    new_qty = int(prod["quantity"] or 0) + payload.change
    if new_qty < 0:
        raise HTTPException(status_code=400, detail="Insufficient stock")
    # update stock
    conn.execute("UPDATE products SET quantity=? WHERE id=?", (new_qty, payload.product_id))
    now = datetime.utcnow().isoformat()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO inventory_movements(product_id, change, reason, reference, created_at) VALUES(?,?,?,?,?)",
        (payload.product_id, payload.change, payload.reason, payload.reference, now),
    )
    conn.commit()
    move_id = cur.lastrowid
    row = conn.execute("SELECT * FROM inventory_movements WHERE id=?", (move_id,)).fetchone()
    d = row_to_dict(row)
    d["created_at"] = datetime.fromisoformat(d["created_at"])  # cast to datetime for schema
    return d

@app.get("/movements", response_model=List[MovementRead])
def list_movements(
    product_id: Optional[int] = None,
    days: Optional[int] = None,
    conn: sqlite3.Connection = Depends(get_conn),
):
    sql = "SELECT * FROM inventory_movements WHERE 1=1"
    params: List[Any] = []
    if product_id:
        sql += " AND product_id=?"
        params.append(product_id)
    if days and days > 0:
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        sql += " AND created_at >= ?"
        params.append(since)
    sql += " ORDER BY created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = row_to_dict(r)
        d["created_at"] = datetime.fromisoformat(d["created_at"])  # cast to datetime
        out.append(d)
    return out

# ---------------------- Analytics ----------------------
@app.get("/analytics/stock-valuation")
def stock_valuation(conn: sqlite3.Connection = Depends(get_conn)):
    row = conn.execute("SELECT SUM(quantity*cost) AS cost_value, SUM(quantity*price) AS retail_value, SUM(quantity) AS total_qty FROM products").fetchone()
    cost_value = float(row["cost_value"] or 0)
    retail_value = float(row["retail_value"] or 0)
    total_qty = int(row["total_qty"] or 0)
    return {
        "total_quantity": total_qty,
        "inventory_cost_value": cost_value,
        "inventory_retail_value": retail_value,
    }

@app.get("/analytics/low-stock", response_model=List[ProductRead])
def low_stock(
    threshold: Optional[int] = Query(default=None, description="Override threshold. If not set, uses reorder_level"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    if threshold is not None:
        rows = conn.execute("SELECT * FROM products WHERE is_active=1 AND quantity <= ? ORDER BY quantity ASC", (threshold,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM products WHERE is_active=1 AND quantity <= reorder_level ORDER BY quantity ASC").fetchall()
    out = []
    for r in rows:
        d = row_to_dict(r)
        d["is_active"] = bool(d["is_active"])  # cast bool
        out.append(d)
    return out

@app.get("/analytics/top-movers")
def top_movers(days: int = 30, limit: int = 10, conn: sqlite3.Connection = Depends(get_conn)):
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """
        SELECT product_id, SUM(ABS(change)) AS moved
        FROM inventory_movements
        WHERE created_at >= ?
        GROUP BY product_id
        ORDER BY moved DESC
        LIMIT ?
        """,
        (since, limit),
    ).fetchall()
    result = []
    for r in rows:
        product = conn.execute("SELECT sku, name FROM products WHERE id=?", (r["product_id"],)).fetchone()
        if product:
            result.append({
                "product_id": r["product_id"],
                "sku": product["sku"],
                "name": product["name"],
                "moved": int(r["moved"] or 0),
            })
    return result

# ------------- Simple health checks -------------
@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}

@app.get("/test")
def test_database():
    return {
        "backend": "✅ Running",
        "sql_database_url": SQLITE_URL,
        "engine": "sqlite3",
        "tables": [
            "suppliers",
            "categories",
            "products",
            "inventory_movements",
        ],
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
