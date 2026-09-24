"""
Hesap.com.tr 7/24 Çekiliş Kazanan Takip Botu (Render & Telegram)
===============================================================
- UI/HTML yok: Saf ve ultra hafif arka plan motoru.
- Render Free planında 7/24 çalışır (cron-job pingleri için / veya /health 'OK' döner).
- SADECE ve SADECE çekiliş kazanıldığında Telegram'a bildirim atar.
- Test için: python app.py --test
"""

import os
import sys
import re
import json
import time
import html
import threading
import logging
from datetime import datetime

from dotenv import load_dotenv
import requests
import curl_cffi.requests as cffi_requests
from bs4 import BeautifulSoup
from flask import Flask

# Ping isteklerinin konsolu kirletmesini engelle
logging.getLogger("werkzeug").setLevel(logging.ERROR)

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# -------------------------------------------------------------
# YAPILANDIRMA
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
CHECKED_DRAWS_FILE = os.path.join(BASE_DIR, "checked_draws.json")
WINS_FILE = os.path.join(BASE_DIR, "kazandiklarim.json")
USERNAMES_FILE = os.path.join(BASE_DIR, "usernames.txt")

BASE_URL = "https://hesap.com.tr"
ENDED_DRAWS_URL = f"{BASE_URL}/tamamlanan-cekilisler"
ACTIVE_DRAWS_URL = f"{BASE_URL}/cekilisler"


def get_tracked_usernames() -> list[str]:
    """Takip edilecek kullanıcı adlarını yükler."""
    usernames = set()

    # 1. Ortam Değişkeni
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

    return sorted(list(usernames))


# -------------------------------------------------------------
# TELEGRAM BİLDİRİMİ (SADECE KAZANMA DURUMUNDA)
# -------------------------------------------------------------
def send_win_alert(win: dict):
    """Hesabınız çekiliş kazandığında Telegram'a bildirim atar."""
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return

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
    for cid in chat_ids:
        try:
            requests.post(url, json={
                "chat_id": cid,
                "text": msg,
                "parse_mode": "HTML",
                "disable_web_page_preview": False
            }, timeout=10)
        except Exception as e:
            print(f"[!] Telegram bildirim hatası ({cid}): {e}")


# -------------------------------------------------------------
# ÇEKİLİŞ TARAMA MOTORU
# -------------------------------------------------------------
def get_client() -> cffi_requests.Session:
    return cffi_requests.Session(impersonate="chrome124")


def load_checked_draws() -> set[str]:
    if not os.path.exists(CHECKED_DRAWS_FILE):
        return set()
    try:
        with open(CHECKED_DRAWS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_checked_draws(checked_set: set[str]):
    try:
        data = sorted(list(checked_set))
        if len(data) > 1500:
            data = data[-1500:]
        with open(CHECKED_DRAWS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[!] checked_draws.json kayıt hatası: {e}")


def record_win(win_info: dict):
    past = []
    if os.path.exists(WINS_FILE):
        try:
            with open(WINS_FILE, "r", encoding="utf-8") as f:
                past = json.load(f)
        except Exception:
            pass

    if not any(w.get("draw_id") == win_info.get("draw_id") and w.get("username", "").lower() == win_info.get("username", "").lower() for w in past):
        past.append(win_info)
        try:
            with open(WINS_FILE, "w", encoding="utf-8") as f:
                json.dump(past, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[!] kazandiklarim.json kayıt hatası: {e}")


def parse_draw_page(client: cffi_requests.Session, draw_url: str) -> tuple[str, str, list[str]]:
    """Çekiliş sayfasından başlık, ödül ve kazananları ayıklar."""
    try:
        r = client.get(draw_url, timeout=12)
        if r.status_code != 200:
            return "", "", []

        soup = BeautifulSoup(r.text, "html.parser")

        title = ""
        t_el = soup.find("h1") or soup.find(class_=lambda c: c and "title" in c.lower())
        if t_el:
            title = t_el.get_text(strip=True)
        elif soup.title:
            title = soup.title.string.split("-")[0].strip()

        prize = ""
        p_el = soup.find(class_="price") or soup.find(class_=lambda c: c and "prize" in c.lower())
        if p_el:
            prize = p_el.get_text(strip=True)

        winners = []
        cards = soup.find_all(class_=lambda c: c and "winner" in c.lower())
        for card in cards:
            m = re.search(r'kazanan\s*[:\|\-]?\s*([a-zA-Z0-9_\.-]+)', card.get_text(strip=True, separator=" "), re.IGNORECASE)
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


def run_check_cycle():
    """Çekilişleri tarar, kazanç varsa Telegram'a iletir."""
    tracked_users = get_tracked_usernames()
    if not tracked_users:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [!] HATA: Takip edilecek hesap tanımlanmamış!")
        return

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
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [!] HATA: {page_url} durum kodu: {r.status_code}")
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [!] HATA: Sayfa okunamadı ({page_url}): {e}")

    new_wins = []
    for draw_id, draw_url in draw_links:
        if draw_id in checked_draws:
            continue

        title, prize, winners = parse_draw_page(client, draw_url)
        time.sleep(0.2)

        # Henüz kazananlar belirlenmemişse atla
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
                send_win_alert(win_data)

    save_checked_draws(checked_draws)
    now_str = datetime.now().strftime("%H:%M:%S")

    if new_wins:
        for w in new_wins:
            print(f"[{now_str}] [🏆 KAZANÇ] {w['username'].upper()} kazandı: {w['title']} ({w['prize']})")
    else:
        print(f"[{now_str}] [OK] Aktif: {len(draw_links)} çekiliş taranıyor | Yeni kazanç: 0")


# -------------------------------------------------------------
# SADE PING UÇ NOKTASI (RENDER & CRON-JOB İÇİN)
# -------------------------------------------------------------
app = Flask(__name__)

@app.route("/")
@app.route("/health")
@app.route("/ping")
def ping():
    """Render ve cron-job pingleri için düz metin yanıt."""
    return "OK", 200


# -------------------------------------------------------------
# ARKA PLAN ÇALIŞTIRICISI
# -------------------------------------------------------------
def background_checker():
    now_str = datetime.now().strftime("%H:%M:%S")
    tracked = get_tracked_usernames()
    print(f"[{now_str}] [BAŞLATILDI] Sistem aktif: {len(tracked)} hesap takip ediliyor | Periyot: her {CHECK_INTERVAL_MINUTES} dk")

    try:
        run_check_cycle()
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [!] HATA: İlk tarama: {e}")

    while True:
        try:
            time.sleep(CHECK_INTERVAL_MINUTES * 60)
            run_check_cycle()
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [!] HATA: Döngü hatası: {e}")
            time.sleep(10)


if __name__ == "__main__":
    if "--test" in sys.argv:
        print("Test taraması başlatılıyor...")
        run_check_cycle()
        print("Test bitti.")
    else:
        threading.Thread(target=background_checker, daemon=True).start()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [OK] Web servisi dinleniyor: 0.0.0.0:{PORT}")
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
