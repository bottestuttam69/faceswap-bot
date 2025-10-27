from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for, send_file
import json
import os
import requests
import threading
from datetime import datetime
from bot import handle_update # Import the handler from bot.py

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- JSON Database Functions ---
def load_json(filename):
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {} if filename != 'support.json' else []
    return {} if filename != 'support.json' else []

def save_json(data, filename):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

# --- Authentication ---
@app.before_request
def check_login():
    if 'logged_in' not in session and request.endpoint not in ['login', 'static']:
        return redirect(url_for('login'))

# --- Routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        config = load_json('config.json')
        admin_id = config.get('admin_id', 'Palak123@@')
        admin_pass = config.get('admin_pass', 'Palak123@@')
        if request.form['username'] == admin_id and request.form['password'] == admin_pass:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            return render_template_string(LOGIN_TEMPLATE, error="Invalid credentials")
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/')
def dashboard():
    config = load_json('config.json')
    users = load_json('users.json')
    stats = load_json('stats.json')
    support_messages = load_json('support.json')

    # Uptime calculation
    start_time_str = stats.get('start_time')
    uptime = "N/A"
    if start_time_str:
        start_time = datetime.fromisoformat(start_time_str)
        delta = datetime.now() - start_time
        days, remainder = divmod(delta.total_seconds(), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime = f"{int(days)}d {int(hours)}h {int(minutes)}m"

    return render_template_string(
        DASHBOARD_TEMPLATE,
        config=config,
        users=users,
        stats=stats,
        support_messages=support_messages,
        total_users=len(users),
        uptime=uptime
    )

@app.route('/api/connect_bot', methods=['POST'])
def connect_bot():
    token = request.json.get('token')
    if not token:
        return jsonify({'status': 'error', 'message': 'Token is required'}), 400

    # Validate token
    test_url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        res = requests.get(test_url)
        if res.status_code != 200:
            return jsonify({'status': 'error', 'message': 'Invalid Bot Token'}), 400
    except requests.RequestException:
        return jsonify({'status': 'error', 'message': 'Failed to connect to Telegram API'}), 500

    # Get Replit URL
    repl_url = f"https://{request.host}"
    webhook_url = f"{repl_url}/webhook"
    
    # Set Webhook
    set_webhook_url = f"https://api.telegram.org/bot{token}/setWebhook?url={webhook_url}"
    try:
        res = requests.get(set_webhook_url)
        if res.status_code == 200:
            config = load_json('config.json')
            config['bot_token'] = token
            save_json(config, 'config.json')
            # Set bot start time for uptime calculation
            stats = load_json('stats.json')
            stats['start_time'] = datetime.now().isoformat()
            save_json(stats, 'stats.json')
            return jsonify({'status': 'success', 'message': 'Bot connected and webhook set successfully!'})
        else:
            return jsonify({'status': 'error', 'message': f'Failed to set webhook: {res.text}'}), 500
    except requests.RequestException as e:
        return jsonify({'status': 'error', 'message': f'Webhook connection error: {e}'}), 500

@app.route('/api/save_settings', methods=['POST'])
def save_settings():
    settings = request.json
    config = load_json('config.json')
    
    # Update only the fields present in the request
    for key, value in settings.items():
        # Handle boolean toggles
        if key in ['maintenance_mode', 'earning_mode']:
            config[key] = (value == 'true' or value is True)
        else:
            config[key] = value

    save_json(config, 'config.json')
    return jsonify({'status': 'success', 'message': 'Settings saved!'})

@app.route('/api/user_action', methods=['POST'])
def user_action():
    data = request.json
    user_id = str(data.get('user_id'))
    action = data.get('action')
    users = load_json('users.json')

    if user_id not in users:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404

    if action == 'ban':
        users[user_id]['is_banned'] = True
    elif action == 'unban':
        users[user_id]['is_banned'] = False
    elif action == 'update_balance':
        amount = int(data.get('amount', 0))
        users[user_id]['balance'] += amount
    
    save_json(users, 'users.json')
    return jsonify({'status': 'success', 'message': f'User {action} successful.', 'new_balance': users[user_id].get('balance')})


@app.route('/api/broadcast', methods=['POST'])
def broadcast():
    data = request.json
    message_text = data.get('message')
    target_user = data.get('target_user') # 'all' or a specific user_id
    users = load_json('users.json')
    config = load_json('config.json')
    token = config.get('bot_token')
    
    if not token:
        return jsonify({'status': 'error', 'message': 'Bot not connected.'}), 400

    target_ids = []
    if target_user == 'all':
        target_ids = list(users.keys())
    elif target_user in users:
        target_ids.append(target_user)
    
    success_count = 0
    fail_count = 0
    
    for user_id in target_ids:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {'chat_id': user_id, 'text': message_text, 'parse_mode': 'Markdown'}
        try:
            res = requests.post(url, json=payload)
            if res.json().get('ok'):
                success_count += 1
            else:
                fail_count += 1
        except Exception:
            fail_count += 1

    return jsonify({
        'status': 'success', 
        'message': 'Broadcast complete.',
        'summary': f'Sent to {success_count} users. Failed for {fail_count} users.'
    })


@app.route('/api/reply_support', methods=['POST'])
def reply_support():
    data = request.json
    user_id = data.get('user_id')
    reply_text = data.get('reply')
    timestamp = data.get('timestamp')
    
    config = load_json('config.json')
    token = config.get('bot_token')
    if not token:
        return jsonify({'status': 'error', 'message': 'Bot not connected.'}), 400
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {'chat_id': user_id, 'text': f"✉️ **Reply from Support:**\n\n{reply_text}", 'parse_mode': 'Markdown'}
    res = requests.post(url, json=payload)

    if res.json().get('ok'):
        # Mark message as replied
        support_messages = load_json('support.json')
        for msg in support_messages:
            if str(msg['user_id']) == str(user_id) and msg['timestamp'] == timestamp:
                msg['status'] = 'replied'
                break
        save_json(support_messages, 'support.json')
        return jsonify({'status': 'success', 'message': 'Reply sent!'})
    else:
        return jsonify({'status': 'error', 'message': f'Failed to send reply: {res.json().get("description")}'}), 500


@app.route('/download/<filename>')
def download_file(filename):
    if filename in ['users.json', 'config.json', 'support.json', 'stats.json']:
        return send_file(filename, as_attachment=True)
    return "File not found", 404

# --- Webhook for Telegram Bot ---
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.is_json:
        update = request.get_json()
        # Use threading to handle updates asynchronously to avoid timeouts
        threading.Thread(target=handle_update, args=(update,)).start()
    return jsonify({'status': 'ok'})

# --- HTML & CSS Templates ---
LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Login</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Poppins', sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: #fff; }
        .login-container { background: rgba(255, 255, 255, 0.1); backdrop-filter: blur(10px); padding: 40px; border-radius: 15px; box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37); text-align: center; }
        h2 { margin-bottom: 20px; }
        input { width: 100%; padding: 10px; margin-bottom: 15px; border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.3); background: rgba(255, 255, 255, 0.2); color: #fff; font-size: 16px; }
        input::placeholder { color: #eee; }
        button { width: 100%; padding: 12px; border: none; border-radius: 8px; background-color: #8e44ad; color: white; cursor: pointer; font-size: 16px; transition: background-color 0.3s; }
        button:hover { background-color: #9b59b6; }
        .error { color: #ffcccc; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="login-container">
        <h2>Admin Panel Login</h2>
        <form method="post">
            <input type="text" name="username" placeholder="Admin ID" required>
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Login</button>
        </form>
        {% if error %}
            <p class="error">{{ error }}</p>
        {% endif %}
    </div>
</body>
</html>
"""

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FaceSwap Bot Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-grad: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            --card-bg: rgba(255, 255, 255, 0.1);
            --text-color: #f0f0f0;
            --header-color: #ffffff;
            --border-color: rgba(255, 255, 255, 0.2);
            --shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
            --blur: 10px;
            --primary-btn: #8e44ad;
            --primary-btn-hover: #9b59b6;
            --danger-btn: #c0392b;
            --success-btn: #27ae60;
        }
        body { font-family: 'Poppins', sans-serif; background: var(--bg-grad); color: var(--text-color); margin: 0; padding: 20px; }
        .dashboard { max-width: 1200px; margin: auto; }
        .header { text-align: center; margin-bottom: 30px; }
        .header h1 { font-weight: 600; color: var(--header-color); }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .card { background: var(--card-bg); backdrop-filter: blur(var(--blur)); -webkit-backdrop-filter: blur(var(--blur)); border-radius: 15px; padding: 25px; box-shadow: var(--shadow); border: 1px solid var(--border-color); }
        .card h3 { margin-top: 0; border-bottom: 1px solid var(--border-color); padding-bottom: 10px; font-weight: 500; }
        .form-group { margin-bottom: 15px; }
        .form-group label { display: block; margin-bottom: 5px; font-weight: 400; }
        .form-group input, .form-group textarea { width: calc(100% - 20px); padding: 10px; border-radius: 8px; border: 1px solid var(--border-color); background: rgba(0,0,0,0.2); color: var(--text-color); font-size: 14px; }
        .btn { padding: 10px 15px; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; transition: all 0.3s; font-weight: 500; }
        .btn-primary { background: var(--primary-btn); color: white; }
        .btn-primary:hover { background: var(--primary-btn-hover); }
        .btn-danger { background: var(--danger-btn); color: white; }
        .btn-success { background: var(--success-btn); color: white; }
        .status { font-weight: 600; }
        .status.connected { color: #2ecc71; }
        .status.not-connected { color: #e74c3c; }
        .user-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        .user-table th, .user-table td { padding: 10px; text-align: left; border-bottom: 1px solid var(--border-color); }
        .user-table th { font-weight: 600; }
        .user-actions .btn { margin-right: 5px; }
        .toggle-switch { position: relative; display: inline-block; width: 50px; height: 26px; }
        .toggle-switch input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #ccc; transition: .4s; border-radius: 34px; }
        .slider:before { position: absolute; content: ""; height: 18px; width: 18px; left: 4px; bottom: 4px; background-color: white; transition: .4s; border-radius: 50%; }
        input:checked + .slider { background-color: #27ae60; }
        input:checked + .slider:before { transform: translateX(24px); }
        .support-message { border-left: 3px solid var(--primary-btn); padding-left: 15px; margin-bottom: 15px; }
        .logout-btn { position: absolute; top: 20px; right: 20px; }
    </style>
</head>
<body>
    <a href="/logout" class="btn btn-danger logout-btn">Logout</a>
    <div class="dashboard">
        <div class="header"><h1>🤖 FaceSwap Bot Admin Panel</h1></div>
        
        <div class="grid">
            <!-- BOT CONNECTION -->
            <div class="card">
                <h3>🔌 Bot Connection</h3>
                <div class="form-group">
                    <label for="bot-token">Enter Bot Token</label>
                    <input type="text" id="bot-token" placeholder="Your Telegram Bot Token">
                </div>
                <button class="btn btn-primary" onclick="connectBot()">Connect Bot</button>
                <p>Status: <span id="bot-status" class="status {{ 'connected' if config.bot_token else 'not-connected' }}">{{ '✅ Connected' if config.bot_token else '❌ Not Connected' }}</span></p>
                <p id="connect-message"></p>
            </div>

            <!-- SETTINGS -->
            <div class="card">
                <h3>⚙️ Bot Settings</h3>
                <form id="settings-form">
                    <div class="form-group"><label>Bot Name:</label><input type="text" name="bot_name" value="{{ config.bot_name }}"></div>
                    <div class="form-group"><label>Announcement Channel:</label><input type="text" name="announcement_channel" value="{{ config.announcement_channel }}"></div>
                    <div class="form-group"><label>Deposit Link:</label><input type="text" name="deposit_link" value="{{ config.deposit_link }}"></div>
                    <div class="form-group"><label>Face API URL:</label><input type="text" name="face_api_url" value="{{ config.face_api_url }}"></div>
                    <div class="form-group"><label>Credits per Swap:</label><input type="number" name="credits_per_swap" value="{{ config.credits_per_swap }}"></div>
                    <div class="form-group"><label>INR per USDT:</label><input type="number" name="inr_per_usdt" value="{{ config.inr_per_usdt }}"></div>
                    <div class="form-group" style="display:flex; align-items:center; justify-content: space-between;">
                        <label>Earning Mode:</label>
                        <label class="toggle-switch"><input type="checkbox" name="earning_mode" {{ 'checked' if config.earning_mode else '' }}><span class="slider"></span></label>
                    </div>
                    <button type="button" class="btn btn-primary" onclick="saveSettings()">Save Settings</button>
                </form>
            </div>

            <!-- STATS & MAINTENANCE -->
            <div class="card">
                <h3>📊 Stats & Maintenance</h3>
                <p><strong>Total Users:</strong> {{ total_users }}</p>
                <p><strong>Total Swaps:</strong> {{ stats.total_swaps | default(0) }}</p>
                <p><strong>Generated Files:</strong> {{ stats.generated_files | default(0) }}</p>
                <p><strong>Bot Uptime:</strong> {{ uptime }}</p>
                <div class="form-group" style="display:flex; align-items:center; justify-content: space-between;">
                    <label>Maintenance Mode:</label>
                    <label class="toggle-switch"><input type="checkbox" id="maintenance-mode" {{ 'checked' if config.maintenance_mode else '' }} onchange="toggleMaintenance()"><span class="slider"></span></label>
                </div>
                 <a href="/download/users.json" class="btn btn-success">Download User DB</a>
            </div>

            <!-- BROADCAST -->
            <div class="card">
                <h3>📣 Broadcast Message</h3>
                <div class="form-group">
                    <label for="broadcast-message">Message (Markdown supported):</label>
                    <textarea id="broadcast-message" rows="4"></textarea>
                </div>
                 <div class="form-group">
                    <label for="broadcast-target">Target:</label>
                    <select id="broadcast-target" class="form-group input">
                        <option value="all">All Users</option>
                        {% for id, user in users.items() %}
                        <option value="{{ id }}">{{ user.first_name }} (@{{ user.username }})</option>
                        {% endfor %}
                    </select>
                </div>
                <button class="btn btn-primary" onclick="sendBroadcast()">Send Broadcast</button>
                <p id="broadcast-summary"></p>
            </div>

            <!-- USERS -->
            <div class="card" style="grid-column: 1 / -1;">
                <h3>👥 Users</h3>
                <div style="max-height: 400px; overflow-y: auto;">
                    <table class="user-table">
                        <thead><tr><th>Name</th><th>Username</th><th>ID</th><th>Balance</th><th>Actions</th></tr></thead>
                        <tbody>
                            {% for id, user in users.items() %}
                            <tr id="user-row-{{ id }}">
                                <td>{{ user.first_name }}</td>
                                <td>@{{ user.username }}</td>
                                <td>{{ id }}</td>
                                <td id="balance-{{ id }}">{{ user.balance }}</td>
                                <td class="user-actions">
                                    {% if user.is_banned %}
                                    <button class="btn btn-success" onclick="userAction('{{ id }}', 'unban')">Unban</button>
                                    {% else %}
                                    <button class="btn btn-danger" onclick="userAction('{{ id }}', 'ban')">Ban</button>
                                    {% endif %}
                                    <input type="number" id="balance-input-{{ id }}" placeholder="Amount" style="width: 70px; padding: 5px;">
                                    <button class="btn" onclick="userAction('{{ id }}', 'update_balance', 'add')">+</button>
                                    <button class="btn" onclick="userAction('{{ id }}', 'update_balance', 'deduct')">-</button>
                 </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
            
            <!-- SUPPORT -->
            <div class="card" style="grid-column: 1 / -1;">
                <h3>💬 Support Messages</h3>
                <div style="max-height: 400px; overflow-y: auto;">
                {% for msg in support_messages | reverse %}
                    <div class="support-message" id="msg-{{ msg.timestamp }}">
                        <p><strong>From:</strong> {{ msg.first_name }} (@{{ msg.username }}) - {{ msg.user_id }}</p>
                        <p><strong>Message:</strong> {{ msg.message }}</p>
                        <p><strong>Status:</strong> <span id="status-{{ msg.timestamp }}">{{ msg.status }}</span></p>
                        {% if msg.status == 'open' %}
                        <div id="reply-form-{{ msg.timestamp }}">
                           <textarea id="reply-text-{{ msg.timestamp }}" rows="2" placeholder="Type your reply..."></textarea>
                           <button class="btn btn-primary" onclick="replySupport('{{ msg.user_id }}', '{{ msg.timestamp }}')">Reply</button>
                        </div>
                        {% endif %}
                    </div>
                {% endfor %}
                </div>
            </div>
        </div>
    </div>

    <script>
        async function apiCall(endpoint, data) {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            });
            return response.json();
        }

        async function connectBot() {
            const token = document.getElementById('bot-token').value;
            const messageEl = document.getElementById('connect-message');
            const statusEl = document.getElementById('bot-status');
            
            const result = await apiCall('/api/connect_bot', { token });
            messageEl.textContent = result.message;
            if (result.status === 'success') {
                statusEl.textContent = '✅ Connected';
                statusEl.className = 'status connected';
                setTimeout(() => location.reload(), 1500);
            } else {
                 statusEl.textContent = '❌ Not Connected';
                 statusEl.className = 'status not-connected';
            }
        }

        async function saveSettings() {
            const form = document.getElementById('settings-form');
            const formData = new FormData(form);
            const data = {};
            formData.forEach((value, key) => {
                // Handle checkboxes separately for boolean value
                if (form.elements[key].type === 'checkbox') {
                    data[key] = form.elements[key].checked;
                } else {
                    data[key] = value;
                }
            });
            const result = await apiCall('/api/save_settings', data);
            alert(result.message);
        }

        async function toggleMaintenance() {
            const isChecked = document.getElementById('maintenance-mode').checked;
            const result = await apiCall('/api/save_settings', { maintenance_mode: isChecked });
            alert(result.message);
        }

        async function userAction(userId, action, type) {
            let payload = { user_id: userId, action: action };
            if (action === 'update_balance') {
                let amount = parseInt(document.getElementById(`balance-input-${userId}`).value);
                if (isNaN(amount)) { alert('Please enter a valid amount.'); return; }
                if (type === 'deduct') amount = -amount;
                payload.amount = amount;
            }
            const result = await apiCall('/api/user_action', payload);
            alert(result.message);
            if (result.status === 'success') {
                if (result.new_balance !== undefined) {
                    document.getElementById(`balance-${userId}`).textContent = result.new_balance;
                } else {
                    location.reload(); // Reload to show ban/unban status change
                }
            }
        }

        async function sendBroadcast() {
            const message = document.getElementById('broadcast-message').value;
            const target = document.getElementById('broadcast-target').value;
            const result = await apiCall('/api/broadcast', { message, target_user: target });
            document.getElementById('broadcast-summary').textContent = result.summary;
        }
        
        async function replySupport(userId, timestamp) {
            const replyText = document.getElementById(`reply-text-${timestamp}`).value;
            if (!replyText) { alert('Reply cannot be empty.'); return; }
            
            const result = await apiCall('/api/reply_support', { user_id: userId, reply: replyText, timestamp: timestamp });
            alert(result.message);

            if (result.status === 'success') {
                document.getElementById(`status-${timestamp}`).textContent = 'replied';
                document.getElementById(`reply-form-${timestamp}`).style.display = 'none';
            }
        }
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    # Initialize stats file on first run
    if not os.path.exists('stats.json'):
        save_json({
            "total_swaps": 0,
            "generated_files": 0,
            "last_activity": None,
            "start_time": None
        }, 'stats.json')
    app.run(host='0.0.0.0', port=8080)
