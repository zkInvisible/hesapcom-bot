# 🎁 Hesap.com.tr 7/24 Çekiliş Kazanan Takip Botu (Render & Telegram)

Bu proje, **hesap.com.tr** üzerindeki biten ve güncel çekilişleri 7 gün 24 saat kesintisiz tarayan, hesaplarınızdan biri çekiliş kazandığı anda **Telegram üzerinden sesli ve detaylı bildirim** gönderen bulut uyumlu bir otomasyon sistemidir.

Render.com'un **ücretsiz (Free)** planında çalışmak üzere özel olarak optimize edilmiştir (Cloudflare TLS impersonation ile sıfır RAM/CPU tüketimi ve uyku önleyici Keep-Alive mekanizması içerir).

---

## 🌟 Özellikler

- **7/24 Kesintisiz Çalışma (Render Free Uyumlu):** Dahili Flask web sunucusu barındırır. cron-job.org veya harici cron pingleri ile Render'ın 15 dakikalık uyku moduna geçmesi tamamen engellenir.
- **SADECE Kazanınca Telegram Bildirimi:** Gereksiz başlangıç, rutin durum veya boş döngü mesajları atmaz! Yalnızca ve yalnızca hesaplarınızdan biri çekiliş kazandığında anında detaylı bildirim gönderir.
- **Ultra Hafif & Hızlı:** Tarayıcı (Chrome/Selenium) gerektirmez; `curl_cffi` ile doğrudan TLS parmak izi taklidi yaparak Cloudflare korumasını 0.2 saniyede aşar.
- **Web Kontrol Paneli:** Sunucunuzun canlı durumunu, taranan çekiliş sayısını, takip edilen hesapları ve kazanılan ödülleri tarayıcınızdan izleyebileceğiniz modern bir arayüz sunar.
- **Tek Tıkla Render Kurulumu:** `render.yaml` blueprint dosyası ile 2 dakikada Render'a kurulabilir.

---

## 📱 1. Adım: Telegram Botu ve Chat ID Alma (2 Dakika)

