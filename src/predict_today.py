import os
import math
import json
from datetime import datetime, timezone
import requests

API_KEY = os.getenv("FOOTBALL_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HEADERS = {"X-Auth-Token": API_KEY}
BASE_URL = "https://api.football-data.org/v4"

def poisson_pmf(k, lamb):
    if lamb <= 0:
        return 0.0
    return (math.pow(lamb, k) * math.exp(-lamb)) / math.factorial(k)

def calculate_match_probabilities(home_exp, away_exp, max_goals=6):
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
    return round(home_win * 100, 1), round(draw * 100, 1), round(away_win * 100, 1)

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets not set. Skipping notification.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            print("Telegram alert sent successfully.")
        else:
            print(f"Telegram failed: {r.text}")
    except Exception as e:
        print(f"Error sending to Telegram: {e}")

def run():
    if not API_KEY:
        print("ERROR: FOOTBALL_API_KEY environment variable is missing.")
        return

    url = f"{BASE_URL}/matches"
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        print(f"API Error {response.status_code}: {response.text}")
        return

    matches = response.json().get("matches", [])
    if not matches:
        print("No matches scheduled for today.")
        send_telegram_alert("⚽ *Daily Match Predictor*\nNo matches found for today.")
        return

    output = []
    telegram_lines = ["⚽ *Today's Football Predictions:*\n"]

    DEFAULT_HOME_EXP = 1.45
    DEFAULT_AWAY_EXP = 1.15

    for m in matches:
        home = m["homeTeam"]["name"]
        away = m["awayTeam"]["name"]
        comp = m["competition"]["name"]

        p_home, p_draw, p_away = calculate_match_probabilities(DEFAULT_HOME_EXP, DEFAULT_AWAY_EXP)

        output.append({
            "competition": comp,
            "match": f"{home} vs {away}",
            "date": m["utcDate"],
            "prediction": {
                "home_win_pct": p_home,
                "draw_pct": p_draw,
                "away_win_pct": p_away
            }
        })

        telegram_lines.append(
            f"🏆 *{comp}*\n"
            f"⚔️ {home} vs {away}\n"
            f"📊 1: `{p_home}%` | X: `{p_draw}%` | 2: `{p_away}%`\n"
        )

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_file = f"predictions/{today}.json"
    with open(out_file, "w") as f:
        json.dump(output, f, indent=2)

    full_message = "\n".join(telegram_lines)
    if len(full_message) > 4000:
        full_message = full_message[:3900] + "\n\n_...list truncated._"
    send_telegram_alert(full_message)

    print(f"Processed {len(output)} matches -> {out_file}")

if __name__ == "__main__":
    run()

