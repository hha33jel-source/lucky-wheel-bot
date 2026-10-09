import os, sqlite3, time, hmac, hashlib, json, random
from urllib.parse import parse_qsl
from flask import Flask, jsonify, request, send_from_directory

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or "0")
DB_PATH = os.environ.get("DB_PATH", "wheel.sqlite3")
DAILY_SECONDS = 24 * 60 * 60

# Prizes and probabilities. Keep labels and points aligned with static/index.html.
PRIZES = [
    {"label": "0 نقطة", "points": 0, "weight": 20},
    {"label": "5 نقاط", "points": 5, "weight": 25},
    {"label": "10 نقاط", "points": 10, "weight": 22},
    {"label": "20 نقطة", "points": 20, "weight": 15},
    {"label": "50 نقطة", "points": 50, "weight": 10},
    {"label": "100 نقطة", "points": 100, "weight": 5},
    {"label": "حظ أوفر", "points": 0, "weight": 3},
]

app = Flask(__name__, static_folder="static")

def connect():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, first_name TEXT DEFAULT '',
            points INTEGER NOT NULL DEFAULT 0, last_free_spin INTEGER NOT NULL DEFAULT 0
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            label TEXT NOT NULL, points INTEGER NOT NULL, created_at INTEGER NOT NULL,
            source TEXT NOT NULL
        )""")

def get_balance(user_id):
    with connect() as db:
        row = db.execute("SELECT points FROM users WHERE user_id=?", (user_id,)).fetchone()
        return int(row["points"]) if row else 0

def add_points(user_id, amount, source="admin"):
    now = int(time.time())
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO users(user_id, points) VALUES(?, 0)", (user_id,))
        db.execute("UPDATE users SET points=points+? WHERE user_id=?", (amount, user_id))
        db.execute("INSERT INTO history(user_id,label,points,created_at,source) VALUES(?,?,?,?,?)",
                   (user_id, f"+{amount} نقطة", amount, now, source))

def validate_init_data(init_data):
    """Validate Telegram Web App initData; never trust user IDs sent by the browser alone."""
    if not BOT_TOKEN or not init_data:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", None)
        if not received_hash:
            return None
        auth_date = int(pairs.get("auth_date", "0"))
        if auth_date <= 0 or abs(int(time.time()) - auth_date) > 86400:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            return None
        user_data = json.loads(pairs.get("user", "{}"))
        user_id = int(user_data["id"])
        first_name = str(user_data.get("first_name", ""))[:80]
        return {"id": user_id, "first_name": first_name}
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None

def require_user():
    data = validate_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    if not data:
        return None
    return data

@app.get("/")
def home():
    return send_from_directory("static", "index.html")

@app.get("/api/state")
def state():
    user = require_user()
    if not user:
        return jsonify({"error": "افتح اللعبة من داخل بوت تلغرام."}), 401
    now = int(time.time())
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO users(user_id, first_name) VALUES(?,?)",
                   (user["id"], user["first_name"]))
        db.execute("UPDATE users SET first_name=? WHERE user_id=?",
                   (user["first_name"], user["id"]))
        row = db.execute("SELECT points,last_free_spin FROM users WHERE user_id=?",
                         (user["id"],)).fetchone()
        hist = db.execute("SELECT label,points,created_at FROM history WHERE user_id=? "
                          "ORDER BY id DESC LIMIT 10", (user["id"],)).fetchall()
    last = int(row["last_free_spin"])
    remaining = max(0, DAILY_SECONDS - (now - last)) if last else 0
    return jsonify({
        "first_name": user["first_name"], "points": int(row["points"]),
        "free_spin_available": remaining == 0, "free_spin_seconds": remaining,
        "history": [{"label": r["label"], "points": r["points"], "created_at": r["created_at"]} for r in hist],
        "prizes": [{"label": p["label"], "points": p["points"]} for p in PRIZES]
    })

def perform_spin(user_id, source):
    now = int(time.time())
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT OR IGNORE INTO users(user_id, points, last_free_spin) VALUES(?,0,0)", (user_id,))
        row = db.execute("SELECT points,last_free_spin FROM users WHERE user_id=?", (user_id,)).fetchone()
        if source == "free":
            if row["last_free_spin"] and now - int(row["last_free_spin"]) < DAILY_SECONDS:
                db.rollback()
                return None, "استخدمت محاولتك المجانية. حاول مجددًا بعد انتهاء المؤقت."
            db.execute("UPDATE users SET last_free_spin=? WHERE user_id=?", (now, user_id))
        else:
            db.rollback()
            return None, "التدوير المجاني فقط متاح في هذه اللعبة."
        prize = random.choices(PRIZES, weights=[p["weight"] for p in PRIZES], k=1)[0]
        db.execute("UPDATE users SET points=points+? WHERE user_id=?", (prize["points"], user_id))
        db.execute("INSERT INTO history(user_id,label,points,created_at,source) VALUES(?,?,?,?,?)",
                   (user_id, prize["label"], prize["points"], now, source))
        balance = db.execute("SELECT points FROM users WHERE user_id=?", (user_id,)).fetchone()["points"]
        db.commit()
    return {"label": prize["label"], "points": prize["points"], "balance": balance,
            "prize_index": PRIZES.index(prize)}, None

@app.post("/api/spin")
def spin():
    user = require_user()
    if not user:
        return jsonify({"error": "تعذر التحقق من حساب تلغرام. افتح البوت ثم اضغط زر العجلة."}), 401
    body = request.get_json(silent=True) or {}
    result, error = perform_spin(user["id"], "free")
    if error:
        return jsonify({"error": error}), 400
    return jsonify(result)

@app.get("/health")
def health():
    return jsonify({"ok": True})

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
