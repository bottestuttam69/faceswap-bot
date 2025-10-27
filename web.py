# web.py
# Full Admin Panel + Telegram Webhook + FaceSwap proxy
# Designed for Replit (or any host that gives a public URL)
# Admin login: ID=Palak123@@  PASS=Palak123@@

import os, time, json, sqlite3, base64, tempfile, requests
from flask import Flask, request, render_template_string, redirect, url_for, flash, session, send_file, jsonify
from werkzeug.utils import secure_filename

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_ROOT, "data.db")
GENERATED_DIR = os.path.join(APP_ROOT, "generated")
STATE_DIR = os.path.join(APP_ROOT, "state")
TOKEN_FILE = os.path.join(APP_ROOT, "bot_token.txt")
SETTINGS_FILE = os.path.join(APP_ROOT, "settings.json")

os.makedirs(GENERATED_DIR, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)

# Defaults
ADMIN_ID = "Palak123@@"
ADMIN_PASS = "Palak123@@"
RESET_PASS = "Palak123@@"
DEFAULT_FACE_API = "https://ng-faceswap.vercel.app/api/faceswap"  # you can change from admin

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "swap_secret_change_me")

# ---------- DB helpers ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
      CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        name TEXT,
        username TEXT,
        link TEXT,
        balance REAL DEFAULT 0,
        banned INTEGER DEFAULT 0,
        created_at TEXT
      )
    """)
    cur.execute("""
      CREATE TABLE IF NOT EXISTS stats (
        id INTEGER PRIMARY KEY CHECK(id=1),
        total_generated INTEGER DEFAULT 0,
        last_generated TEXT,
        started_at TEXT
      )
    """)
    cur.execute("INSERT OR IGNORE INTO stats (id, total_generated, started_at) VALUES (1,0,?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"),))
    cur.execute("""
      CREATE TABLE IF NOT EXISTS support (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        user_name TEXT,
        message TEXT,
        reply TEXT,
        created_at TEXT,
        status TEXT DEFAULT 'open'
      )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------- settings helpers ----------
def load_settings():
    default = {
        "auto_delete": True,
        "maintenance": False,
        "bot_name": "FaceSwap by Uttam",
        "announcement_channel": "",
        "credit_deposit_link": "https://example.com/deposit",
        "earning_mode": False,
        "price_usdt": 1.0,
        "price_inr": 85.0,
        "face_api": DEFAULT_FACE_API
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            j = json.load(open(SETTINGS_FILE))
            default.update(j)
        except:
            pass
    return default

def save_settings(d):
    json.dump(d, open(SETTINGS_FILE, "w"), indent=2)

# ---------- basic helpers ----------
def read_token():
    return open(TOKEN_FILE).read().strip() if os.path.exists(TOKEN_FILE) else ""

def write_token(t):
    open(TOKEN_FILE, "w").write(t.strip())

def validate_token(token):
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=8)
        return r.status_code == 200 and r.json().get("ok", False), r.json()
    except Exception as e:
        return False, {"error": str(e)}

def set_webhook(token, webhook_url):
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/setWebhook", params={"url": webhook_url}, timeout=8)
        return r.status_code == 200 and r.json().get("ok", False), r.json()
    except Exception as e:
        return False, {"error": str(e)}

def tg_send_message(token, chat_id, text, parse_mode="HTML"):
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode}, timeout=10)
        return r.status_code == 200, r.json()
    except Exception as e:
        return False, {"error": str(e)}

def tg_send_photo(token, chat_id, photo_path, caption=""):
    try:
        with open(photo_path, "rb") as f:
            files = {"photo": f}
            data = {"chat_id": chat_id, "caption": caption}
            r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", data=data, files=files, timeout=60)
        return r.status_code == 200, r.json()
    except Exception as e:
        return False, {"error": str(e)}