### A) Bot Oluşturma:
1. Telegram uygulamanızda **[@BotFather](https://t.me/BotFather)** botunu açın ve `/newbot` yazın.
2. Botunuza bir isim verin (Örn: `HesapComTakipBot`).
3. Botunuza sonu `bot` ile biten bir kullanıcı adı verin (Örn: `hesapcom_kazanan_bot`).
4. BotFather size bir **HTTP API Token** verecektir. (Örn: `7123456789:AAFs89XJk...`). Bu sizin `TELEGRAM_BOT_TOKEN` bilginizdir.

### B) Chat ID Öğrenme:
1. Telegram arama kutusuna **[@userinfobot](https://t.me/userinfobot)** yazıp bota `/start` deyin.
2. Bot size **`Id: 123456789`** şeklinde bir numara gönderecektir. Bu sizin `TELEGRAM_CHAT_ID` bilginizdir.
3. **ÖNEMLİ:** Bildirim alabilmek için, 1. adımda BotFather ile oluşturduğunuz kendi botunuza gidip bir kez `/start` mesajı atın.

---

## 🚀 2. Adım: Render.com Üzerinde 7/24 Ücretsiz Başlatma

### Yöntem 1: GitHub ile Deploy Etme (En Kolay & Otomatik)

1. Bu `render_kazanan_bot` klasörünü GitHub hesabınıza yeni bir repo olarak yükleyin (Public veya Private).
2. [Render.com](https://render.com) adresine ücretsiz üye olun veya giriş yapın.
3. Render panosunda sağ üstteki **"New +"** butonuna basıp **"Web Service"** seçin.
4. GitHub reponuzu seçin ("Connect").
5. Aşağıdaki ayarları kontrol edin:
   - **Name:** `hesapcom-kazanan-bot` (veya istediğiniz bir ad)
   - **Region:** `Frankfurt (EU)` (Türkiye'ye en yakın)
   - **Branch:** `main` (veya `master`)
   - **Language/Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python app.py`
   - **Instance Type:** `Free` ($0/month)
6. Aşağıdaki **"Environment Variables"** (Ortam Değişkenleri) bölümüne şu anahtarları ekleyin:
   - `TELEGRAM_BOT_TOKEN` = BotFather'dan aldığınız token
   - `TELEGRAM_CHAT_ID` = userinfobot'tan aldığınız chat ID numaranız
   - `USERNAMES` = Takip edilecek hesap kullanıcı adlarınız (virgülle ayırın, Örn: `ioskan4362,yavuz555,kraliyeyt,iosslayer22,losort33,akal53,dontbrea`)
   - `CHECK_INTERVAL_MINUTES` = `5` (İsteğe bağlı, varsayılan 5 dakikada birdir)
7. En alttaki **"Create Web Service"** butonuna basın!

---

## ⏰ 3. Adım: Cron-job ile 7/24 Uyanık Tutma (Ping Ayarı)

Render'ın ücretsiz planı 15 dakika boyunca HTTP isteği almazsa uyku moduna geçer. Bu yüzden cron-job ile düzenli ping atarak botun 7/24 uyanık kalmasını sağlıyoruz:

1. Render servisinizin web adresini kopyalayın (Örn: `https://hesapcom-kazanan-bot.onrender.com`).
2. Ücretsiz **[cron-job.org](https://cron-job.org)** veya **[uptimerobot.com](https://uptimerobot.com)** sitesine girin.
3. Yeni bir Cron Job (veya Monitor) oluşturun:
   - **URL:** `https://hesapcom-kazanan-bot.onrender.com/health` (veya `/ping` ya da `/cron`)
   - **İstek Sıklığı (Schedule):** `Her 5 dakikada bir` (Every 5 minutes) veya `Her 10 dakikada bir`
4. Kaydedin. Cron-job her 5 dakikada bir sitenizi tetikleyecek, Render asla uykuya geçmeyecek ve botunuz 7/24 aralıksız çekilişleri tarayacaktır.

---

## 💻 4. Adım: Yerel Bilgisayarda Test Etme

İsterseniz Render'a yüklemeden önce kendi bilgisayarınızda tek bir komutla test edebilirsiniz:

1. `.env.example` dosyasının adını `.env` olarak değiştirin ve tokenlerinizi girin:
   ```env
   TELEGRAM_BOT_TOKEN=bot_tokeniniz
   TELEGRAM_CHAT_ID=chat_id_numaraniz
   USERNAMES=ioskan4362,yavuz555,kraliyeyt
   ```
2. Teşhis testini çalıştırın:
   ```bash
   python local_test.py
   ```
3. Yerel web kontrol panelini açmak için:
   ```bash
   python app.py
   ```
   Tarayıcınızdan `http://localhost:10000` adresine girerek kontrol panelini görebilirsiniz.

---

## 📂 Dosya Açıklamaları

- `app.py`: Flask tabanlı web sunucusu, arka plan tarama thread'i ve self-ping yöneticisi.
- `checker.py`: Cloudflare TLS parmak izi korumasını aşan çekiliş tarama motoru.
- `telegram_notifier.py`: HTML destekli zengin bildirim gönderim modülü.
- `config.py`: Ortam değişkenlerini ve dosya yollarını yöneten konfigürasyon katmanı.
- `local_test.py`: Hızlı teşhis ve doğrulama aracı.
- `usernames.txt`: Takip edilecek kullanıcı adlarının listesi (ortam değişkeni yerine dosya kullanmak isterseniz).
- `checked_draws.json`: Daha önce taranmış çekilişlerin kayıt defteri (aynı çekiliş tekrar taranmaz).
- `kazandiklarim.json`: Kazandığınız çekilişlerin otomatik tutulduğu arşiv dosyası.
- `render.yaml`: Render için 1-tıkla Blueprint kurulum şablonu.
- `Dockerfile`: Opsiyonel Docker konteyner desteği.
