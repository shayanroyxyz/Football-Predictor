import os
import json
from datetime import datetime, timezone
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ODDS_API_KEY_ENV = os.getenv("ODDS_API_KEY", "")

# Support multiple API keys: separates by comma if you have more than one
API_KEYS = [k.strip() for k in ODDS_API_KEY_ENV.split(",") if k.strip()]

GITHUB_USERNAME = "shayanroyxyz"
GITHUB_REPO = "Football-Predictor"
PAGES_URL = "https://football-predictor-croi-sigma.vercel.app"
TRIGGER_URL = f"https://github.com/{GITHUB_USERNAME}/{GITHUB_REPO}/actions/workflows/daily.yml"

# Tracking quotas
CREDITS_LEFT = "N/A"
CREDITS_USED = "N/A"

# Tournament Priority & Asian league identifiers
ASIAN_KEYWORDS = [
    "asia", "afc", "asian cup", "japan", "j_league", "j-league", 
    "korea", "kleague", "k-league", "china", "csl", "superleague", 
    "saudi", "pro league", "australia", "a-league", "aleague", 
    "india", "isl", "singapore", "thailand", "vietnam", "iran", 
    "qatar", "uae", "gulf"
]

GLOBAL_CUP_KEYWORDS = [
    "champions", "uefa", "europa", "libertadores", "nations", 
    "world cup", "fifa", "copa sudamericana", "afcon"
]

def format_commence_time(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y"), dt.strftime("%H:%M UTC")
    except Exception:
        return "Upcoming", "TBD"

def send_telegram(message):
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
                    {"text": "🌐 Open Web Dashboard", "url": PAGES_URL}
                ]
            ]
        }
    }
    try:
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}")

def api_get(endpoint_path):
    """Tries the API call across available keys; tracks remaining credits."""
    global CREDITS_LEFT, CREDITS_USED
    for key in API_KEYS:
        url = f"https://api.the-odds-api.com/v4/{endpoint_path}&apiKey={key}" if "?" in endpoint_path else f"https://api.the-odds-api.com/v4/{endpoint_path}?apiKey={key}"
        try:
            r = requests.get(url, timeout=15)
            # Fetch remaining credits from response headers
            rem = r.headers.get("x-requests-remaining")
            usd = r.headers.get("x-requests-used")
            if rem is not None:
                CREDITS_LEFT = rem
            if usd is not None:
                CREDITS_USED = usd

            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429 or (rem is not None and int(rem) <= 0):
                print(f"Key {key[:6]}... exhausted. Trying next key if available.")
                continue
        except Exception:
            continue
    return None