def tg_download_file(token, file_id, dest_path):
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getFile", params={"file_id": file_id}, timeout=8)
        jr = r.json()
        if not jr.get("ok"): return False, jr
        fp = jr["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{token}/{fp}"
        rr = requests.get(file_url, timeout=30)
        if rr.status_code == 200:
            open(dest_path, "wb").write(rr.content)
            return True, {"size": len(rr.content)}
        return False, {"status": rr.status_code}
    except Exception as e:
        return False, {"error": str(e)}

# ---------- user & stats helpers ----------
def add_or_update_user(user_id, name="", username=""):
    conn = get_conn(); cur = conn.cursor()
    link = f"https://t.me/{username}" if username else ""
    cur.execute("INSERT OR IGNORE INTO users(user_id,name,username,link,created_at) VALUES(?,?,?,?,?)",
                (user_id, name, username, link, time.strftime("%Y-%m-%d %H:%M:%S")))
    cur.execute("UPDATE users SET name=?, username=?, link=? WHERE user_id=?", (name, username, link, user_id))
    conn.commit(); conn.close()

def get_all_users():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT user_id,name,username,link,balance,banned,created_at FROM users ORDER BY created_at DESC")
    rows = cur.fetchall(); conn.close(); return rows

def change_balance(user_id, amount):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit(); conn.close()

def set_balance(user_id, amount):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE users SET balance = ? WHERE user_id=?", (amount, user_id))
    conn.commit(); conn.close()

def ban_unban(user_id, banned=1):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if banned else 0, user_id))
    conn.commit(); conn.close()

def increment_generated():
    conn = get_conn(); cur = conn.cursor()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("UPDATE stats SET total_generated = total_generated + 1, last_generated = ? WHERE id=1", (now,))
    conn.commit(); conn.close()

def get_stats():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT total_generated, last_generated, started_at FROM stats WHERE id=1")
    r = cur.fetchone(); conn.close()
    return {"total_generated": r["total_generated"], "last_generated": r["last_generated"], "started_at": r["started_at"]}

