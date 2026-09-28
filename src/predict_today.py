import os
import math
import json
from datetime import datetime, timedelta, timezone
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
        print(f"Telegram error: {e}")

def fetch_from_fotmob(date_str):
    """
    Fetches matches from FotMob's open daily feed.
    date_str format: YYYYMMDD
    """
    url = f"https://www.fotmob.com/api/matches?date={date_str}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    }
    matches = []
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            for league in data.get("leagues", []):
                league_name = league.get("name", "World Soccer")
                ccode = league.get("ccode", "")
                full_league = f"{league_name} ({ccode})" if ccode else league_name

                for m in league.get("matches", []):
                    home = m.get("home", {}).get("name")
                    away = m.get("away", {}).get("name")
                    status = m.get("status", {})
                    
                    if home and away:
                        p_home, p_draw, p_away = calculate_probabilities()
                        matches.append({
                            "league": full_league,
                            "home": home,
                            "away": away,
                            "date": status.get("utcTime", date_str),
                            "probabilities": {
                                "home_win_pct": p_home,
                                "draw_pct": p_draw,
                                "away_win_pct": p_away
                            }
                        })
    except Exception as e:
        print(f"FotMob error: {e}")
    return matches

def fetch_from_thesportsdb():
    """Fallback feed covering all major global upcoming events."""
    url = "https://www.thesportsdb.com/api/v1/json/3/eventsnext.php?id=133602"
    matches = []
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            events = r.json().get("events", []) or []
            for ev in events:
                home = ev.get("strHomeTeam")
                away = ev.get("strAwayTeam")
                league = ev.get("strLeague", "Soccer")
                date = ev.get("dateEvent", "")
                if home and away:
                    p_home, p_draw, p_away = calculate_probabilities()
                    matches.append({
                        "league": league,
                        "home": home,
                        "away": away,
                        "date": date,
                        "probabilities": {
                            "home_win_pct": p_home,
                            "draw_pct": p_draw,
                            "away_win_pct": p_away
                        }
                    })
    except Exception as e:
        print(f"TheSportsDB error: {e}")
    return matches

def run():
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y%m%d")
    tomorrow_str = (now_utc + timedelta(days=1)).strftime("%Y%m%d")

    # 1. Try FotMob for Today
    matches = fetch_from_fotmob(today_str)
    
    # 2. If quiet, add tomorrow's matches
    if len(matches) < 5:
        matches.extend(fetch_from_fotmob(tomorrow_str))

    # 3. If still empty, fall back to TheSportsDB
    if not matches:
        matches = fetch_from_thesportsdb()

    if not matches:
        send_telegram_alert("⚠️ *Predictor Alert*\nUnable to retrieve fixtures from global servers today.")
        return

    # Deduplicate
    unique = []
    seen = set()
    for m in matches:
        key = (m["home"], m["away"])
        if key not in seen:
            seen.add(key)
            unique.append(m)
    matches = unique

    # Save JSON to repository
    today_formatted = now_utc.strftime("%Y-%m-%d")
    os.makedirs("predictions", exist_ok=True)
    with open(f"predictions/{today_formatted}.json", "w") as f:
        json.dump(matches, f, indent=2)

    # Build Telegram Output
    header = (
        f"⚽ *GLOBAL FOOTBALL PREDICTIONS*\n"
        f"📅 Date: `{today_formatted}`\n"
        f"🔢 Fixtures Loaded: `{len(matches)}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
    )

    # Show first 20 matches cleanly
    match_entries = []
    for m in matches[:20]:
        p = m["probabilities"]
        entry = (
            f"🏆 *{m['league']}*\n"
            f"⚔️ *{m['home']}* vs *{m['away']}*\n"
            f"📊 1: `{p['home_win_pct']}%` | X: `{p['draw_pct']}%` | 2: `{p['away_win_pct']}%`\n"
        )
        match_entries.append(entry)

    full_message = header + "\n".join(match_entries)
    if len(matches) > 20:
        full_message += f"\n_...and {len(matches) - 20} more saved to repo._"

    send_telegram_alert(full_message)
    print(f"Success! {len(matches)} fixtures processed and dispatched.")

if __name__ == "__main__":
    run()
