# web.py
import os, time, base64, json, sqlite3, tempfile, shutil, requests
from flask import Flask, request, render_template_string, redirect, url_for, flash, session, send_file, jsonify
from werkzeug.utils import secure_filename
from bot import read_token, write_token, validate_token, set_webhook, tg_send_message, tg_send_photo, tg_download_file

APP_ROOT = os.path.dirname(os.path.abspath(__file__))

# --- Config defaults (change via admin UI) ---
ADMIN_ID = "Palak123@@"
ADMIN_PASS = "Palak123@@"
RESET_PASS = "Palak123@@"
FACE_SWAP_API = "https://ng-faceswap.vercel.app/api/faceswap"  # external API (can change in admin)
APP_DOMAIN = None  # set to your render domain in env if you want auto-webhook
CREDIT_DEPOSIT_LINK = "https://example.com/deposit"  # editable from admin
BOT_DISPLAY_NAME = "FaceSwap by Uttam"  # editable from admin

# --- Paths ---
DB_PATH = os.path.join(APP_ROOT, "data.db")
GENERATED = os.path.join(APP_ROOT, "generated")
STATE = os.path.join(APP_ROOT, "state")
SETTINGS_FILE = os.path.join(APP_ROOT, "settings.json")
SUPPORT_FILE = os.path.join(APP_ROOT, "support.json")  # store support messages
os.makedirs(GENERATED, exist_ok=True)
os.makedirs(STATE, exist_ok=True)

# Flask init
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "swapapi_secret_change_me")

# --- DB helpers ---
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
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
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS stats (
      id INTEGER PRIMARY KEY CHECK (id=1),
      total_generated INTEGER DEFAULT 0,
      last_generated TEXT
    )""")
    cur.execute("INSERT OR IGNORE INTO stats (id, total_generated) VALUES (1,0)")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS support (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER,
      user_name TEXT,
      message TEXT,
      reply TEXT,
      created_at TEXT,
      status TEXT DEFAULT 'open'
    )""")
    conn.commit()
    conn.close()

init_db()

# --- Settings helpers ---
def load_settings():
    default = {
        "auto_delete": True,
        "maintenance": False,
        "bot_name": BOT_DISPLAY_NAME,
        "announcement_channel": "",
        "currency_price_inr": 1.0,
        "currency_price_usdt": 1.0,
        "credit_deposit_link": CREDIT_DEPOSIT_LINK,
        "earning_mode": False
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

# --- Utility functions ---
def increment_generated():
    conn = get_conn()
    cur = conn.cursor()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("UPDATE stats SET total_generated = total_generated + 1, last_generated = ? WHERE id=1", (now,))
    conn.commit()
    conn.close()

def get_stats():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT total_generated, last_generated FROM stats WHERE id=1")
    row = cur.fetchone()
    conn.close()
    return {"total_generated": row["total_generated"], "last_generated": row["last_generated"]}

def add_or_update_user(user_id, name="", username=""):
    conn = get_conn(); cur = conn.cursor()
    link = f"https://t.me/{username}" if username else ""
    cur.execute("INSERT OR IGNORE INTO users(user_id,name,username,link,created_at) VALUES(?,?,?,?,?)",
                (user_id, name, username, link, time.strftime("%Y-%m-%d %H:%M:%S")))
    cur.execute("UPDATE users SET name=?, username=?, link=? WHERE user_id=?", (name, username, link, user_id))
    conn.commit(); conn.close()

def change_balance(user_id, amount):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit(); conn.close()

def set_balance(user_id, amount):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE users SET balance = ? WHERE user_id=?", (amount, user_id))
    conn.commit(); conn.close()

def get_all_users():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT user_id,name,username,link,balance,banned,created_at FROM users ORDER BY created_at DESC")
    rows = cur.fetchall(); conn.close()
    return rows

def ban_unban(user_id, banned=1):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if banned else 0, user_id))
    conn.commit(); conn.close()