def add_support(user_id, user_name, message):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT INTO support(user_id,user_name,message,created_at) VALUES(?,?,?,?)",
                (user_id, user_name, message, time.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit(); conn.close()

def list_supports():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM support ORDER BY created_at DESC")
    r = cur.fetchall(); conn.close(); return r

def reply_support_db(sid, reply):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE support SET reply=?, status='replied' WHERE id=?", (reply, sid))
    conn.commit(); conn.close()

# ---------- Templates (polished but simple) ----------
INDEX_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Admin — {{settings.bot_name}}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
body{background:linear-gradient(135deg,#071032,#0f1724);color:#e6f6ff}
.card{border-radius:12px}
.small-muted{color:#cfe3ff}
.h1small{font-weight:700}
</style></head><body>
<div class="container py-4">
<div class="card p-4 shadow-sm">
  <div class="d-flex justify-content-between">
    <div>
      <h3 class="h1small">{{settings.bot_name}}</h3>
      <div class="small-muted">Admin panel — Manage bot, broadcast, users, credits</div>
    </div>
    <div>
      {% if session.admin %}<a class="btn btn-outline-light" href="/logout">Logout</a>{% endif %}
    </div>
  </div>
  <hr>
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for cat,msg in messages %}
      <div class="alert alert-{{'success' if cat=='ok' else 'danger'}}">{{msg}}</div>
    {% endfor %}
  {% endwith %}

  {% if not session.admin %}
    <form method="post" action="/login">
      <div class="mb-2"><input class="form-control" name="id" placeholder="Admin ID"></div>
      <div class="mb-2"><input class="form-control" name="pass" type="password" placeholder="Password"></div>
      <button class="btn btn-primary">Login</button>
      <div class="mt-2 small-muted">Use ID: <strong>{{admin_id}}</strong></div>
    </form>
  {% else %}
    <div class="row">
      <div class="col-md-6">
        <h5>Bot Connect & Settings</h5>
        <form method="post" action="/save_token">
          <input class="form-control mb-2" name="bot_token" placeholder="Paste Telegram Bot Token" value="{{token}}">
          <button class="btn btn-success mb-2">Save & Validate Token</button>
        </form>
        <div class="small-muted mb-2">Webhook: <code>{{webhook}}</code></div>

        <h6>Bot Settings</h6>
        <form method="post" action="/update_settings">
          <input class="form-control mb-2" name="bot_name" value="{{settings.bot_name}}">
          <input class="form-control mb-2" name="announcement_channel" value="{{settings.announcement_channel}}" placeholder="Announcement channel link">
          <input class="form-control mb-2" name="credit_deposit_link" value="{{settings.credit_deposit_link}}">
          <div class="form-check mb-2"><input class="form-check-input" type="checkbox" name="earning_mode" id="earn" {% if settings.earning_mode %}checked{% endif %}><label class="form-check-label" for="earn">Earning mode (1 credit per swap)</label></div>
          <div class="form-check mb-2"><input class="form-check-input" type="checkbox" name="auto_delete" id="adel" {% if settings.auto_delete %}checked{% endif %}><label class="form-check-label" for="adel">Auto-delete generated images</label></div>
          <div class="mb-2"><input class="form-control" name="price_usdt" value="{{settings.price_usdt}}" placeholder="Price per credit (USDT)"></div>
          <div class="mb-2"><input class="form-control" name="price_inr" value="{{settings.price_inr}}" placeholder="Price per USDT (INR)"></div>
          <div class="mb-2"><input class="form-control" name="face_api" value="{{settings.face_api}}" placeholder="Face swap API URL"></div>
          <button class="btn btn-outline-primary">Save Settings</button>
        </form>

        <hr>
        <h6>Broadcast / Direct Message</h6>
        <form method="post" action="/broadcast" enctype="multipart/form-data">
          <select class="form-select mb-2" name="type"><option value="text">Text</option><option value="image">Image</option><option value="video">Video</option></select>
          <textarea class="form-control mb-2" name="caption" placeholder="Message or caption"></textarea>
          <input type="file" name="file" class="form-control mb-2">
          <input class="form-control mb-2" name="target_user" placeholder="UserID (empty=all)">
          <button class="btn btn-warning">Send</button>
        </form>
      </div>

      <div class="col-md-6">
        <h5>Stats & Tools</h5>
        <ul class="list-group mb-2">
          <li class="list-group-item">Total users: <strong>{{users_count}}</strong></li>
          <li class="list-group-item">Total swaps: <strong>{{stats.total_generated}}</strong></li>
          <li class="list-group-item">Last swap: <strong>{{stats.last_generated or '—'}}</strong></li>
          <li class="list-group-item">Files in generated/: <strong>{{files_count}}</strong></li>
        </ul>

        <h6>Users</h6>
        <a class="btn btn-sm btn-secondary mb-2" href="/users">See All Users</a>
        <a class="btn btn-sm btn-danger mb-2" href="/download_db">Download DB</a>

        <h6 class="mt-3">Maintenance & Reset</h6>
        <form method="post" action="/toggle_maintenance"><button class="btn btn-outline-secondary mb-2">{{ 'Disable' if settings.maintenance else 'Enable' }} Maintenance</button></form>
        <form method="post" action="/reset_history"><input class="form-control mb-2" name="pwd" type="password" placeholder="Enter admin password"><button class="btn btn-danger">Reset History</button></form>

        <h6 class="mt-3">Support</h6>
        <a class="btn btn-sm btn-info" href="/support">Support Inbox</a>
      </div>
    </div>
  {% endif %}
</div>
<div class="mt-3 text-muted small">Tip: Use clear, front-facing photos for best swap results.</div>
</div></body></html>
"""

# ----------------- routes -----------------
@app.route("/", methods=["GET"])
def index():
    settings = load_settings()
    stats = get_stats()
    token = read_token()
    users = get_all_users()
    files_count = len([f for f in os.listdir(GENERATED_DIR) if os.path.isfile(os.path.join(GENERATED_DIR, f))])
    return render_template_string(INDEX_HTML, session={"admin": session.get("admin")}, settings=settings,
                                  stats=stats, token=token, users_count=len(users), files_count=files_count,
                                  admin_id=ADMIN_ID, webhook=(request.url_root.strip("/") + "/webhook"))

@app.route("/login", methods=["POST"])
def login():
    idv = request.form.get("id","")
    pwd = request.form.get("pass","")
    if idv == ADMIN_ID and pwd == ADMIN_PASS:
        session['admin'] = True
        flash("Logged in","ok")
    else:
        flash("Wrong credentials","err")
    return redirect("/")

@app.route("/logout")
def logout():
    session.pop("admin", None)
    flash("Logged out","ok")
    return redirect("/")

@app.route("/save_token", methods=["POST"])
def save_token():
    if not session.get("admin"):
        flash("Unauthorized","err"); return redirect("/")
    token = request.form.get("bot_token","").strip()
    ok, info = validate_token(token)
    if not ok:
        flash("Invalid token or network error","err"); return redirect("/")
    write_token(token)
    # try to set webhook automatically
    webhook_url = request.url_root.strip("/") + "/webhook"
    ok2, info2 = set_webhook(token, webhook_url)
    if ok2:
        flash("Token saved and webhook set","ok")
    else:
        flash("Token saved but webhook set failed: " + json.dumps(info2),"err")
    return redirect("/")

@app.route("/update_settings", methods=["POST"])
def update_settings():
    if not session.get("admin"):
        flash("Unauthorized","err"); return redirect("/")
    s = load_settings()
    s["bot_name"] = request.form.get("bot_name", s.get("bot_name"))
    s["announcement_channel"] = request.form.get("announcement_channel", s.get("announcement_channel"))
    s["credit_deposit_link"] = request.form.get("credit_deposit_link", s.get("credit_deposit_link"))
    s["earning_mode"] = True if request.form.get("earning_mode") == "on" else False
    s["auto_delete"] = True if request.form.get("auto_delete") == "on" else False
    try:
        s["price_usdt"] = float(request.form.get("price_usdt", s.get("price_usdt")))
        s["price_inr"] = float(request.form.get("price_inr", s.get("price_inr")))
    except:
        pass
    s["face_api"] = request.form.get("face_api", s.get("face_api"))
    save_settings(s)
    flash("Settings updated","ok")
    return redirect("/")

@app.route("/broadcast", methods=["POST"])
def broadcast():
    if not session.get("admin"):
        flash("Unauthorized","err"); return redirect("/")
    t = request.form.get("type","text")
    caption = request.form.get("caption","")
    target = request.form.get("target_user","").strip()
    token = read_token()
    if not token:
        flash("No bot token","err"); return redirect("/")
    users = []
    if target:
        try:
            users = [(int(target),)]
        except:
            flash("Invalid user id","err"); return redirect("/")
    else:
        rows = get_all_users()
        users = [(r["user_id"],) for r in rows if r["banned"]==0]
    sent = 0
    file = request.files.get("file")
    for u in users:
        uid = u[0]
        if t == "text":
            ok,_ = tg_send_message(token, uid, caption)
            if ok: sent += 1
        elif t == "image" and file:
            tmp = tempfile.gettempdir()+"/"+secure_filename(file.filename)
            file.save(tmp)
            ok,_ = tg_send_photo(token, uid, tmp, caption)
            try: os.remove(tmp)
            except: pass
            if ok: sent += 1
        elif t == "video" and file:
            tmp = tempfile.gettempdir()+"/"+secure_filename(file.filename)
            file.save(tmp)
            try:
                r = requests.post(f"https://api.telegram.org/bot{token}/sendVideo", data={"chat_id": uid, "caption": caption}, files={"video": open(tmp,"rb")}, timeout=60)
                if r.status_code == 200: sent += 1
            except:
                pass
            try: os.remove(tmp)
            except: pass
    flash(f"Broadcast attempted to {sent} users","ok")
    return redirect("/")

@app.route("/users")
def users_page():
    if not session.get("admin"):
        flash("Unauthorized","err"); return redirect("/")
    rows = get_all_users()
    html = "<h3>Users</h3><a href='/'>Back</a><table class='table table-sm'><tr><th>user_id</th><th>name</th><th>username</th><th>balance</th><th>banned</th><th>actions</th></tr>"
    for r in rows:
        html += f"<tr><td>{r['user_id']}</td><td>{r['name']}</td><td>{r['username']}</td><td>{r['balance']}</td><td>{r['banned']}</td>"
        html += f"<td><a href='/ban/{r['user_id']}'>Ban</a> | <a href='/unban/{r['user_id']}'>Unban</a> | <a href='/edit_balance/{r['user_id']}'>Adjust</a></td></tr>"
    html += "</table>"
    return html

@app.route("/ban/<int:uid>")
def ban(uid):
    if not session.get("admin"): return redirect("/")
    ban_unban(uid, 1); flash("Banned","ok"); return redirect("/users")
@app.route("/unban/<int:uid>")
def unban(uid):
    if not session.get("admin"): return redirect("/")
    ban_unban(uid, 0); flash("Unbanned","ok"); return redirect("/users")

@app.route("/edit_balance/<int:uid>", methods=["GET","POST"])
def edit_balance(uid):
    if not session.get("admin"): return redirect("/")
    if request.method=="GET":
        return f"<form method='post'><input name='amount' placeholder='+ add, - deduct'><button>Save</button></form>"
    amt = float(request.form.get("amount","0"))
    change_balance(uid, amt)
    flash("Balance updated","ok"); return redirect("/users")

@app.route("/download_db")
def download_db():
    if not session.get("admin"): return redirect("/")
    return send_file(DB_PATH, as_attachment=True, download_name="data.db")

@app.route("/toggle_maintenance", methods=["POST"])
def toggle_maintenance():
    if not session.get("admin"): return redirect("/")
    s = load_settings(); s["maintenance"] = not s.get("maintenance", False); save_settings(s)
    flash("Maintenance toggled","ok"); return redirect("/")

@app.route("/reset_history", methods=["POST"])
def reset_history():
    if not session.get("admin"): return redirect("/")
    pwd = request.form.get("pwd","")
    if pwd != RESET_PASS:
        flash("Wrong password","err"); return redirect("/")
    deleted = 0
    for f in os.listdir(GENERATED_DIR):
        try: os.remove(os.path.join(GENERATED_DIR, f)); deleted += 1
        except: pass
    # ---------- Support Page ----------
@app.route("/support")
def support_inbox():
    if not session.get("admin"):
        return redirect("/")
    data = list_supports()
    html = "<h3>Support Messages</h3><a href='/'>Back</a><table class='table table-sm'><tr><th>ID</th><th>User</th><th>Message</th><th>Reply</th><th>Status</th><th>Action</th></tr>"
    for d in data:
        html += f"<tr><td>{d['id']}</td><td>{d['user_name']} ({d['user_id']})</td><td>{d['message']}</td><td>{d['reply'] or ''}</td><td>{d['status']}</td>"
        html += f"<td><a href='/reply_support/{d['id']}'>Reply</a></td></tr>"
    html += "</table>"
    return html

@app.route("/reply_support/<int:sid>", methods=["GET","POST"])
def reply_support(sid):
    if not session.get("admin"):
        return redirect("/")
    if request.method == "GET":
        return f"<form method='post'><textarea name='reply' placeholder='Reply message'></textarea><br><button>Send</button></form>"
    reply = request.form.get("reply", "")
    reply_support_db(sid, reply)
    flash("Reply sent", "ok")
    return redirect("/support")

# ---------- Telegram Webhook ----------
@app.route("/webhook", methods=["POST"])
def webhook():
    settings = load_settings()
    if settings.get("maintenance"):
        return "Maintenance", 200
    token = read_token()
    if not token:
        return "No token", 200

    data = request.json
    if not data:
        return "No JSON", 200

    message = data.get("message") or data.get("edited_message")
    if not message:
        return "No message", 200

    chat_id = message["chat"]["id"]
    name = message["chat"].get("first_name", "")
    username = message["chat"].get("username", "")
    text = message.get("text", "").strip()

    add_or_update_user(chat_id, name, username)

    if text.lower() in ["/start", "start"]:
        reply = (
            f"👋 <b>Welcome to {settings['bot_name']}</b>\n\n"
            "Send two clear face photos — one to replace (base) and one with face you want to swap!\n\n"
            "✨ You can also send /help for guide.\n"
        )
        tg_send_message(token, chat_id, reply)
        return "ok", 200

    if text.lower() in ["/help", "help"]:
        tg_send_message(token, chat_id, "📘 Send two images — base and face. I’ll swap them automatically!")
        return "ok", 200

    # support
    if text.lower().startswith("/support"):
        msg = text.replace("/support", "").strip()
        if not msg:
            tg_send_message(token, chat_id, "🧾 Usage: /support your message here")
        else:
            add_support(chat_id, name, msg)
            tg_send_message(token, chat_id, "✅ Support message sent to admin.")
        return "ok", 200

    # --- Handle photos for swapping ---
    if "photo" in message:
        file_id = message["photo"][-1]["file_id"]
        user_state = os.path.join(STATE_DIR, f"{chat_id}.json")

        if not os.path.exists(user_state):
            # first photo
            tmp = os.path.join(tempfile.gettempdir(), f"{chat_id}_1.jpg")
            ok, _ = tg_download_file(token, file_id, tmp)
            if ok:
                json.dump({"base": tmp}, open(user_state, "w"))
                tg_send_message(token, chat_id, "📸 Got first photo! Now send the second one (face to swap).")
            return "ok", 200
        else:
            # second photo
            data = json.load(open(user_state))
            base_path = data.get("base")
            tmp2 = os.path.join(tempfile.gettempdir(), f"{chat_id}_2.jpg")
            ok, _ = tg_download_file(token, file_id, tmp2)
            if not ok:
                tg_send_message(token, chat_id, "⚠️ Failed to download second image.")
                return "ok", 200

            # earning mode
            if settings.get("earning_mode"):
                conn = get_conn()
                cur = conn.cursor()
                cur.execute("SELECT balance FROM users WHERE user_id=?", (chat_id,))
                bal = cur.fetchone()["balance"]
                conn.close()
                if bal < 1:
                    tg_send_message(token, chat_id, f"💰 You need at least 1 credit to swap.\nDeposit here: {settings['credit_deposit_link']}")
                    return "ok", 200
                change_balance(chat_id, -1)

            # Perform face swap
            files = {"base": open(base_path, "rb"), "face": open(tmp2, "rb")}
            try:
                r = requests.post(settings["face_api"], files=files, timeout=180)
                if r.status_code == 200:
                    out_path = os.path.join(GENERATED_DIR, f"{chat_id}_{int(time.time())}.jpg")
                    open(out_path, "wb").write(r.content)
                    increment_generated()
                    tg_send_photo(token, chat_id, out_path, caption="✨ Swap complete!")
                    if settings.get("auto_delete"):
                        os.remove(base_path)
                        os.remove(tmp2)
                        os.remove(user_state)
                else:
                    tg_send_message(token, chat_id, "❌ Face swap failed. Try again.")
            except Exception as e:
                tg_send_message(token, chat_id, f"⚠️ Error: {e}")
            return "ok", 200

    return "ok", 200

# ---------- Run app ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
