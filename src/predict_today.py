import os
import json
from datetime import datetime, timezone
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

GITHUB_USERNAME = "shayanroyxyz"
GITHUB_REPO = "Football-Predictor"

# Live Vercel App URL
PAGES_URL = "https://football-predictor-croi-sigma.vercel.app"
TRIGGER_URL = f"https://github.com/{GITHUB_USERNAME}/{GITHUB_REPO}/actions/workflows/daily.yml"

GLOBAL_PRIORITY_KEYWORDS = [
    "champions", "uefa", "europa", "libertadores", "nations", 
    "world cup", "fifa", "copa sudamericana", "afcon", "asian cup"
]

def format_commence_time(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y"), dt.strftime("%H:%M UTC")
    except Exception:
        return "Upcoming", "TBD"

def send_telegram(message):
    """Sends message with real clickable inline action buttons."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram configuration missing.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "🌐 Open Web Dashboard", "url": PAGES_URL},
                    {"text": "⚡ Re-Run on GitHub", "url": TRIGGER_URL}
                ]
            ]
        }
    }
    try:
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code != 200:
            print(f"Telegram API warning: {res.text}")
    except Exception as e:
        print(f"Telegram error: {e}")

def get_predictions_from_market():
    if not ODDS_API_KEY:
        print("Error: ODDS_API_KEY is not set.")
        return []

    sports_url = f"https://api.the-odds-api.com/v4/sports?apiKey={ODDS_API_KEY}"
    try:
        r = requests.get(sports_url, timeout=15)
        if r.status_code != 200:
            return []
        all_sports = r.json()
        soccer_keys = [s["key"] for s in all_sports if s.get("group") == "Soccer" and s.get("active")]
    except Exception:
        return []

    def get_sport_priority(key_name):
        k = key_name.lower()
        for idx, word in enumerate(GLOBAL_PRIORITY_KEYWORDS):
            if word in k:
                return idx
        return 99

    soccer_keys.sort(key=get_sport_priority)

    matches = []
    for sport_key in soccer_keys[:6]:
        odds_url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h&oddsFormat=decimal"
        try:
            res = requests.get(odds_url, timeout=15)
            if res.status_code != 200:
                continue
            events = res.json()
            for ev in events:
                home = ev.get("home_team")
                away = ev.get("away_team")
                bookmakers = ev.get("bookmakers", [])
                if not bookmakers or not home or not away:
                    continue

                outcomes = bookmakers[0]["markets"][0]["outcomes"]
                home_odds = next((o["price"] for o in outcomes if o["name"] == home), None)
                away_odds = next((o["price"] for o in outcomes if o["name"] == away), None)
                draw_odds = next((o["price"] for o in outcomes if o["name"].lower() == "draw"), None)

                if home_odds and away_odds:
                    raw_h = 1.0 / float(home_odds)
                    raw_a = 1.0 / float(away_odds)
                    raw_d = (1.0 / float(draw_odds)) if draw_odds else 0.25
                    margin = raw_h + raw_d + raw_a

                    p_h = round((raw_h / margin) * 100, 1)
                    p_d = round((raw_d / margin) * 100, 1)
                    p_a = round((raw_a / margin) * 100, 1)

                    match_date, match_time = format_commence_time(ev.get("commence_time", ""))
                    league_title = ev.get("sport_title", "Soccer")
                    is_global = any(w in league_title.lower() for w in GLOBAL_PRIORITY_KEYWORDS)

                    matches.append({
                        "league": league_title,
                        "is_global": is_global,
                        "home": home,
                        "away": away,
                        "commence_time": ev.get("commence_time", ""),
                        "match_date": match_date,
                        "match_time": match_time,
                        "bookmaker": bookmakers[0].get("title", "Market Consensus"),
                        "probabilities": {
                            "home_win_pct": p_h,
                            "draw_pct": p_d,
                            "away_win_pct": p_a
                        }
                    })
        except Exception:
            continue

    return matches

def run():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    matches = get_predictions_from_market()

    if not matches:
        send_telegram("⚠️ *Notice:* No active fixtures available right now.")
        return

    # Sort chronological by commence time
    matches.sort(key=lambda m: (m.get("commence_time") or ""))

    os.makedirs("predictions", exist_ok=True)
    with open(f"predictions/{now_str}.json", "w") as f:
        json.dump(matches, f, indent=2)

    total = len(matches)

    # Top Value Picks
    top_picks = []
    for m in matches:
        p = m["probabilities"]
        if p["home_win_pct"] >= 55.0:
            top_picks.append(
                f"⭐ *{m['home']}* to WIN (`{p['home_win_pct']}%`)\n"
                f"   ⚔️ vs {m['away']} ({m['league']})\n"
                f"   🗓️ `{m['match_date']} • {m['match_time']}`"
            )
        elif p["away_win_pct"] >= 55.0:
            top_picks.append(
                f"⭐ *{m['away']}* to WIN (`{p['away_win_pct']}%`)\n"
                f"   ⚔️ vs {m['home']} ({m['league']})\n"
                f"   🗓️ `{m['match_date']} • {m['match_time']}`"
            )

    header = (
        f"⚽ *GLOBAL FOOTBALL PREDICTIONS*\n"
        f"📅 Date: `{now_str}`\n"
        f"🌍 *Upcoming Matches Found:* `{total}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
    )

    if top_picks:
        header += "🔥 *TOP VALUE PICKS:*\n" + "\n\n".join(top_picks[:5]) + "\n\n━━━━━━━━━━━━━━━━━━━\n\n"

    batch = header
    shown = min(total, 25)

    for idx, m in enumerate(matches[:shown], start=1):
        p = m["probabilities"]
        badge = "🌍 " if m["is_global"] else ""
        entry = (
            f"*{idx}. {badge}{m['league']}*\n"
            f"🗓️ `{m['match_date']}` | ⏰ `{m['match_time']}`\n"
            f"⚔️ *{m['home']}* vs *{m['away']}*\n"
            f"   🏠 {m['home']} Win: `{p['home_win_pct']}%`\n"
            f"   🤝 Draw: `{p['draw_pct']}%`\n"
            f"   ✈️ {m['away']} Win: `{p['away_win_pct']}%`\n\n"
        )
        if len(batch) + len(entry) > 3800:
            send_telegram(batch)
            batch = entry
        else:
            batch += entry

    if batch.strip():
        send_telegram(batch)

    print(f"Processed {total} matches successfully.")

if __name__ == "__main__":
    run()
