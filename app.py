"""
Hesap.com.tr 7/24 Çekiliş Kazanan Takip Botu (Render & Telegram)
===============================================================
- Tek dosya, sıfır karmaşa: Tüm modüller tek bir yerde birleştirilmiştir.
- Cloudflare TLS parmak izi korumasını curl_cffi ile tarayıcısız aşar.
- SADECE ve SADECE çekiliş kazanıldığında Telegram'a bildirim atar.
- Render Free planında 7/24 çalışır; cron-job ile /health veya /ping adresine ping atılabilir.
- Test modu: python app.py --test
"""

import os
import sys
import re
import json
import time
import html
import threading
from datetime import datetime

from dotenv import load_dotenv
import requests
import curl_cffi.requests as cffi_requests
import logging
from flask import Flask, jsonify, render_template_string, redirect, url_for, request

# Flask/Werkzeug HTTP istek log kirliliğini engelle (cron-job pingleri logu doldurmasın)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# UTF-8 Konsol Desteği
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# .env dosyasını yükle (varsa)
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# -------------------------------------------------------------
# YAPILANDIRMA (ENV / DOSYA)
# -------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

try:
    CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "60"))
    if CHECK_INTERVAL_MINUTES < 1:
        CHECK_INTERVAL_MINUTES = 1
except ValueError:
    CHECK_INTERVAL_MINUTES = 60

PORT = int(os.getenv("PORT", "10000"))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", os.getenv("APP_URL", "")).strip().rstrip("/")
ENABLE_SELF_PING = os.getenv("ENABLE_SELF_PING", "true").lower() in ("true", "1", "yes")

DATA_DIR = os.getenv("DATA_DIR", BASE_DIR)
CHECKED_DRAWS_FILE = os.path.join(DATA_DIR, "checked_draws.json")
WINS_FILE = os.path.join(DATA_DIR, "kazandiklarim.json")
USERNAMES_FILE = os.path.join(DATA_DIR, "usernames.txt")
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.txt")

BASE_URL = "https://hesap.com.tr"
ENDED_DRAWS_URL = f"{BASE_URL}/tamamlanan-cekilisler"
ACTIVE_DRAWS_URL = f"{BASE_URL}/cekilisler"


