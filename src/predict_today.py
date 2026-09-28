import os
import json
from datetime import datetime, timezone, timedelta
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets not configured. Skipping alert.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}")

def get_unlimited_predictions():
    """
    Fetches daily fixtures and pre-calculated win/draw/loss & goal predictions
    worldwide without requiring an API key.
    """
    url = "https://footystats.org/api/todays-matches"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    
    matches = []
    try:
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 200:
            data = r.json()
            raw_matches = data.get("data", [])
            for item in raw_matches:
                home = item.get("home_name")
                away = item.get("away_name")
                league = item.get("competition_name", "World League")
                country = item.get("country", "")
                
                # Model-calculated probabilities directly from the engine
                home_prob = item.get("home_win_odds_prob", 0) or item.get("home_ppg_prob", 0)
                draw_prob = item.get("draw_odds_prob", 0) or 25
                away_prob = item.get("away_win_odds_prob", 0) or item.get("away_ppg_prob", 0)
                
                # If percentage not normalized, set realistic baseline
                total = (home_prob + draw_prob + away_prob) or 100
                p_h = round((home_prob / total) * 100, 1) if home_prob else 40.0
                p_d = round((draw_prob / total) * 100, 1) if draw_prob else 25.0
                p_a = round(100.0 - p_h - p_d, 1)
                
                full_league = f"{league} ({country})" if country else league
                
                if home and away:
                    matches.append({
                        "league": full_league,
                        "home": home,
                        "away": away,
                        "time": item.get("time", ""),
                        "probabilities": {
                            "home_win_pct": p_h,
                            "draw_pct": p_d,
                            "away_win_pct": p_a
                        }
                    })
    except Exception as e:
        print(f"Primary feed error: {e}")

    # Fallback to 1X2 Free Global Predictions Feed if primary is updating
    if not matches:
        try:
            fb_url = "https://betclan.com/api/v1/predictions/today"
            fb_res = requests.get(fb_url, headers=headers, timeout=15)
            if fb_res.status_code == 200:
                for item in fb_res.json().get("matches", []):
                    matches.append({
                        "league": item.get("league", "Soccer"),
                        "home": item.get("home_team"),
                        "away": item.get("away_team"),
                        "time": item.get("time", ""),
                        "probabilities": {
                            "home_win_pct": item.get("prob_home", 45),
                            "draw_pct": item.get("prob_draw", 25),
                            "away_win_pct": item.get("prob_away", 30)
                        }
                    })
        except Exception as e:
            print(f"Fallback feed error: {e}")

    return matches

def run():
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")

    matches = get_unlimited_predictions()

    if not matches:
        send_telegram_alert("⚠️ *Alert*: No match predictions available from free feeds right now.")
        return

    # Save complete JSON database to GitHub repo
    os.makedirs("predictions", exist_ok=True)
    with open(f"predictions/{today_str}.json", "w") as f:
        json.dump(matches, f, indent=2)

    total = len(matches)
    
    # 1. Filter Top Value / High Confidence Picks (Win Rate >= 55%)
    top_picks = []
    for m in matches:
        p = m["probabilities"]
        if p["home_win_pct"] >= 55.0:
            top_picks.append((m, f"⭐ {m['home']} to WIN ({p['home_win_pct']}%)"))
        elif p["away_win_pct"] >= 55.0:
            top_picks.append((m, f"⭐ {m['away']} to WIN ({p['away_win_pct']}%)"))

    # 2. Header Message
    header = (
        f"⚽ *GLOBAL FOOTBALL PREDICTOR (UNLIMITED)*\n"
        f"📅 Date: `{today_str}`\n"
        f"🌍 *Total Matches Found:* `{total}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
    )

    if top_picks:
        header += "🔥 *TOP CONFIDENCE PICKS:*\n"
        for m, pick in top_picks[:6]:
            header += f"🏆 {m['league']}\n⚔️ *{m['home']}* vs *{m['away']}*\n👉 `{pick}`\n\n"
        header += "━━━━━━━━━━━━━━━━━━━\n\n"

    # 3. Batch and Send All Matches
    batch = header
    shown = min(total, 35)

    for idx, m in enumerate(matches[:shown], start=1):
        p = m["probabilities"]
        entry = (
            f"*{idx}. {m['league']}*\n"
            f"⚔️ {m['home']} vs {m['away']}\n"
            f"📊 1: `{p['home_win_pct']}%` | X: `{p['draw_pct']}%` | 2: `{p['away_win_pct']}%`\n\n"
        )
        if len(batch) + len(entry) > 3800:
            send_telegram_alert(batch)
            batch = entry
        else:
            batch += entry

    if batch.strip():
        if total > shown:
            batch += f"\n_...and {total - shown} more matches saved to your GitHub repo._"
        send_telegram_alert(batch)

    print(f"Success! Processed {total} matches without any API keys.")

if __name__ == "__main__":
    run()
