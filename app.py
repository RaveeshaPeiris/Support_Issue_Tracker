"""Support Issue Tracker - Flask + SQLite backend."""
import sqlite3
from datetime import datetime, timedelta, timezone

from flask import Flask, g, jsonify, render_template, request

app = Flask(__name__)
DB_PATH = "issues.db"
PRIORITIES = ("Low", "Medium", "High")
STATUSES = ("Open", "In Progress", "Resolved")


# ---------- database ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def now_utc():
    return datetime.now(timezone.utc)


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS issues (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            client_name TEXT NOT NULL,
            title       TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            engineer    TEXT NOT NULL DEFAULT '',
            priority    TEXT NOT NULL CHECK (priority IN ('Low','Medium','High')),
            status      TEXT NOT NULL CHECK (status IN ('Open','In Progress','Resolved')),
            reported_at TEXT NOT NULL
        )""")
    columns = {row[1] for row in con.execute("PRAGMA table_info(issues)")}
    if "engineer" not in columns:
        con.execute("ALTER TABLE issues ADD COLUMN engineer TEXT NOT NULL DEFAULT ''")
        con.execute(
            "UPDATE issues SET status='In Progress' "
            "WHERE status='Resolved' AND TRIM(engineer)=''"
        )
    if con.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == 0:
        samples = [  # (client, title, description, engineer, priority, status, hours ago)
            ("Acme Logistics", "Cannot export invoices to PDF", "Export button spins forever.", "John Doe", "High", "Open", 52),
            ("Brightwave Media", "Login page slow in the morning", "Takes ~15s to load.", "Jane Smith", "Medium", "In Progress", 30),
            ("Cedar Health", "Wrong date format in reports", "Shows MM/DD instead of DD/MM.", "Bob Johnson", "Low", "Open", 6),
            ("Delta Retail", "Payment webhook failing", "Receiving 500 errors since update.", "Alice Williams", "High", "In Progress", 5),
            ("Evergreen Bank", "User role not saving", "Admin role resets after save.", "Charlie Brown", "High", "Resolved", 70),
        ]
        for c, t, d, e, p, s, h in samples:
            ts = (now_utc() - timedelta(hours=h)).isoformat(timespec="seconds")
            con.execute(
                "INSERT INTO issues (client_name,title,description,engineer,priority,status,reported_at) VALUES (?,?,?,?,?,?,?)",
                (c, t, d, e, p, s, ts))
    con.commit()
    con.close()


# ---------- helpers ----------
def to_dict(row):
    reported = datetime.fromisoformat(row["reported_at"])
    overdue = (row["priority"] == "High" and row["status"] != "Resolved"
               and now_utc() - reported > timedelta(hours=24))
    return {
        "id": row["id"],
        "issue_id": f"ISS-{row['id']:04d}",
        "client_name": row["client_name"],
        "title": row["title"],
        "description": row["description"],
        "engineer": row["engineer"],
        "priority": row["priority"],
        "status": row["status"],
        "reported_at": row["reported_at"],
        "needs_attention": overdue,
    }


def validate(data, partial=False):
    """Return (clean_dict, errors_dict)."""
    clean, errors = {}, {}
    for f, label in (("client_name", "Client name"), ("title", "Issue title")):
        if f in data or not partial:
            v = str(data.get(f, "")).strip()
            if not v:
                errors[f] = f"{label} is required."
            elif len(v) > 200:
                errors[f] = f"{label} must be 200 characters or fewer."
            else:
                clean[f] = v
    if "description" in data or not partial:
        clean["description"] = str(data.get("description", "")).strip()[:5000]
    if "engineer" in data or not partial:
        engineer = str(data.get("engineer", "")).strip()
        if len(engineer) > 200:
            errors["engineer"] = "Assigned Engineer must be 200 characters or fewer."
        else:
            clean["engineer"] = engineer
    if "priority" in data or not partial:
        if data.get("priority") not in PRIORITIES:
            errors["priority"] = "Priority must be Low, Medium or High."
        else:
            clean["priority"] = data["priority"]
    if "status" in data or not partial:
        if data.get("status", "Open") not in STATUSES:
            errors["status"] = "Status must be Open, In Progress or Resolved."
        else:
            clean["status"] = data.get("status", "Open")
    if clean.get("status") == "Resolved" and not clean.get("engineer", "").strip():
        errors["engineer"] = "Select an Assigned Engineer before resolving this issue."
    return clean, errors


def fetch(issue_id):
    return get_db().execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()


# ---------- routes ----------
@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/issues")
def list_issues():
    sql, params = "SELECT * FROM issues WHERE 1=1", []
    q = request.args.get("search", "").strip()
    if q:
        sql += " AND (client_name LIKE ? OR title LIKE ?)"
        params += [f"%{q}%"] * 2
    if request.args.get("priority") in PRIORITIES:
        sql += " AND priority=?"
        params.append(request.args["priority"])
    if request.args.get("status") in STATUSES:
        sql += " AND status=?"
        params.append(request.args["status"])
    engineer = request.args.get("engineer", "").strip()
    if engineer:
        sql += " AND engineer LIKE ? COLLATE NOCASE"
        params.append(f"%{engineer}%")
    sql += " ORDER BY reported_at DESC, id DESC"
    rows = get_db().execute(sql, params).fetchall()
    return jsonify([to_dict(r) for r in rows])


@app.post("/api/issues")
def create_issue():
    clean, errors = validate(request.get_json(silent=True) or {})
    if errors:
        return jsonify(errors=errors), 400
    clean["reported_at"] = now_utc().isoformat(timespec="seconds")  # set by server
    db = get_db()
    cur = db.execute(
        "INSERT INTO issues (client_name,title,description,engineer,priority,status,reported_at) "
        "VALUES (:client_name,:title,:description,:engineer,:priority,:status,:reported_at)", clean)
    db.commit()
    return jsonify(to_dict(fetch(cur.lastrowid))), 201


@app.route("/api/issues/<int:issue_id>", methods=["PUT", "PATCH"])
def update_issue(issue_id):
    existing = fetch(issue_id)
    if existing is None:
        return jsonify(errors={"_": "Issue not found."}), 404
    clean, errors = validate(request.get_json(silent=True) or {}, partial=(request.method == "PATCH"))
    if not errors:
        status = clean.get("status", existing["status"])
        engineer = clean.get("engineer", existing["engineer"])
        if status == "Resolved" and not engineer.strip():
            errors["engineer"] = "Select an Assigned Engineer before resolving this issue."
    if errors:
        return jsonify(errors=errors), 400
    if clean:
        sets = ", ".join(f"{k}=:{k}" for k in clean)  # keys are whitelisted by validate()
        db = get_db()
        db.execute(f"UPDATE issues SET {sets} WHERE id=:id", {**clean, "id": issue_id})
        db.commit()
    return jsonify(to_dict(fetch(issue_id)))


@app.delete("/api/issues/<int:issue_id>")
def delete_issue(issue_id):
    db = get_db()
    cur = db.execute("DELETE FROM issues WHERE id=?", (issue_id,))
    db.commit()
    if cur.rowcount == 0:
        return jsonify(errors={"_": "Issue not found."}), 404
    return "", 204


init_db()

if __name__ == "__main__":
    app.run(debug=True)