def get_tracked_usernames() -> list[str]:
    """Takip edilecek kullanıcı adlarını belirler."""
    usernames = set()

    # 1. USERNAMES Ortam Değişkeni (Render Dashboard için)
    env_users = os.getenv("USERNAMES", "").strip()
    if env_users:
        for u in env_users.split(","):
            u = u.strip().lower()
            if u:
                usernames.add(u)

    # 2. usernames.txt dosyası
    if os.path.exists(USERNAMES_FILE):
        try:
            with open(USERNAMES_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    u = line.strip().lower()
                    if u and not u.startswith("#"):
                        usernames.add(u)
        except Exception:
            pass

    # 3. accounts.txt dosyası (email:pass:user)
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = [p.strip() for p in line.split(":")]
                    if len(parts) >= 3 and parts[2]:
                        usernames.add(parts[2].lower())
                    elif len(parts) == 1 and "@" not in parts[0]:
                        usernames.add(parts[0].lower())
        except Exception:
            pass

    return sorted(list(usernames))


# -------------------------------------------------------------
# TELEGRAM BİLDİRİMİ (SADECE KAZANMA DURUMUNDA)
# -------------------------------------------------------------
def send_win_alert(win: dict) -> tuple[bool, str]:
    """Hesabınız çekiliş kazandığında Telegram'a anlık bildirim atar."""
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return False, "Telegram bilgileri eksik."

    title = html.escape(win.get("title", "Hesap.com.tr Çekilişi"))
    prize = html.escape(win.get("prize", "Belirtilmemiş"))
    username = html.escape(win.get("username", "Bilinmiyor"))
    draw_id = html.escape(str(win.get("draw_id", "")))
    draw_url = win.get("draw_url", f"https://hesap.com.tr/cekilis/{draw_id}")
    win_date = html.escape(win.get("win_date", datetime.now().strftime("%d.%m.%Y %H:%M")))

    msg = (
        "🎉 <b>TEBRİKLER! ÇEKİLİŞ KAZANDINIZ!</b> 🎉\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Kazanan Hesap:</b> <code>{username}</code>\n"
        f"🎁 <b>Ödül:</b> <b>{prize}</b>\n"
        f"🏷️ <b>Çekiliş:</b> {title}\n"
        f"🆔 <b>Çekiliş ID:</b> #{draw_id}\n"
        f"⏰ <b>Tarih:</b> {win_date}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <a href=\"{draw_url}\"><b>Çekiliş Sayfasına Git ve Ödülünü Al 👉</b></a>\n"
        "━━━━━━━━━━━━━━━━━━━━━━"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chat_ids = [c.strip() for c in TELEGRAM_CHAT_ID.split(",") if c.strip()]
    
    success = False
    for cid in chat_ids:
        try:
            res = requests.post(url, json={
                "chat_id": cid,
                "text": msg,
                "parse_mode": "HTML",
                "disable_web_page_preview": False
            }, timeout=10)
            if res.status_code == 200 and res.json().get("ok"):
                success = True
        except Exception as e:
            print(f"[!] Telegram istek hatası ({cid}): {e}")

    return success, "Tamamlandı"


# -------------------------------------------------------------
# ÇEKİLİŞ KONTROL MOTORU (CLOUDFLARE BYPASS TLS)
# -------------------------------------------------------------
STATE_LOCK = threading.Lock()
CHECK_LOCK = threading.Lock()
BOT_STATE = {
    "is_checking": False,
    "last_check_time": None,
    "last_status": "Henüz kontrol yapılmadı",
    "total_checks": 0,
    "total_wins_recorded": 0,
    "recent_wins": [],
    "tracked_accounts": []
}


def get_client() -> cffi_requests.Session:
    """Chrome TLS parmak izi ile Cloudflare aşan oturum."""
    return cffi_requests.Session(impersonate="chrome124")


def load_checked_draws() -> set[str]:
    """Taranmış çekiliş listesi."""
    if not os.path.exists(CHECKED_DRAWS_FILE):
        return set()
    try:
        with open(CHECKED_DRAWS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_checked_draws(checked_set: set[str]):
    """Taranmış çekiliş listesini kaydeder."""
    try:
        data = sorted(list(checked_set))
        if len(data) > 1500:
            data = data[-1500:]
        with open(CHECKED_DRAWS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[!] checked_draws.json kayıt hatası: {e}")


def load_past_wins() -> list[dict]:
    """Kazanılan çekilişler listesi."""
    if not os.path.exists(WINS_FILE):
        return []
    try:
        with open(WINS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def record_win(win_info: dict):
    """Yeni kazancı kazandiklarim.json dosyasına ekler."""
    past = load_past_wins()
    if not any(w.get("draw_id") == win_info.get("draw_id") and w.get("username", "").lower() == win_info.get("username", "").lower() for w in past):
        past.append(win_info)
        try:
            with open(WINS_FILE, "w", encoding="utf-8") as f:
                json.dump(past, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[!] kazandiklarim.json kayıt hatası: {e}")


def parse_draw_page(client: cffi_requests.Session, draw_url: str) -> tuple[str, str, list[str]]:
    """Çekiliş sayfasından başlık, ödül ve kazanan kullanıcıları ayıklar."""
    try:
        r = client.get(draw_url, timeout=12)
        if r.status_code != 200:
            return "", "", []

        soup = BeautifulSoup(r.text, "html.parser")

        # Başlık
        title = ""
        t_el = soup.find("h1") or soup.find(class_=lambda c: c and "title" in c.lower())
        if t_el:
            title = t_el.get_text(strip=True)
        elif soup.title:
            title = soup.title.string.split("-")[0].strip()

        # Ödül
        prize = ""
        p_el = soup.find(class_="price") or soup.find(class_=lambda c: c and "prize" in c.lower())
        if p_el:
            prize = p_el.get_text(strip=True)

        # Kazananlar
        winners = []
        cards = soup.find_all(class_=lambda c: c and "winner" in c.lower())
        for card in cards:
            text = card.get_text(strip=True, separator=" ")
            m = re.search(r'kazanan\s*[:\|\-]?\s*([a-zA-Z0-9_\.-]+)', text, re.IGNORECASE)
            if m:
                u = m.group(1).lower()
                if u != "badge" and u not in winners:
                    winners.append(u)

        if not winners:
            badges = soup.find_all(class_="gwd-winner-badge")
            for b in badges:
                parts = b.parent.get_text(strip=True, separator=" ").replace("KAZANAN", "").strip().split()
                if parts and parts[0].lower() not in winners:
                    winners.append(parts[0].lower())

        return title, prize, winners
    except Exception:
        return "", "", []


def run_check_cycle(notify_telegram: bool = True) -> tuple[list[dict], str]:
    """Çekilişleri tarar, kazanç varsa Telegram'a iletir."""
    global BOT_STATE

    tracked_users = get_tracked_usernames()
    if not tracked_users:
        msg = "Takip edilecek kullanıcı adı bulunamadı!"
        with STATE_LOCK:
            BOT_STATE["last_status"] = msg
        return [], msg

    with STATE_LOCK:
        BOT_STATE["is_checking"] = True
        BOT_STATE["tracked_accounts"] = tracked_users

    start_ts = datetime.now()
    checked_draws = load_checked_draws()
    client = get_client()

    draw_links = []
    for page_url in (ENDED_DRAWS_URL, ACTIVE_DRAWS_URL):
        try:
            r = client.get(page_url, timeout=12)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if "/cekilis/" in href:
                        d_url = href if href.startswith("http") else f"{BASE_URL}{href}"
                        m = re.search(r'/cekilis/(\d+)', d_url)
                        if m:
                            d_id = m.group(1)
                            if (d_id, d_url) not in draw_links:
                                draw_links.append((d_id, d_url))
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [!] HATA: {page_url} yanıt kodu: {r.status_code}")
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [!] HATA: Çekiliş sayfası okunamadı ({page_url}): {e}")

    new_wins = []
    scanned_count = 0

    for draw_id, draw_url in draw_links:
        if draw_id in checked_draws:
            continue

        scanned_count += 1
        title, prize, winners = parse_draw_page(client, draw_url)
        time.sleep(0.2)

        # Henüz kazananlar belirlenmemişse bu çekilişi sonra tekrar taramak için geç
        if not winners:
            continue

        checked_draws.add(draw_id)

        for winner in winners:
            if winner in tracked_users:
                win_data = {
                    "draw_id": draw_id,
                    "draw_url": draw_url,
                    "title": title or f"Çekiliş #{draw_id}",
                    "prize": prize or "Ödül Detayı Sayfada",
                    "username": winner,
                    "win_date": datetime.now().strftime("%d.%m.%Y %H:%M")
                }
                new_wins.append(win_data)
                record_win(win_data)

                # SADECE VE SADECE ÇEKİLİŞ KAZANILDIĞINDA TELEGRAM BİLDİRİMİ AT
                if notify_telegram:
                    send_win_alert(win_data)

    save_checked_draws(checked_draws)
    all_past_wins = load_past_wins()
    now_str = datetime.now().strftime("%H:%M:%S")

    with STATE_LOCK:
        BOT_STATE["is_checking"] = False
        BOT_STATE["last_check_time"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        BOT_STATE["last_status"] = f"Aktif ({len(draw_links)} çekiliş izleniyor, {scanned_count} yeni incelendi)"
        BOT_STATE["total_checks"] += 1
        BOT_STATE["total_wins_recorded"] = len(all_past_wins)
        BOT_STATE["recent_wins"] = all_past_wins[-15:][::-1]

    # Sade ve net konsol çıktısı
    if new_wins:
        for w in new_wins:
            print(f"[{now_str}] [🏆 KAZANÇ] {w['username'].upper()} kazandı: {w['title']} ({w['prize']})")
    else:
        print(f"[{now_str}] [OK] Aktif: {len(draw_links)} çekiliş taranıyor | Yeni kazanç: 0")

    return new_wins, BOT_STATE["last_status"]


# -------------------------------------------------------------
# FLASK WEB SUNUCUSU VE DASHBOARD
# -------------------------------------------------------------
app = Flask(__name__)
START_TIME = datetime.now()

HTML_DASHBOARD = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hesap.com.tr Kazanan Botu - 7/24 Aktif</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0b0f19;
            --card: rgba(23, 31, 51, 0.75);
            --border: rgba(255, 255, 255, 0.08);
            --primary: #4f46e5;
            --accent: #06b6d4;
            --gold: #fbbf24;
            --text: #f8fafc;
            --muted: #94a3b8;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
        body {
            background-color: var(--bg);
            background-image: radial-gradient(at 0% 0%, rgba(79, 70, 229, 0.15) 0px, transparent 50%),
                              radial-gradient(at 100% 100%, rgba(6, 182, 212, 0.12) 0px, transparent 50%);
            color: var(--text);
            min-height: 100vh;
            padding: 2rem 1rem;
        }
        .container { max-width: 980px; margin: 0 auto; }
        header {
            display: flex; justify-content: space-between; align-items: center;
            padding-bottom: 1.5rem; margin-bottom: 2rem; border-bottom: 1px solid var(--border);
        }
        .badge {
            background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3);
            padding: 0.4rem 0.8rem; border-radius: 99px; font-size: 0.85rem; font-weight: 600;
        }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }
        .card {
            background: var(--card); backdrop-filter: blur(10px); border: 1px solid var(--border);
            border-radius: 14px; padding: 1.25rem;
        }
        .card-num { font-size: 1.8rem; font-weight: 800; margin-top: 0.3rem; }
        .card-label { font-size: 0.8rem; color: var(--muted); text-transform: uppercase; font-weight: 600; }
        .btn {
            background: var(--primary); color: white; padding: 0.7rem 1.2rem; border-radius: 8px;
            text-decoration: none; font-weight: 600; font-size: 0.85rem; display: inline-block;
        }
        .btn:hover { opacity: 0.9; }
        .tag {
            background: rgba(79, 70, 229, 0.15); border: 1px solid rgba(79, 70, 229, 0.3);
            color: #a5b4fc; padding: 0.3rem 0.7rem; border-radius: 6px; font-size: 0.85rem; display: inline-block; margin: 0.2rem;
        }
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td { padding: 0.8rem; text-align: left; border-bottom: 1px solid var(--border); font-size: 0.9rem; }
        th { color: var(--muted); font-size: 0.75rem; text-transform: uppercase; }
        .win-pill { background: rgba(251, 191, 36, 0.2); color: var(--gold); padding: 0.2rem 0.5rem; border-radius: 4px; font-weight: 700; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1 style="font-size: 1.4rem;">🎁 Hesap.com.tr Kazanan Botu</h1>
                <p style="color: var(--muted); font-size: 0.85rem;">Render 7/24 Bulut Takip & Telegram Bildirim Sistemi</p>
            </div>
            <div class="badge">● 7/24 Canlı & Aktif</div>
        </header>

        <div class="stats">
            <div class="card">
                <div class="card-label">Kazanılan Çekiliş</div>
                <div class="card-num" style="color: var(--gold);">{{ state.total_wins_recorded }}</div>
            </div>
            <div class="card">
                <div class="card-label">Takip Edilen Hesap</div>
                <div class="card-num">{{ state.tracked_accounts|length }}</div>
            </div>
            <div class="card">
                <div class="card-label">Taranan Çekiliş</div>
                <div class="card-num">{{ total_checked }}</div>
            </div>
            <div class="card">
                <div class="card-label">Son Kontrol</div>
                <div class="card-num" style="font-size: 1.1rem; line-height: 2.3rem;">{{ state.last_check_time or 'Bekleniyor...' }}</div>
            </div>
        </div>

        <div style="margin-bottom: 1.5rem;">
            <a href="/trigger-check" class="btn">⚡ Şimdi Kontrol Et</a>
            <a href="/health" target="_blank" class="btn" style="background: rgba(255,255,255,0.08); margin-left: 0.5rem;">🩺 /health Ping</a>
        </div>

        <div class="card" style="margin-bottom: 1.5rem;">
            <div style="font-weight: 700; margin-bottom: 0.8rem;">👥 Takip Edilen Hesaplar</div>
            <div>
                {% for u in state.tracked_accounts %}
                <span class="tag">@{{ u }}</span>
                {% endfor %}
            </div>
        </div>

        <div class="card">
            <div style="font-weight: 700; margin-bottom: 0.8rem;">🏆 Son Kazanılan Çekilişler</div>
            {% if state.recent_wins %}
            <table>
                <thead>
                    <tr><th>HESAP</th><th>ÖDÜL</th><th>ÇEKİLİŞ</th><th>TARİH</th><th>LİNK</th></tr>
                </thead>
                <tbody>
                    {% for w in state.recent_wins %}
                    <tr>
                        <td><span class="win-pill">{{ w.username|upper }}</span></td>
                        <td style="color: #34d399; font-weight: 700;">{{ w.prize }}</td>
                        <td>{{ w.title }}</td>
                        <td style="color: var(--muted);">{{ w.win_date }}</td>
                        <td><a href="{{ w.draw_url }}" target="_blank" style="color: var(--accent); text-decoration: none;">Git &rsaquo;</a></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <div style="color: var(--muted); padding: 1.5rem 0; font-size: 0.9rem;">Henüz kayıtlı çekiliş ödülü bulunamadı. 7/24 taranıyor...</div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""


@app.route("/")
def index():
    state = dict(BOT_STATE)
    return render_template_string(HTML_DASHBOARD, state=state, total_checked=len(load_checked_draws()))


@app.route("/health")
@app.route("/ping")
@app.route("/cron")
def health():
    """Render Free planı uyutmamak ve cron-job.org için ping uç noktası."""
    state = dict(BOT_STATE)
    return jsonify({
        "status": "ok",
        "service": "hesapcom-kazanan-bot",
        "uptime_sec": int((datetime.now() - START_TIME).total_seconds()),
        "last_check": state["last_check_time"],
        "total_checks": state["total_checks"],
        "wins": state["total_wins_recorded"]
    }), 200


@app.route("/trigger-check")
def trigger_check():
    threading.Thread(target=lambda: run_check_cycle(notify_telegram=True), daemon=True).start()
    return redirect(url_for("index"))


# -------------------------------------------------------------
# ARKA PLAN ÇALIŞTIRICILARI
# -------------------------------------------------------------
def background_checker():
    """Belirlenen aralıklarla arka planda çekilişleri tarar."""
    now_str = datetime.now().strftime("%H:%M:%S")
    tracked = get_tracked_usernames()
    print(f"[{now_str}] [BAŞLATILDI] Sistem aktif: {len(tracked)} hesap takip ediliyor | Kontrol: her {CHECK_INTERVAL_MINUTES} dk")

    # İlk kontrolü yap
    try:
        run_check_cycle(notify_telegram=True)
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [!] HATA: İlk taramada hata: {e}")

    while True:
        try:
            time.sleep(CHECK_INTERVAL_MINUTES * 60)
            with CHECK_LOCK:
                run_check_cycle(notify_telegram=True)
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [!] HATA: Tarama döngüsü hatası: {e}")
            time.sleep(10)


def background_self_ping():
    """Render'ın uykuya geçmesini önlemek için sessiz periyodik self-ping."""
    if not (ENABLE_SELF_PING and RENDER_EXTERNAL_URL):
        return

    time.sleep(30)
    while True:
        try:
            time.sleep(600)  # 10 dakikada bir
            requests.get(f"{RENDER_EXTERNAL_URL}/health", timeout=10)
        except Exception:
            pass


# -------------------------------------------------------------
# BAŞLATMA VE TEST MODU
# -------------------------------------------------------------
def run_cli_test():
    """python app.py --test komutuyla çalışan hızlı teşhis testi."""
    print("=" * 65)
    print("       HESAP.COM.TR KAZANAN BOTU - SİSTEM VE BAĞLANTI TESTİ")
    print("=" * 65)

    tracked = get_tracked_usernames()
    print(f"\n[1/4] Takip Edilen Hesaplar ({len(tracked)}): {', '.join(tracked)}")

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        masked = TELEGRAM_BOT_TOKEN[:6] + "..." + TELEGRAM_BOT_TOKEN[-4:]
        print(f"[2/4] Telegram Bot Bilgisi: Token={masked} | Chat ID={TELEGRAM_CHAT_ID}")
        print("      (Kural: SADECE çekiliş kazanıldığında bildirim gider.)")
    else:
        print("[2/4] [!] Telegram token veya Chat ID tanımlanmamış!")

    print("[3/4] Hesap.com.tr Cloudflare TLS Testi...")
    client = get_client()
    r = client.get(ENDED_DRAWS_URL, timeout=12)
    print(f"      Sayfa Durumu: {r.status_code} OK ({len(r.text)} bayt)")

    print("[4/4] Çekiliş Tarama Testi...")
    wins, summary = run_check_cycle(notify_telegram=True)
    print(f"      {summary}")
    print("\n[+] TEST TAMAMLANDI! Sistem Render için hazır.")


if __name__ == "__main__":
    if "--test" in sys.argv:
        run_cli_test()
    else:
        threading.Thread(target=background_checker, daemon=True).start()
        threading.Thread(target=background_self_ping, daemon=True).start()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [OK] Web servisi dinleniyor: 0.0.0.0:{PORT}")
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
