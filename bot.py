import os, requests, json

TOKEN_FILE = "bot_token.txt"

# --- Save / read token ---
def write_token(token):
    with open(TOKEN_FILE, "w") as f:
        f.write(token.strip())

def read_token():
    if not os.path.exists(TOKEN_FILE):
        return ""
    return open(TOKEN_FILE).read().strip()

# --- Validate token ---
def validate_token(token):
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        data = r.json()
        if data.get("ok"):
            return True, data["result"]
        else:
            return False, data.get("description", "Invalid")
    except Exception as e:
        return False, str(e)

# --- Set webhook ---
def set_webhook(token, url):
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/setWebhook", params={"url": url})
        data = r.json()
        return data.get("ok"), data
    except Exception as e:
        return False, str(e)

# --- Telegram send functions ---
def tg_send_message(token, chat_id, text):
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        return r.status_code == 200, r.text
    except Exception as e:
        return False, str(e)

def tg_send_photo(token, chat_id, photo_path, caption=None):
    try:
        files = {"photo": open(photo_path, "rb")}
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
        r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", data=data, files=files)
        return r.status_code == 200, r.text
    except Exception as e:
        return False, str(e)

def tg_download_file(token, file_id):
    try:
        # get file path
        r = requests.get(f"https://api.telegram.org/bot{token}/getFile", params={"file_id": file_id})
        file_path = r.json()["result"]["file_path"]
        url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        out_path = f"download_{file_id.split('/')[-1]}.jpg"
        open(out_path, "wb").write(requests.get(url).content)
        return out_path
    except Exception as e:
        print("Download error:", e)
        return None