def get_predictions_from_market():
    if not API_KEYS:
        print("Error: No ODDS_API_KEY set.")
        return []

    all_sports = api_get("sports")
    if not all_sports or not isinstance(all_sports, list):
        return []

    soccer_keys = [s["key"] for s in all_sports if s.get("group") == "Soccer" and s.get("active")]

    def get_sport_priority(key_name):
        k = key_name.lower()
        for idx, word in enumerate(ASIAN_KEYWORDS):
            if word in k:
                return idx
        for idx, word in enumerate(GLOBAL_CUP_KEYWORDS):
            if word in k:
                return 50 + idx
        return 99

    soccer_keys.sort(key=get_sport_priority)

    matches = []
    # Query up to 18 active competitions
    for sport_key in soccer_keys[:18]:
        endpoint = f"sports/{sport_key}/odds/?regions=eu,uk,au&markets=h2h&oddsFormat=decimal"
        events = api_get(endpoint)
        if not events or not isinstance(events, list):
            continue

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

                full_text = f"{league_title} {sport_key} {home} {away}".lower()
                is_asian = any(w in full_text for w in ASIAN_KEYWORDS)
                is_global = is_asian or any(w in full_text for w in GLOBAL_CUP_KEYWORDS)

                matches.append({
                    "league": league_title,
                    "is_asian": is_asian,
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

    return matches

def generate_full_dashboard(matches, date_str):
    os.makedirs("docs", exist_ok=True)
    matches_json_string = json.dumps(matches)

    asian_count = sum(1 for m in matches if m.get("is_asian"))
    global_count = sum(1 for m in matches if m.get("is_global"))

    html_parts = [
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n',
        '  <meta charset="UTF-8" />\n',
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n',
        '  <title>Football Match Predictions</title>\n',
        '  <script src="https://cdn.tailwindcss.com"></script>\n',
        '  <link rel="preconnect" href="https://fonts.googleapis.com">\n',
        '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n',
        '  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">\n',
        '  <style>body { font-family: "Inter", sans-serif; }</style>\n',
        '</head>\n',
        '<body class="bg-slate-950 text-slate-100 min-h-screen pb-16 antialiased">\n\n',
        '  <header class="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-50 px-4 py-4">\n',
        '    <div class="max-w-6xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">\n',
        '      <div class="flex items-center gap-3">\n',
        '        <span class="text-3xl">⚽</span>\n',
        '        <div>\n',
        '          <h1 class="text-xl font-bold tracking-tight text-white">Football Match Predictions</h1>\n',
        f'          <p class="text-xs text-slate-400">Date: {date_str} (UTC) • Total: {len(matches)} Fixtures • API Left: {CREDITS_LEFT}</p>\n',
        '        </div>\n',
        '      </div>\n\n',
        '      <div class="w-full md:w-96">\n',
        '        <div class="relative">\n',
        '          <input type="text" id="searchInput" placeholder="Search team, league, AFC, Asia..." \n',
        '                 class="w-full bg-slate-950 border border-slate-700 text-xs sm:text-sm rounded-lg pl-9 pr-4 py-2.5 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 shadow-inner" />\n',
        '          <svg class="w-4 h-4 text-slate-500 absolute left-3 top-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">\n',
        '            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>\n',
        '          </svg>\n',
        '        </div>\n',
        '      </div>\n',
        '    </div>\n',
        '  </header>\n\n',
        '  <main class="max-w-6xl mx-auto px-4 mt-6">\n',
        '    <div class="flex flex-wrap items-center justify-between gap-2 mb-6">\n',
        f'      <div id="matchSummary" class="text-xs font-semibold text-slate-400">Showing all {len(matches)} fixtures</div>\n',
        '      <div class="flex flex-wrap gap-2">\n',
        f'        <button id="filterAll" class="px-3 py-1.5 text-xs rounded-lg font-medium bg-indigo-600 text-white">All ({len(matches)})</button>\n',
        f'        <button id="filterAsian" class="px-3 py-1.5 text-xs rounded-lg font-medium bg-slate-800 text-slate-300 hover:bg-slate-700">🌏 Asian / AFC ({asian_count})</button>\n',
        f'        <button id="filterGlobal" class="px-3 py-1.5 text-xs rounded-lg font-medium bg-slate-800 text-slate-300 hover:bg-slate-700">🌍 Global Cups ({global_count})</button>\n',
        '        <button id="filterPicks" class="px-3 py-1.5 text-xs rounded-lg font-medium bg-slate-800 text-slate-300 hover:bg-slate-700">⭐ Top Picks</button>\n',
        '      </div>\n',
        '    </div>\n\n',
        '    <div id="dateGroupsContainer" class="space-y-8"></div>\n\n',
        '    <div id="noResults" class="hidden text-center py-20">\n',
        '      <p class="text-slate-400 text-sm">No matches found matching your search.</p>\n',
        '    </div>\n',
        '  </main>\n\n',
        '  <script>\n',
        f'    const rawMatches = {matches_json_string};\n',
        '''    let currentFilter = 'all';

    function groupMatchesByDate(matches) {
      return matches.reduce((acc, match) => {
        const d = match.match_date || "Upcoming Fixtures";
        if (!acc[d]) acc[d] = [];
        acc[d].push(match);
        return acc;
      }, {});
    }

    function renderGroupedMatches(matches) {
      const container = document.getElementById("dateGroupsContainer");
      const noResults = document.getElementById("noResults");
      const summary = document.getElementById("matchSummary");

      container.innerHTML = "";
      summary.textContent = `Showing ${matches.length} fixtures across scheduled dates`;

      if (matches.length === 0) {
        noResults.classList.remove("hidden");
        return;
      }
      noResults.classList.add("hidden");

      const grouped = groupMatchesByDate(matches);

      for (const [dateStr, matchGroup] of Object.entries(grouped)) {
        const section = document.createElement("section");
        section.className = "border border-slate-800 bg-slate-900/40 rounded-2xl p-4 sm:p-5";

        const heading = document.createElement("div");
        heading.className = "flex items-center gap-2 mb-4 pb-3 border-b border-slate-800/80";
        heading.innerHTML = `
          <span class="text-amber-400 text-lg">🗓️</span>
          <h2 class="text-sm sm:text-base font-bold text-white tracking-wide uppercase">${dateStr}</h2>
          <span class="text-xs bg-slate-800 text-slate-400 px-2 py-0.5 rounded-full font-medium ml-auto">${matchGroup.length} Matches</span>
        `;
        section.appendChild(heading);

        const grid = document.createElement("div");
        grid.className = "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3";

        matchGroup.forEach(m => {
          const p = m.probabilities || { home_win_pct: 33.3, draw_pct: 33.3, away_win_pct: 33.3 };
          const isHigh = (p.home_win_pct >= 55 || p.away_win_pct >= 55);
          const favBorder = isHigh ? "border-amber-500/60" : "border-slate-800";
          
          let tagHtml = "";
          if (m.is_asian) {
            tagHtml = `<span class="bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-[9px] px-1.5 py-0.5 rounded font-bold uppercase">ASIA / AFC</span>`;
          } else if (m.is_global) {
            tagHtml = `<span class="bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 text-[9px] px-1.5 py-0.5 rounded font-bold uppercase">GLOBAL</span>`;
          }

          const card = document.createElement("div");
          card.className = `bg-slate-900 border ${favBorder} rounded-xl p-3.5 flex flex-col justify-between hover:border-slate-700 transition`;
          card.innerHTML = `
            <div>
              <div class="flex items-center justify-between mb-1.5">
                <span class="text-[11px] font-semibold text-slate-400 truncate uppercase tracking-wider">${m.league}</span>
                ${tagHtml}
              </div>
              <div class="text-[11px] text-amber-400 font-medium mb-2.5">⏰ ${m.match_time || "TBD"}</div>
              <div class="text-xs sm:text-sm font-bold text-white mb-3 flex items-center justify-between gap-2">
                <span class="truncate w-5/12 text-left">${m.home}</span>
                <span class="text-[10px] text-slate-500 font-normal w-2/12 text-center">VS</span>
                <span class="truncate w-5/12 text-right">${m.away}</span>
              </div>
              <div class="grid grid-cols-3 gap-1.5 text-center text-xs font-semibold mb-2">
                <div class="bg-slate-950 p-2 rounded-lg border border-slate-800/80">
                  <div class="text-slate-400 text-[9px] uppercase truncate">${m.home}</div>
                  <div class="text-emerald-400 text-xs font-bold">${p.home_win_pct}%</div>
                </div>
                <div class="bg-slate-950 p-2 rounded-lg border border-slate-800/80">
                  <div class="text-slate-400 text-[9px] uppercase">Draw</div>
                  <div class="text-amber-400 text-xs font-bold">${p.draw_pct}%</div>
                </div>
                <div class="bg-slate-950 p-2 rounded-lg border border-slate-800/80">
                  <div class="text-slate-400 text-[9px] uppercase truncate">${m.away}</div>
                  <div class="text-sky-400 text-xs font-bold">${p.away_win_pct}%</div>
                </div>
              </div>
            </div>
            <div class="text-[10px] text-slate-500 pt-2 border-t border-slate-800/70 flex justify-between">
              <span>Source: ${m.bookmaker || "Market"}</span>
              <span class="text-indigo-400 font-medium">${isHigh ? (p.home_win_pct >= 55 ? m.home : m.away) + " to WIN" : "Balanced"}</span>
            </div>
          `;
          grid.appendChild(card);
        });

        section.appendChild(grid);
        container.appendChild(section);
      }
    }

    function applyFilterAndSearch() {
      const q = document.getElementById("searchInput").value.toLowerCase().trim();
      const filtered = rawMatches.filter(m => {
        const text = `${m.home} ${m.away} ${m.league} ${m.match_date}`.toLowerCase();
        const matchesQuery = text.includes(q);
        if (!matchesQuery) return false;
        if (currentFilter === 'asian') return m.is_asian;
        if (currentFilter === 'global') return m.is_global;
        if (currentFilter === 'picks') return (m.probabilities?.home_win_pct >= 55 || m.probabilities?.away_win_pct >= 55);
        return true;
      });
      renderGroupedMatches(filtered);
    }

    document.getElementById("searchInput").addEventListener("input", applyFilterAndSearch);

    const btns = {
      all: document.getElementById("filterAll"),
      asian: document.getElementById("filterAsian"),
      global: document.getElementById("filterGlobal"),
      picks: document.getElementById("filterPicks")
    };

    Object.entries(btns).forEach(([key, btn]) => {
      btn.addEventListener("click", () => {
        currentFilter = key;
        Object.values(btns).forEach(b => {
          b.className = "px-3 py-1.5 text-xs rounded-lg font-medium bg-slate-800 text-slate-300 hover:bg-slate-700";
        });
        btn.className = "px-3 py-1.5 text-xs rounded-lg font-medium bg-indigo-600 text-white";
        applyFilterAndSearch();
      });
    });

    renderGroupedMatches(rawMatches);
  </script>
</body>
</html>
'''
    ]

    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write("".join(html_parts))

def run():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    matches = get_predictions_from_market()

    if not matches:
        send_telegram("⚠️ *Notice:* No active fixtures available right now.")
        return

    # Chronological sort
    matches.sort(key=lambda m: (m.get("commence_time") or ""))

    os.makedirs("predictions", exist_ok=True)
    with open(f"predictions/{now_str}.json", "w") as f:
        json.dump(matches, f, indent=2)

    generate_full_dashboard(matches, now_str)

    total = len(matches)

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
        f"⚽ *GLOBAL & ASIAN FOOTBALL PREDICTIONS*\n"
        f"📅 Date: `{now_str}`\n"
        f"💳 *API Quota Left:* `{CREDITS_LEFT}` remaining\n"
        f"🌍 *Upcoming Matches Found:* `{total}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
    )

    if top_picks:
        header += "🔥 *TOP VALUE PICKS:*\n" + "\n\n".join(top_picks[:5]) + "\n\n━━━━━━━━━━━━━━━━━━━\n\n"

    batch = header
    shown = min(total, 25)

    for idx, m in enumerate(matches[:shown], start=1):
        p = m["probabilities"]
        badge = "🌏 " if m.get("is_asian") else ("🌍 " if m.get("is_global") else "")
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
        batch += f"\n👉 Tap **🌐 Open Web Dashboard** below to filter matches by date & category."
        send_telegram(batch)

    print(f"Processed {total} matches. Quota remaining: {CREDITS_LEFT}")

if __name__ == "__main__":
    run()