# --- Support messages ---
def add_support(user_id, user_name, message):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT INTO support(user_id,user_name,message,created_at) VALUES(?,?,?,?)",
                (user_id, user_name, message, time.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit(); conn.close()

def list_supports():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM support ORDER BY created_at DESC")
    r = cur.fetchall(); conn.close(); return r

def reply_support(support_id, reply_text):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE support SET reply=?, status='replied' WHERE id=?", (reply_text, support_id))
    conn.commit(); conn.close()

# --- Admin templates (kept concise but polished) ---
INDEX_HTML = """<!doctype html><html lang="en">
<head><meta charset="utf-8"><title>Admin — FaceSwap</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<style>body{background:linear-gradient(135deg,#0f1724,#071032);color:#e6f0ff} .card{border-radius:12px;} .small-muted{color:#cfe3ff}</style>
</head><body>
<div class="container py-4">
  <div class="card p-4 mb-3">
    <div class="d-flex justify-content-between align-items-center">
      <h3>{{settings.bot_name}} — Admin Panel</h3>
      <div><small class="small-muted">Admin</small></div>
    </div>
    <hr>
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% for cat,msg in messages %}
        <div class="alert alert-{{'success' if cat=='ok' else 'danger'}}">{{msg}}</div>
      {% endfor %}
    {% endwith %}
    {% if not session.get('admin') %}
      <form method="post" action="/login">
        <div class="mb-2"><input class="form-control" name="id" placeholder="Admin ID"></div>
        <div class="mb-2"><input class="form-control" name="pass" type="password" placeholder="Password"></div>
        <button class="btn btn-primary">Login</button>
        <div class="mt-2 small-muted">ID & Password: <strong>{{admin_id}}</strong></div>
      </form>
    {% else %}
      <div class="row">
        <div class="col-md-6">
          <h5>Bot & Webhook</h5>
          <form method="post" action="/save_token">
            <input class="form-control mb-2" name="bot_token" placeholder="Telegram bot token" value="{{token}}">
            <button class="btn btn-success">Validate & Connect Bot</button>
          </form>
          <div class="mt-2 small-muted">Webhook URL: <code>{{webhook}}</code></div>
          <hr>
          <h5>Settings</h5>
          <form method="post" action="/update_settings">
            <div class="mb-2"><input class="form-control" name="bot_name" placeholder="Bot display name" value="{{settings.bot_name}}"></div>
            <div class="mb-2"><input class="form-control" name="announcement_channel" placeholder="Announcement channel link" value="{{settings.announcement_channel}}"></div>
            <div class="mb-2"><input class="form-control" name="credit_deposit_link" placeholder="Deposit link" value="{{settings.credit_deposit_link}}"></div>
            <div class="mb-2 form-check"><input class="form-check-input" type="checkbox" name="earning_mode" id="earn" {% if settings.earning_mode %}checked{% endif %}><label class="form-check-label" for="earn">Earning Mode (credits required)</label></div>
            <div class="mb-2 form-check"><input class="form-check-input" type="checkbox" name="auto_delete" id="adel" {% if settings.auto_delete %}checked{% endif %}><label class="form-check-label" for="adel">Auto-delete generated images</label></div>
            <button class="btn btn-outline-primary">Save Settings</button>
          </form>
          <hr>
          <h5>Broadcast / Direct</h5>
          <form method="post" action="/broadcast" enctype="multipart/form-data">
            <div class="mb-2"><select class="form-select" name="type"><option value="text">Text</option><option value="image">Image</option><option value="video">Video</option></select></div>
            <div class="mb-2"><textarea class="form-control" name="caption" placeholder="Message or caption"></textarea></div>
            <div class="mb-2"><input type="file" name="file" class="form-control"></div>
            <div class="mb-2"><input class="form-control" name="target_user" placeholder="UserID (empty = broadcast all)"></div>
            <button class="btn btn-warning">Send</button>
          </form>
        </div>

        <div class="col-md-6">
          <h5>Stats</h5>
          <ul class="list-group">
            <li class="list-group-item">Total generated: <strong>{{stats.total_generated}}</strong></li>
            <li class="list-group-item">Last generated: <strong>{{stats.last_generated or '—'}}</strong></li>
            <li class="list-group-item">Users: <strong>{{users_count}}</strong></li>
            <li class="list-group-item">Files in generated/: <strong>{{files_count}}</strong></li>
          </ul>
          <hr>
          <h5>Users</h5>
          <a class="btn btn-sm btn-secondary mb-2" href="/users">See All Users</a>
          <a class="btn btn-sm btn-danger mb-2" href="/download_db">Download DB</a>
          <form method="post" action="/reset_history" class="mt-2">
            <input class="form-control mb-2" name="pwd" type="password" placeholder="Enter admin password to confirm">
            <button class="btn btn-outline-danger">Reset History</button>
          </form>
        </div>
      </div>
    {% endif %}
  </div>

  <div class="mt-3 text-muted small">Tip: Use clear images for best face-swap results. Admin features: ban/unban, credit adjust, support reply, broadcast.</div>
</div>
</body></html>"""

# --- Routes: index & login ---
@app.route("/", methods=["GET"])
def index():
    settings = load_settings()
    stats = get_stats()
    token = read_token()
    users = get_all_users()
    files_count = len([f for f in os.listdir(GENERATED) if os.path.isfile(os.path.join(GENERATED, f))])
    return render_template_string(INDEX_HTML, session=session, settings=settings, stats=stats,
                                  token=token, users_count=len(users), files_count=files_count,
                                  admin_id=ADMIN_ID, webhook=(f"https://{APP_DOMAIN}/webhook" if APP_DOMAIN else "/webhook"))

@app.route("/login", methods=["POST"])
def login():
    uid = request.form.get("id", "")
    pwd = request.form.get("pass", "")
    if uid == ADMIN_ID and pwd == ADMIN_PASS:
        session['admin'] = True
        flash("Logged in", "ok")
    else:
        flash("Wrong credentials", "err")
    return redirect("/")

@app.route("/logout")
def logout():
    session.pop("admin", None)
    flash("Logged out", "ok")
    return redirect("/")

# --- Save token & set webhook ---
@app.route("/save_token", methods=["POST"])
def save_token():
    if not session.get("admin"):
        flash("Unauthorized", "err"); return redirect("/")
    token = request.form.get("bot_token", "").strip()
    ok, info = validate_token(token)
    if not ok:
        flash("Invalid token: " + str(info), "err")
        return redirect("/")
    write_token(token)
    # set webhook if domain provided
    if APP_DOMAIN:
        webhook_url = f"https://{APP_DOMAIN}/webhook"
        ok2, info2 = set_webhook(token, webhook_url)
        if ok2:
            flash("Token saved and webhook set.", "ok")
        else:
            flash("Token saved but webhook failed: " + str(info2), "err")
    else:
        flash("Token saved. Set APP_DOMAIN env to auto-set webhook.", "ok")
    return redirect("/")

# --- Update settings ---
@app.route("/update_settings", methods=["POST"])
def update_settings():
    if not session.get("admin"):
        flash("Unauthorized", "err"); return redirect("/")
    s = load_settings()
    s["bot_name"] = request.form.get("bot_name", s.get("bot_name"))
    s["announcement_channel"] = request.form.get("announcement_channel", s.get("announcement_channel"))
    s["credit_deposit_link"] = request.form.get("credit_deposit_link", s.get("credit_deposit_link"))
    s["earning_mode"] = True if request.form.get("earning_mode") == "on" else False
    s["auto_delete"] = True if request.form.get("auto_delete") == "on" else False
    save_settings(s)
    flash("Settings saved", "ok")
    return redirect("/")

# --- Broadcast / send ---
@app.route("/broadcast", methods=["POST"])
def broadcast():
    if not session.get("admin"):
        flash("Unauthorized", "err"); return redirect("/")
    ttype = request.form.get("type", "text")
    caption = request.form.get("caption", "")
    target = request.form.get("target_user", "").strip()
    token = read_token()
    if not token:
        flash("No token saved", "err"); return redirect("/")
    users = []
    if target:
        users = [(int(target),)]
    else:
        rows = get_all_users()
        users = [(row["user_id"],) for row in rows if row["banned"]==0]
    sent = 0
    for u in users:
        uid = u[0]
        if ttype == "text":
            ok,_ = tg_send_message(token, uid, caption)
            if ok: sent += 1
        elif ttype == "image":
            f = request.files.get("file")
            if not f:
                continue
            tmp = os.path.join(tempfile.gettempdir(), secure_filename(f.filename))
            f.save(tmp)
            ok,_ = tg_send_photo(token, uid, tmp, caption)
            try: os.remove(tmp)
            except: pass
            if ok: sent += 1
        elif ttype == "video":
            f = request.files.get("file")
            if not f:
                continue
            tmp = os.path.join(tempfile.gettempdir(), secure_filename(f.filename))
            f.save(tmp)
            try:
                # reuse same method (tg_send_photo won't work for video) - fallback to sendMessage link or implement sendVideo
                r = requests.post(f"https://api.telegram.org/bot{token}/sendVideo", data={"chat_id": uid, "caption": caption}, files={"video": open(tmp, "rb")})
                if r.status_code == 200: sent += 1
            except: pass
            try: os.remove(tmp)
            except: pass
    flash(f"Broadcast sent to {sent} users (attempted).", "ok")
    return redirect("/")

# --- Users list, ban/unban, adjust balance, download DB ---
@app.route("/users")
def users():
    if not session.get("admin"):
        flash("Unauthorized", "err"); return redirect("/")
    rows = get_all_users()
    html = "<h3>All Users</h3><a href='/'>Back</a><table border=1 cellpadding=6><tr><th>user_id</th><th>name</th><th>username</th><th>balance</th><th>banned</th><th>actions</th></tr>"
    for r in rows:
        html += f"<tr><td>{r['user_id']}</td><td>{r['name']}</td><td>{r['username']}</td><td>{r['balance']}</td><td>{r['banned']}</td>"
        html += f"<td><a href='/ban/{r['user_id']}'>Ban</a> | <a href='/unban/{r['user_id']}'>Unban</a> | <a href='/edit_balance/{r['user_id']}'>Adjust</a></td></tr>"
    html += "</table>"
    return html

@app.route("/ban/<int:uid>")
def ban(uid):
    if not session.get("admin"): return redirect("/")
    ban_unban(uid, 1)
    flash("User banned", "ok"); return redirect("/users")

@app.route("/unban/<int:uid>")
def unban(uid):
    if not session.get("admin"): return redirect("/")
    ban_unban(uid, 0)
    flash("User unbanned", "ok"); return redirect("/users")

@app.route("/edit_balance/<int:uid>", methods=["GET","POST"])
def edit_balance(uid):
    if not session.get("admin"): return redirect("/")
    if request.method == "GET":
        return f"<form method='post'><input name='amount' placeholder='+ for add, - for deduct'><button>Save</button></form>"
    amt = float(request.form.get("amount", "0"))
    change_balance(uid, amt)
    flash("Balance updated", "ok"); return redirect("/users")

@app.route("/download_db")
def download_db():
    if not session.get("admin"): return redirect("/")
    return send_file(DB_PATH, as_attachment=True, download_name="data.db")

# --- Reset history (delete generated files) ---
@app.route("/reset_history", methods=["POST"])
def reset_history():
    if not session.get("admin"): return redirect("/")
    pwd = request.form.get("pwd","")
    if pwd != RESET_PASS:
        flash("Wrong password", "err"); return redirect("/")
    deleted = 0
    for f in os.listdir(GENERATED):
        try: os.remove(os.path.join(GENERATED,f)); deleted += 1
        except: pass
    # reset stats
    conn = get_conn(); cur = conn.cursor(); cur.execute("UPDATE stats SET total_generated=0, last_generated=NULL WHERE id=1"); conn.commit(); conn.close()
    flash(f"Deleted {deleted} files and reset counters", "ok")
    return redirect("/")

# --- Support inbox ---
@app.route("/support")
def support_inbox():
    if not session.get("admin"): return redirect("/")
    rows = list_supports()
    html = "<h3>Support Messages</h3><a href='/'>Back</a><ul>"
    for r in rows:
        html += f"<li>#{r['id']} from {r['user_name']} ({r['user_id']}): {r['message']} <form method='post' action='/reply_support/{r['id']}'><input name='reply' placeholder='Reply'><button>Send</button></form></li>"
    html += "</ul>"
    return html

@app.route("/reply_support/<int:sid>", methods=["POST"])
def reply_support_route(sid):
    if not session.get("admin"): return redirect("/")
    reply_text = request.form.get("reply","")
    reply_support(sid, reply_text)
    # optionally notify user via telegram
    # fetch support entry to get user id
    conn = get_conn(); cur = conn.cursor(); cur.execute("SELECT user_id FROM support WHERE id=?", (sid,)); r = cur.fetchone(); conn.close()
    if r:
        token = read_token()
        if token:
            tg_send_message(token, r["user_id"], reply_text)
    flash("Replied", "ok"); return redirect("/support")

# --- Webhook handler (Telegram sends updates here) ---
@app.route("/webhook", methods=["POST"])
def webhook():
    token = read_token()
    if not token:
        return "no-token", 200
    update = request.get_json(force=True, silent=True)
    if not update:
        return "ok", 200

    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return "ok", 200

    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    text = msg.get("text", "").strip() if msg.get("text") else ""
    from_user = msg.get("from", {})
    user_name = from_user.get("first_name", "") + (" " + (from_user.get("last_name") or "") if from_user.get("last_name") else "")
    username = from_user.get("username") or ""

    # register user in DB
    add_or_update_user(chat_id, user_name, username)

    settings = load_settings()
    if settings.get("maintenance", False):
        tg_send_message(token, chat_id, "Bot under maintenance. Try later.")
        return "ok", 200

    # handle commands via inline-style texts: no /commands needed; we will accept messages "Swap" or button clicks
    # simple flow: user sends "Swap" text or presses inline button (we do not implement inline keyboards in this simple webhook)
    if text.lower() in ["start", "hi", "hello"]:
        msg_text = (
            f"👋 Welcome to {settings.get('bot_name')}!\n\n"
            "✨ This bot can swap faces in your photos!\n\n"
            "🪙 Credits System: Each successful swap costs 1 credit (if enabled).\n"
            "💰 Deposit credits from the 'Deposit Credits' button below.\n\n"
            "📸 Send any photo and reply with another face photo to swap.\n\n"
            "👇 Choose an option below:"
        )
        buttons = [
            [{"text": "📸 Swap Faces", "callback_data": "swap"}],
            [{"text": "💰 Deposit Credits", "callback_data": "deposit"}],
            [{"text": "📩 Support", "callback_data": "support"}]
        ]
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat_id, "text": msg_text,
                            "reply_markup": {"inline_keyboard": buttons}})
        return "ok", 200

    # Swap process: expecting user to send two images sequentially
    if "photo" in msg:
        # Save incoming photo
        file_id = msg["photo"][-1]["file_id"]
        file_path = tg_download_file(token, file_id)
        state_file = os.path.join(STATE, f"{chat_id}.json")
        if os.path.exists(state_file):
            # second image received -> perform swap
            with open(state_file) as f:
                first = json.load(f)
            os.remove(state_file)
            tg_send_message(token, chat_id, "⚙️ Please wait while swapping faces...")
            try:
                files = {"target": open(first["path"], "rb"), "source": open(file_path, "rb")}
                r = requests.post(FACE_SWAP_API, files=files, timeout=60)
                if r.status_code == 200:
                    increment_generated()
                    out_path = os.path.join(GENERATED, f"{chat_id}_{int(time.time())}.jpg")
                    open(out_path, "wb").write(r.content)
                    tg_send_photo(token, chat_id, out_path, "✅ Swap complete!")
                    if load_settings().get("auto_delete"):
                        os.remove(out_path)
                else:
                    tg_send_message(token, chat_id, f"❌ Error swapping: {r.text}")
            except Exception as e:
                tg_send_message(token, chat_id, f"⚠️ Failed: {e}")
            finally:
                try: os.remove(file_path)
                except: pass
        else:
            # first image received
            json.dump({"path": file_path}, open(state_file, "w"))
            tg_send_message(token, chat_id, "📸 First image saved. Now send second image (the face to swap).")
        return "ok", 200

    # Deposit Credits
    if text.lower() in ["deposit", "add credit"]:
        s = load_settings()
        link = s.get("credit_deposit_link", CREDIT_DEPOSIT_LINK)
        msg = f"💳 Deposit credits here:\n{link}\n\nAfter deposit, send payment proof or transaction ID to admin."
        tg_send_message(token, chat_id, msg)
        return "ok", 200

    # Support message
    if text.lower().startswith("support"):
        support_text = text.replace("support", "").strip()
        if not support_text:
            tg_send_message(token, chat_id, "✍️ Please type your message after 'Support'. Example:\nSupport I have an issue with credits.")
        else:
            add_support(chat_id, user_name, support_text)
            tg_send_message(token, chat_id, "📨 Your message has been sent to the admin. You’ll get a reply soon!")
        return "ok", 200

    # Unknown message
    tg_send_message(token, chat_id, "❔ Unknown command. Type 'start' to see options again.")
    return "ok", 200


# --- Run server ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)