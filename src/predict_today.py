import os
import json
from datetime import datetime, timezone
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

GITHUB_USERNAME = "shayanroyxyz"
GITHUB_REPO = "Football-Predictor"
PAGES_URL = f"https://{GITHUB_USERNAME}.github.io/{GITHUB_REPO}/"

# Priority keywords for global / continental tournaments
GLOBAL_PRIORITY_KEYWORDS = [
    "champions", "uefa", "europa", "libertadores", "nations", 
    "world cup", "fifa", "copa sudamericana", "afcon", "asian cup"
]

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram configuration missing.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=15)
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

    # Sort tournaments: Put UEFA/Global/Continental tournaments first
    def get_sport_priority(key_name):
        k = key_name.lower()
        for idx, word in enumerate(GLOBAL_PRIORITY_KEYWORDS):
            if word in k:
                return idx
        return 99

    soccer_keys.sort(key=get_sport_priority)

    matches = []
    for sport_key in soccer_keys[:12]:
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

                    league_title = ev.get("sport_title", "Soccer")
                    is_global = any(w in league_title.lower() for w in GLOBAL_PRIORITY_KEYWORDS)

                    matches.append({
                        "league": league_title,
                        "is_global": is_global,
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
        except Exception:
            continue

    return matches

def generate_web_dashboard(matches, date_str):
    """Creates a modern HTML dashboard for docs/index.html on GitHub Pages."""
    os.makedirs("docs", exist_ok=True)
    cards_html = ""
    for idx, m in enumerate(matches, 1):
        p = m["probabilities"]
        fav_class = "border-l-4 border-amber-500" if (p["home_win_pct"] >= 55 or p["away_win_pct"] >= 55) else "border-l-4 border-slate-700"
        badge = '<span class="bg-indigo-600 text-white text-xs px-2 py-0.5 rounded font-semibold">GLOBAL TOURNAMENT</span>' if m["is_global"] else ""
        
        cards_html += f"""
        <div class="bg-slate-800 rounded-xl p-4 shadow-md {fav_class}">
            <div class="flex justify-between items-center mb-2">
                <span class="text-xs font-semibold text-slate-400 uppercase tracking-wider">{m['league']}</span>
                {badge}
            </div>
            <div class="text-base font-bold text-slate-100 mb-3 flex items-center justify-between">
                <span>{m['home']}</span>
                <span class="text-xs text-slate-500 font-normal px-2">VS</span>
                <span>{m['away']}</span>
            </div>
            <div class="grid grid-cols-3 gap-2 text-center text-xs font-medium">
                <div class="bg-slate-900/60 p-2 rounded-lg">
                    <div class="text-slate-400 text-[10px] uppercase">1 ({m['home'][:10]})</div>
                    <div class="text-emerald-400 text-sm font-bold">{p['home_win_pct']}%</div>
                </div>
                <div class="bg-slate-900/60 p-2 rounded-lg">
                    <div class="text-slate-400 text-[10px] uppercase">X (Draw)</div>
                    <div class="text-amber-400 text-sm font-bold">{p['draw_pct']}%</div>
                </div>
                <div class="bg-slate-900/60 p-2 rounded-lg">
                    <div class="text-slate-400 text-[10px] uppercase">2 ({m['away'][:10]})</div>
                    <div class="text-sky-400 text-sm font-bold">{p['away_win_pct']}%</div>
                </div>
            </div>
            <div class="mt-2 text-[11px] text-slate-400 text-right">
                Market: {m['bookmaker']}
            </div>
        </div>
        """

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Global Football Match Predictions</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen py-8 px-4 font-sans">
    <div class="max-w-4xl mx-auto">
        <header class="mb-8 border-b border-slate-800 pb-5">
            <h1 class="text-3xl font-extrabold tracking-tight text-white flex items-center gap-2">
                ⚽ Global Football Match Predictions
            </h1>
            <p class="text-slate-400 text-sm mt-1">Generated: {date_str} (UTC) • Total Matches: {len(matches)}</p>
        </header>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            {cards_html}
        </div>
    </div>
</body>
</html>
"""
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html_content)

def run():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    matches = get_predictions_from_market()

    if not matches:
        send_telegram("⚠️ *Notice:* No active fixtures available right now.")
        return

    # Sort: Global tournaments first, then by highest win probability
    matches.sort(
        key=lambda m: (
            0 if m["is_global"] else 1,
            -max(m["probabilities"]["home_win_pct"], m["probabilities"]["away_win_pct"])
        )
    )

    # Save JSON database & build GitHub Pages Web Dashboard
    os.makedirs("predictions", exist_ok=True)
    with open(f"predictions/{now_str}.json", "w") as f:
        json.dump(matches, f, indent=2)

    generate_web_dashboard(matches, now_str)

    total = len(matches)

    # Top Value Picks
    top_picks = []
    for m in matches:
        p = m["probabilities"]
        if p["home_win_pct"] >= 55.0:
            top_picks.append(f"⭐ *{m['home']}* to WIN (`{p['home_win_pct']}%`)\n   ⚔️ vs {m['away']} ({m['league']})")
        elif p["away_win_pct"] >= 55.0:
            top_picks.append(f"⭐ *{m['away']}* to WIN (`{p['away_win_pct']}%`)\n   ⚔️ vs {m['home']} ({m['league']})")

    # Construct clean Telegram Message
    header = (
        f"⚽ *GLOBAL FOOTBALL PREDICTIONS*\n"
        f"📅 Date: `{now_str}`\n"
        f"🌍 *Upcoming Matches:* `{total}`\n"
        f"🌐 [Open Full Interactive Dashboard]({PAGES_URL})\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
    )

    if top_picks:
        header += "🔥 *TOP GLOBAL PICKS:*\n" + "\n\n".join(top_picks[:5]) + "\n\n━━━━━━━━━━━━━━━━━━━\n\n"

    # Send matches in Telegram with explicit win/draw breakdown
    batch = header
    shown = min(total, 25)

    for idx, m in enumerate(matches[:shown], start=1):
        p = m["probabilities"]
        badge = "🌍 " if m["is_global"] else ""
        entry = (
            f"*{idx}. {badge}{m['league']}*\n"
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
        batch += f"\n🔗 *View all {total} matches on your web page:*\n👉 {PAGES_URL}"
        send_telegram(batch)

    print(f"Successfully processed {total} matches and generated docs/index.html.")

if __name__ == "__main__":
    run()
