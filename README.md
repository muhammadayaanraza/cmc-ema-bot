# 📡 CMC EMA Signal Bot

**CoinMarketCap** ke top coins ko scan karke **EMA 20 × EMA 200 crossover** signals **Telegram** pe bhejta hai — har 15 minute baad.

---

## ⚡ Features

- ✅ CoinMarketCap Top 100 coins auto-scan
- ✅ EMA 20 × EMA 200 crossover detection (15M candles)
- ✅ LONG / SHORT signal with Entry, Stop Loss, TP1 / TP2 / TP3
- ✅ RSI + ATR + Signal Strength included
- ✅ Duplicate signal guard (same signal dobara nahi aata)
- ✅ Scan summary har cycle ke baad
- ✅ Full log file (`cmc_ema_bot.log`)
- ✅ Railway.app / VPS / PC — sab jagah chalta hai

---

## 📁 Files

```
cmc_ema_bot_fixed.py   ← Main bot script
requirements.txt       ← Python libraries
Procfile               ← Railway.app ke liye
.gitignore             ← Sensitive files exclude karta hai
README.md              ← Yeh file
```

---

## 🛠️ Setup — 5 Minutes

### Step 1 — Libraries install karein
```bash
pip install -r requirements.txt
```

### Step 2 — CoinMarketCap FREE API Key
1. [coinmarketcap.com/api](https://coinmarketcap.com/api/) pe jaao
2. **Get Your Free API Key** click karo
3. Sign up karo → Dashboard → API Keys → Copy

### Step 3 — Telegram Bot banao
1. Telegram pe **@BotFather** open karo
2. `/newbot` bhejo → naam aur username dein
3. **BOT_TOKEN** milega — copy karo

### Step 4 — Chat ID lao
1. Telegram pe **@userinfobot** open karo
2. `/start` bhejo → **Id:** ke aage number milega

### Step 5 — Script mein values fill karein
`cmc_ema_bot_fixed.py` file kholein aur yeh 3 lines edit karein:
```python
BOT_TOKEN   = "7123456789:AAFxyz..."   # @BotFather se
CHAT_ID     = "123456789"              # @userinfobot se
CMC_API_KEY = "a1b2c3d4-e5f6-..."     # coinmarketcap.com/api se
```

### Step 6 — Chalao
```bash
python cmc_ema_bot_fixed.py
```

---

## ☁️ 24/7 Deploy — Railway.app (Free)

1. [railway.app](https://railway.app) pe free account banao
2. **New Project → Deploy from GitHub** → yeh repo select karo
3. **Variables** mein yeh set karo:

| Key | Value |
|-----|-------|
| `BOT_TOKEN` | Apna Telegram bot token |
| `CHAT_ID` | Apna Telegram chat ID |
| `CMC_API_KEY` | Apni CoinMarketCap API key |

4. Deploy karo — bot 24/7 chalne lagega ✅

> ⚠️ **Important:** Railway Variables mein values daalein — script mein seedha mat likhein (security ke liye)

---

## 🔧 VPS Deploy (Linux)

```bash
# 1. Dependencies install
pip3 install -r requirements.txt

# 2. Systemd service banao
sudo nano /etc/systemd/system/emabot.service
```

```ini
[Unit]
Description=CMC EMA Signal Bot
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/user/cmc_ema_bot_fixed.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable emabot
sudo systemctl start emabot
sudo systemctl status emabot
```

---

## ⚙️ Settings Customize Karein

`cmc_ema_bot_fixed.py` mein yeh values change kar sakte hain:

| Setting | Default | Description |
|---------|---------|-------------|
| `TOP_N_COINS` | `100` | CMC se kitne coins scan hों |
| `INTERVAL_MINUTES` | `15` | Har kitne minute baad scan |
| `MIN_VOLUME_USD` | `5,000,000` | Minimum 24h volume filter |
| `CANDLE_INTERVAL` | `15m` | Candle timeframe |
| `EMA_FAST` | `20` | Fast EMA period |
| `EMA_SLOW` | `200` | Slow EMA period |
| `CUSTOM_COINS` | `[]` | Specific coins (khali = top N) |

---

## 📊 Signal Message Example

```
🟢 CMC SIGNAL — BTC/USDT
━━━━━━━━━━━━━━━━━━━━━━━━━
📈 LONG — BUY
🔀 EMA20 ↑ crossed ABOVE EMA200 (Bullish)
🕐 Time     : 29 May 2026  14:15 UTC
━━━━━━━━━━━━━━━━━━━━━━━━━
📍 Entry    : $ 67,450.00
🛑 Stop Loss: $ 66,230.00
🎯 TP 1     : $ 68,670.00
🎯 TP 2     : $ 70,890.00
🎯 TP 3     : $ 73,110.00
⚖️ R:R Ratio: 1 : 2 / 4 / 6
━━━━━━━━━━━━━━━━━━━━━━━━━
📶 EMA 20   : $ 67,380.00
📶 EMA 200  : $ 67,290.00
📏 ATR (14) : $ 813.00
📊 RSI (14) : 58.3 ✅ Neutral
━━━━━━━━━━━━━━━━━━━━━━━━━
💪 Strength : ████████░░ 82.4%
```

---

## ⚠️ Disclaimer

Yeh bot sirf educational purpose ke liye hai. EMA crossover signals 100% accurate nahi hote. Real money se trade karne se pehle apna khud ka analysis zaroor karein. Koi bhi financial loss ki zimmedari developer ki nahi hogi.

---

## 📜 License

MIT License — Free to use and modify.
