"""
Bot 3 — Breakout Momentum
Stratégie : Cassure de Support/Résistance + Volume
Gagne sur les grandes cassures de marché
Compatible Python 3.14 — Render.com
"""

import os, time, logging, requests, ccxt

# ══════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════
TG_TOKEN  = os.getenv("TG_TOKEN", "")
TG_CHAT   = os.getenv("TG_CHAT_ID", "")

PAIRS = [
    "EUR/USDT",
    "GBP/USDT",
    "XAU/USDT",
    "BTC/USDT",
    "ETH/USDT",
]

TIMEFRAME      = "4h"   # H4 — breakouts plus fiables sur grand timeframe
CAPITAL        = 1000
RISK_PCT       = 0.02
CHECK_INTERVAL = 240    # vérifie toutes les 4 minutes

# Paramètres Breakout
LOOKBACK       = 20     # nombre de bougies pour calculer S/R
VOLUME_MULT    = 1.5    # volume doit être 1.5x la moyenne pour confirmer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

exchange    = ccxt.bybit({"enableRateLimit": True})
last_signal = {}
last_upd_id = 0
bot_active  = True

# ══════════════════════════════════════════════
#  TELEGRAM
# ══════════════════════════════════════════════
def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        log.error(f"Telegram error: {e}")

# ══════════════════════════════════════════════
#  INDICATEURS
# ══════════════════════════════════════════════
def resistance(highs, lookback):
    """Plus haut des N dernières bougies = niveau de résistance."""
    return max(highs[-lookback-1:-1])

def support(lows, lookback):
    """Plus bas des N dernières bougies = niveau de support."""
    return min(lows[-lookback-1:-1])

def avg_volume(volumes, period=20):
    """Volume moyen sur N bougies."""
    return sum(volumes[-period-1:-1]) / period

def atr(highs, lows, closes, period=14):
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        trs.append(tr)
    return sum(trs[-period:]) / period

def ema(prices, period):
    k = 2 / (period + 1)
    e = prices[0]
    for p in prices[1:]:
        e = p * k + e * (1 - k)
    return e

# ══════════════════════════════════════════════
#  STRATÉGIE BREAKOUT
# ══════════════════════════════════════════════
def check(symbol):
    """
    Logique Breakout Momentum :

    BUY BREAKOUT  → Prix casse la RÉSISTANCE à la hausse
                    + Volume > 1.5x la moyenne (confirmation)
                    + EMA50 haussière (tendance favorable)

    SELL BREAKOUT → Prix casse le SUPPORT à la baisse
                    + Volume > 1.5x la moyenne (confirmation)
                    + EMA50 baissière (tendance favorable)

    Stop Loss  : 1 ATR sous le niveau cassé
    Take Profit: 2 ATR au-delà de l'entrée (ratio 1:2)
    """
    try:
        bars    = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=100)
        closes  = [b[4] for b in bars]
        highs   = [b[2] for b in bars]
        lows    = [b[3] for b in bars]
        volumes = [b[5] for b in bars]

        price    = closes[-1]
        res      = resistance(highs, LOOKBACK)
        sup      = support(lows, LOOKBACK)
        avg_vol  = avg_volume(volumes)
        curr_vol = volumes[-1]
        atr_val  = atr(highs, lows, closes)
        ema50    = ema(closes, 50)

        vol_confirmed = curr_vol > avg_vol * VOLUME_MULT

        # BREAKOUT HAUSSIER — cassure de la résistance
        if price > res and vol_confirmed and price > ema50:
            sl  = round(res - atr_val, 5)
            tp  = round(price + atr_val * 2, 5)
            lot = round((CAPITAL * RISK_PCT) / abs(price - sl), 4) if abs(price - sl) > 0 else 0.01
            return {
                "symbol": symbol, "action": "BUY", "price": round(price, 5),
                "sl": sl, "tp": tp,
                "resistance": round(res, 5),
                "support": round(sup, 5),
                "volume_ratio": round(curr_vol / avg_vol, 2),
                "atr": round(atr_val, 5),
                "lot": lot,
                "reason": f"Cassure résistance {round(res,5)} avec volume x{round(curr_vol/avg_vol,1)}"
            }

        # BREAKOUT BAISSIER — cassure du support
        if price < sup and vol_confirmed and price < ema50:
            sl  = round(sup + atr_val, 5)
            tp  = round(price - atr_val * 2, 5)
            lot = round((CAPITAL * RISK_PCT) / abs(sl - price), 4) if abs(sl - price) > 0 else 0.01
            return {
                "symbol": symbol, "action": "SELL", "price": round(price, 5),
                "sl": sl, "tp": tp,
                "resistance": round(res, 5),
                "support": round(sup, 5),
                "volume_ratio": round(curr_vol / avg_vol, 2),
                "atr": round(atr_val, 5),
                "lot": lot,
                "reason": f"Cassure support {round(sup,5)} avec volume x{round(curr_vol/avg_vol,1)}"
            }

    except Exception as e:
        log.error(f"Signal error {symbol}: {e}")
    return None

