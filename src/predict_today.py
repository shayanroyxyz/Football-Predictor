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

def calculate_poisson_probabilities(home_exp=1.45, away_exp=1.15, max_goals=6):
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

def odds_to_implied_probabilities(home_odds, draw_odds, away_odds):
    try:
        raw_h = 1.0 / float(home_odds)
        raw_d = 1.0 / float(draw_odds)
        raw_a = 1.0 / float(away_odds)
        margin = raw_h + raw_d + raw_a
        fair_h = round((raw_h / margin) * 100, 1)
        fair_d = round((raw_d / margin) * 100, 1)
        fair_a = round((raw_a / margin) * 100, 1)
        return fair_h, fair_d, fair_a
    except Exception:
        return None

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not configured. Skipping alert.")
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
        print(f"Error sending to Telegram: {e}")

def fetch_espn_scoreboard(date_str):
    """Hits ESPN master soccer scoreboard across all world competitions."""
    matches = []
    # Query both the general soccer scoreboard and scorepanel endpoints
    urls = [
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/scoreboard?dates={date_str}&limit=300",
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/scorepanel?dates={date_str}"
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    seen_ids = set()
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            data = r.json()
            
            # Form 1: Direct events list
            events = data.get("events", [])
            
            # Form 2: Nested leagues -> events
            if not events:
                for lg in data.get("leagues", []):
                    events.extend(lg.get("events", []))

            for event in events:
                event_id = event.get("id")
                if event_id in seen_ids:
                    continue
                seen_ids.add(event_id)

                competitions = event.get("competitions", [])
                if not competitions:
                    continue
                comp = competitions[0]
                competitors = comp.get("competitors", [])
                if len(competitors) < 2:
                    continue

                home_team = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "home"), competitors[0]["team"]["displayName"])
                away_team = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "away"), competitors[1]["team"]["displayName"])
                league_name = event.get("season", {}).get("displayName") or comp.get("type", {}).get("text") or "World Football"

                # Check for live/pre-match odds
                odds_info = comp.get("odds", [])
                probs = None
                source_type = "Statistical Model"

                if odds_info:
                    odd_entry = odds_info[0]
                    home_dec = odd_entry.get("homeTeamOdds", {}).get("decimal")
                    away_dec = odd_entry.get("awayTeamOdds", {}).get("decimal")
                    draw_dec = odd_entry.get("drawOdds", {}).get("decimal")
                    if home_dec and away_dec and draw_dec:
                        probs = odds_to_implied_probabilities(home_dec, draw_dec, away_dec)
                        if probs:
                            source_type = "Consensus Market Odds"

                if not probs:
                    probs = calculate_poisson_probabilities()

                matches.append({
                    "league": league_name,
                    "home": home_team,
                    "away": away_team,
                    "date": event.get("date", ""),
                    "source": source_type,
                    "probabilities": {
                        "home_win_pct": probs[0],
                        "draw_pct": probs[1],
                        "away_win_pct": probs[2]
                    }
                })
        except Exception as e:
            print(f"Error reading from {url}: {e}")
            continue

    return matches

def run():
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y%m%d")
    tomorrow_str = (now_utc + timedelta(days=1)).strftime("%Y%m%d")

    # Fetch today and next 24h window
    matches = fetch_espn_scoreboard(today_str)
    if len(matches) < 5:
        # Also grab next day fixtures to catch evening games across timezones
        matches.extend(fetch_espn_scoreboard(tomorrow_str))

    # Remove potential duplicates
    unique_matches = []
    seen = set()
    for m in matches:
        key = (m["home"], m["away"])
        if key not in seen:
            seen.add(key)
            unique_matches.append(m)
    matches = unique_matches

    if not matches:
        send_telegram_alert("⚽ *Global Football Predictor*\nNo fixtures found for today.")
        return

    today_formatted = now_utc.strftime("%Y-%m-%d")
    out_file = f"predictions/{today_formatted}.json"
    os.makedirs("predictions", exist_ok=True)
    with open(out_file, "w") as f:
        json.dump(matches, f, indent=2)

    high_value_picks = []
    for m in matches:
        p = m["probabilities"]
        h_prob, a_prob = p["home_win_pct"], p["away_win_pct"]
        if h_prob >= 55.0:
            pick = f"⭐ *BET:* {m['home']} to WIN (`{h_prob}%` confidence)"
            high_value_picks.append((m, pick))
        elif a_prob >= 55.0:
            pick = f"⭐ *BET:* {m['away']} to WIN (`{a_prob}%` confidence)"
            high_value_picks.append((m, pick))

    messages = []
    
    # 1. High Confidence Header
    msg_header = f"🔥 *HIGH CONFIDENCE PICKS ({today_formatted})*\n\n"
    if high_value_picks:
        for m, pick in high_value_picks[:8]:
            p = m["probabilities"]
            msg_header += (
                f"🏆 *{m['league']}*\n"
                f"⚔️ {m['home']} vs {m['away']}\n"
                f"{pick}\n"
                f"📊 Probs: 1: `{p['home_win_pct']}%` | X: `{p['draw_pct']}%` | 2: `{p['away_win_pct']}%`\n"
                f"🔍 _Basis: {m['source']}_\n\n"
            )
    else:
        msg_header += "_No extreme single-team favorites today._\n\n"
    messages.append(msg_header)

    # 2. Complete Match List (batched)
    all_fixtures_str = f"📋 *TODAY'S GLOBAL FIXTURES ({len(matches)} total)*\n\n"
    for m in matches[:30]:  # Show top 30 to avoid Telegram flood
        p = m["probabilities"]
        entry = (
            f"🏆 *{m['league']}*\n"
            f"⚔️ {m['home']} vs {m['away']}\n"
            f"📊 1: `{p['home_win_pct']}%` | X: `{p['draw_pct']}%` | 2: `{p['away_win_pct']}%`\n\n"
        )
        if len(all_fixtures_str) + len(entry) > 3800:
            messages.append(all_fixtures_str)
            all_fixtures_str = entry
        else:
            all_fixtures_str += entry

    if all_fixtures_str.strip():
        messages.append(all_fixtures_str)

    for chunk in messages:
        send_telegram_alert(chunk)

    print(f"Processed {len(matches)} matches. Sent to Telegram.")

if __name__ == "__main__":
    run()
