import os
import json
from datetime import datetime, timezone
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram configuration missing.")
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

def get_predictions_from_market():
    if not ODDS_API_KEY:
        print("Error: ODDS_API_KEY is not set.")
        return []

    # 1. Fetch all currently active soccer tournaments & leagues worldwide
    sports_url = f"https://api.the-odds-api.com/v4/sports?apiKey={ODDS_API_KEY}"
    try:
        r = requests.get(sports_url, timeout=15)
        if r.status_code != 200:
            print(f"Sports query failed: {r.text}")
            return []
        all_sports = r.json()
        soccer_keys = [s["key"] for s in all_sports if s.get("group") == "Soccer" and s.get("active")]
    except Exception as e:
        print(f"Error listing sports: {e}")
        return []

    matches = []
    
    # 2. Query top active leagues for upcoming matches & real bookmaker consensus odds
    for sport_key in soccer_keys[:8]:  # Covers active top tier & continental tournaments
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

                # Extract consensus odds from first available bookmaker (e.g. Pinnacle, Bet365)
                outcomes = bookmakers[0]["markets"][0]["outcomes"]
                home_odds = next((o["price"] for o in outcomes if o["name"] == home), None)
                away_odds = next((o["price"] for o in outcomes if o["name"] == away), None)
                draw_odds = next((o["price"] for o in outcomes if o["name"].lower() == "draw"), None)

                if home_odds and away_odds:
                    # If 2-way without draw, assign default draw
                    raw_h = 1.0 / float(home_odds)
                    raw_a = 1.0 / float(away_odds)
                    raw_d = (1.0 / float(draw_odds)) if draw_odds else 0.25
                    margin = raw_h + raw_d + raw_a

                    p_h = round((raw_h / margin) * 100, 1)
                    p_d = round((raw_d / margin) * 100, 1)
                    p_a = round((raw_a / margin) * 100, 1)

                    matches.append({
                        "league": ev.get("sport_title", "Soccer"),
                        "home": home,
                        "away": away,
                        "commence_time": ev.get("commence_time", ""),
                        "bookmaker": bookmakers[0].get("title", "Market Consensus"),
                        "probabilities": {
                            "home_win_pct": p_h,
                            "draw_pct": p_d,
                            "away_win_pct": p_a
                        }
                    })
        except Exception as e:
            print(f"Error querying {sport_key}: {e}")
            continue

    return matches

def run():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    matches = get_predictions_from_market()

    if not matches:
        send_telegram("⚠️ *Notice:* No active fixtures available right now or check your `ODDS_API_KEY`.")
        return

    # Save to predictions folder
    os.makedirs("predictions", exist_ok=True)
    with open(f"predictions/{now_str}.json", "w") as f:
        json.dump(matches, f, indent=2)

    total = len(matches)

    # Sort matches by highest favorite confidence
    matches.sort(
        key=lambda m: max(m["probabilities"]["home_win_pct"], m["probabilities"]["away_win_pct"]), 
        reverse=True
    )

    header = (
        f"⚽ *GLOBAL FOOTBALL PREDICTIONS*\n"
        f"📅 Date: `{now_str}`\n"
        f"🌍 *Upcoming Matches Found:* `{total}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
    )

    # High Confidence Picks
    top_picks = []
    for m in matches:
        p = m["probabilities"]
        if p["home_win_pct"] >= 55.0:
            top_picks.append(f"⭐ *{m['home']}* to WIN (`{p['home_win_pct']}%`)\n   ⚔️ vs {m['away']} ({m['league']})")
        elif p["away_win_pct"] >= 55.0:
            top_picks.append(f"⭐ *{m['away']}* to WIN (`{p['away_win_pct']}%`)\n   ⚔️ vs {m['home']} ({m['league']})")

    if top_picks:
        header += "🔥 *TOP VALUE PICKS:*\n" + "\n\n".join(top_picks[:5]) + "\n\n━━━━━━━━━━━━━━━━━━━\n\n"

    # All Matches Output
    batch = header
    for idx, m in enumerate(matches[:25], start=1):
        p = m["probabilities"]
        entry = (
            f"*{idx}. {m['league']}*\n"
            f"⚔️ *{m['home']}* vs *{m['away']}*\n"
            f"📊 1: `{p['home_win_pct']}%` | X: `{p['draw_pct']}%` | 2: `{p['away_win_pct']}%`\n"
            f"📈 _Odds source: {m['bookmaker']}_\n\n"
        )
        if len(batch) + len(entry) > 3800:
            send_telegram(batch)
            batch = entry
        else:
            batch += entry

    if batch.strip():
        if total > 25:
            batch += f"\n_...and {total - 25} more saved to your GitHub repo._"
        send_telegram(batch)

    print(f"Processed {total} matches successfully.")

if __name__ == "__main__":
    run()