# ══════════════════════════════════════════════
#  COMMANDES TELEGRAM
# ══════════════════════════════════════════════
def check_commands():
    global bot_active, last_upd_id
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
            params={"offset": last_upd_id + 1, "timeout": 5},
            timeout=10
        ).json()

        for upd in r.get("result", []):
            last_upd_id = upd["update_id"]
            text = upd.get("message", {}).get("text", "").strip().lower()

            if text == "/pause":
                bot_active = False
                tg("Bot 3 mis en pause. /resume pour reprendre.")
            elif text == "/resume":
                bot_active = True
                tg("Bot 3 repris. Surveillance active.")
            elif text == "/status":
                status = "ACTIF" if bot_active else "EN PAUSE"
                sigs = "\n".join([f"  {p}: {last_signal.get(p,'—')}" for p in PAIRS])
                tg(
                    f"<b>Bot 3 — Breakout — {status}</b>\n\n"
                    f"Derniers signaux :\n{sigs}\n\n"
                    f"Stratégie : Support/Résistance + Volume\n"
                    f"Timeframe : {TIMEFRAME}\n"
                    f"Lookback : {LOOKBACK} bougies\n"
                    f"Volume mult : {VOLUME_MULT}x\n"
                    f"Capital : ${CAPITAL} | Risque : {int(RISK_PCT*100)}%"
                )
            elif text in ["/start", "/help"]:
                tg(
                    "<b>Bot 3 — Breakout Momentum</b>\n\n"
                    "Stratégie : Cassure Support/Résistance + Volume\n"
                    "Timeframe : H4 — signaux moins fréquents mais plus puissants\n\n"
                    "/status /pause /resume /help"
                )
    except Exception as e:
        log.error(f"Commands error: {e}")

# ══════════════════════════════════════════════
#  BOUCLE PRINCIPALE
# ══════════════════════════════════════════════
def main():
    log.info("Bot 3 Breakout démarré")
    tg(
        "<b>Bot 3 — Breakout Momentum démarré</b>\n\n"
        f"Paires : {', '.join(PAIRS)}\n"
        f"Timeframe : {TIMEFRAME} (H4)\n"
        f"Stratégie : Cassure S/R + Volume confirmé\n"
        f"Risque/trade : {int(RISK_PCT*100)}%\n\n"
        "Signaux moins fréquents mais plus puissants.\n"
        "Commandes : /status /pause /resume /help"
    )

    while True:
        try:
            check_commands()

            if bot_active:
                for symbol in PAIRS:
                    sig = check(symbol)
                    if sig and last_signal.get(symbol) != sig["action"]:
                        last_signal[symbol] = sig["action"]
                        a = sig["action"]
                        tg(
                            f"<b>[{a}] {sig['symbol']} — Breakout</b>\n"
                            f"━━━━━━━━━━━━━━\n"
                            f"Prix         : {sig['price']}\n"
                            f"Résistance   : {sig['resistance']}\n"
                            f"Support      : {sig['support']}\n"
                            f"Volume ratio : x{sig['volume_ratio']}\n"
                            f"ATR          : {sig['atr']}\n"
                            f"Stop Loss    : {sig['sl']}\n"
                            f"Take Profit  : {sig['tp']}\n"
                            f"Lot          : {sig['lot']}\n"
                            f"━━━━━━━━━━━━━━\n"
                            f"Raison : {sig['reason']}"
                        )
                        log.info(f"Signal: {a} {symbol} @ {sig['price']}")

        except Exception as e:
            log.error(f"Loop error: {e}")

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
