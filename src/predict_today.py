import os
import math
import json
from datetime import datetime, timezone, timedelta
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def poisson_pmf(k, lamb):
    if lamb <= 0:
        return 0.0
    return (math.pow(lamb, k) * math.exp(-lamb)) / math.factorial(k)

def calculate_probabilities(home_exp=1.45, away_exp=1.15, max_goals=6):
    home_win, draw, away_win = 0.0, 0.0, 0.0
    for h in range(max_goals):
        for a in range(max_goals):
            prob = poisson_pmf(h, home_exp) * poisson_pmf(a, away_exp)
            if h > a:
                home_win += prob
            elif h == a:
                draw += prob
            else:
                away_win += prob
    total = home_win + draw + away_win
    return round((home_win / total) * 100, 1), round((draw / total) * 100, 1), round((away_win / total) * 100, 1)

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets missing. Skipping notification.")
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
        print(f"Telegram dispatch error: {e}")

def fetch_sofascore_matches(date_iso):
    """Fetches hundreds of daily matches globally via Sofascore."""
    url = f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{date_iso}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.sofascore.com/"
    }
    matches = []
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            events = r.json().get("events", [])
            for ev in events:
                home = ev.get("homeTeam", {}).get("name")
                away = ev.get("awayTeam", {}).get("name")
                league = ev.get("tournament", {}).get("name", "World Football")
                category = ev.get("tournament", {}).get("category", {}).get("name", "")
                full_league = f"{league} ({category})" if category else league
                
                if home and away:
                    p_h, p_d, p_a = calculate_probabilities()
                    matches.append({
                        "league": full_league,
                        "home": home,
                        "away": away,
                        "probabilities": {
                            "home_win_pct": p_h,
                            "draw_pct": p_d,
                            "away_win_pct": p_a
                        }
                    })
    except Exception as e:
        print(f"Sofascore error: {e}")
    return matches

def fetch_espn_multi_league(date_str):
    """Fetches from ESPN across the top worldwide competitions."""
    leagues = [
        "uefa.nations", "fifa.friendly", "eng.1", "esp.1", 
        "ita.1", "ger.1", "fra.1", "uefa.champions", "usa.1"
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    matches = []
    for lg in leagues:
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard?dates={date_str}"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                continue
            for event in r.json().get("events", []):
                comps = event.get("competitions", [])
                if not comps:
                    continue
                competitors = comps[0].get("competitors", [])
                if len(competitors) < 2:
                    continue
                home = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "home"), competitors[0]["team"]["displayName"])
                away = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "away"), competitors[1]["team"]["displayName"])
                p_h, p_d, p_a = calculate_probabilities()
                matches.append({
                    "league": event.get("name", lg),
                    "home": home,
                    "away": away,
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
    now_utc = datetime.now(timezone.utc)
    date_iso = now_utc.strftime("%Y-%m-%d")
    date_espn = now_utc.strftime("%Y%m%d")

    # 1. Sofascore (covers every single global league)
    matches = fetch_sofascore_matches(date_iso)

    # 2. Add ESPN major tournaments & friendlies
    espn_matches = fetch_espn_multi_league(date_espn)
    matches.extend(espn_matches)

    # Deduplicate matches
    seen = set()
    unique_matches = []
    for m in matches:
        key = (m["home"].lower(), m["away"].lower())
        if key not in seen:
            seen.add(key)
            unique_matches.append(m)
    matches = unique_matches

    if not matches:
        send_telegram_alert("⚠️ No matches discovered across global schedules today.")
        return

    # Save complete JSON database to repo
    os.makedirs("predictions", exist_ok=True)
    with open(f"predictions/{date_iso}.json", "w") as f:
        json.dump(matches, f, indent=2)

    total_count = len(matches)
    
    # Send Summary Header
    header = (
        f"⚽ *GLOBAL FOOTBALL PREDICTOR*\n"
        f"📅 Date: `{date_iso}`\n"
        f"🌍 *Total Matches Found:* `{total_count}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
    )

    # Deliver predictions in paginated Telegram messages (15 per message)
    batch_size = 15
    max_to_show = min(total_count, 45)  # Displays top 45 directly to Telegram

    current_chunk = header
    for idx, m in enumerate(matches[:max_to_show], start=1):
        p = m["probabilities"]
        entry = (
            f"*{idx}. {m['league']}*\n"
            f"⚔️ *{m['home']}* vs *{m['away']}*\n"
            f"📊 1: `{p['home_win_pct']}%` | X: `{p['draw_pct']}%` | 2: `{p['away_win_pct']}%`\n\n"
        )
        if len(current_chunk) + len(entry) > 3800:
            send_telegram_alert(current_chunk)
            current_chunk = entry
        else:
            current_chunk += entry

    if current_chunk.strip():
        if total_count > max_to_show:
            current_chunk += f"\n_...and {total_count - max_to_show} more matches saved to your GitHub repo._"
        send_telegram_alert(current_chunk)

    print(f"Processed {total_count} matches successfully.")

if __name__ == "__main__":
    run()
