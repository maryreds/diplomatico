"""
semiconductor_report.py — Daily Semiconductor Intelligence Report

Fetches fresh semiconductor news (Mexico, nearshoring, global chip industry)
and combines it with background research data to produce a daily intelligence
briefing on Mexico's semiconductor ecosystem and Mexico-Malaysia opportunities.

Usage:
    python3 semiconductor_report.py              # Generate and send email
    python3 semiconductor_report.py --preview    # HTML preview only
"""

import argparse
import json
import os
import re
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from openai import OpenAI
import feedparser
import requests
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
TEMPLATE_DIR = SCRIPT_DIR / "templates"
OUTPUT_DIR = SCRIPT_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

TODAY = datetime.now().strftime("%B %d, %Y")
TODAY_ISO = datetime.now().strftime("%Y-%m-%d")
YESTERDAY_ISO = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


# ── Live News Fetching ────────────────────────────────────────────────────────

GOOGLE_NEWS_FEEDS = [
    # Mexico + semiconductors
    "https://news.google.com/rss/search?q=Mexico+semiconductor&hl=en&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Mexico+semiconductores&hl=es&gl=MX&ceid=MX:es",
    "https://news.google.com/rss/search?q=Mexico+chip+manufacturing+OR+nearshoring&hl=en&gl=US&ceid=US:en",
    # Key companies in Mexico
    "https://news.google.com/rss/search?q=Foxconn+Nvidia+Mexico+OR+Jalisco&hl=en&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Intel+Guadalajara+OR+Skyworks+Mexicali&hl=en&gl=US&ceid=US:en",
    # Mexico semiconductor policy
    "https://news.google.com/rss/search?q=Mexico+Kutsari+OR+%22Plan+Mexico%22+semiconductor&hl=en&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Mexico+nearshoring+chips+OR+electronics&hl=en&gl=US&ceid=US:en",
    # Malaysia semiconductors (for bilateral context)
    "https://news.google.com/rss/search?q=Malaysia+semiconductor+OSAT+OR+packaging&hl=en&gl=US&ceid=US:en",
    # Global semiconductor supply chain
    "https://news.google.com/rss/search?q=semiconductor+nearshoring+OR+reshoring+Latin+America&hl=en&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=CHIPS+Act+OR+semiconductor+trade+policy&hl=en&gl=US&ceid=US:en",
]

NEWSAPI_QUERIES = [
    "Mexico semiconductor",
    "Mexico chip nearshoring",
    "Malaysia semiconductor",
    "semiconductor supply chain ASEAN Latin America",
]


def fetch_google_news() -> list[dict]:
    """Fetch articles from Google News RSS feeds."""
    articles = []
    seen_titles = set()

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    for feed_url in GOOGLE_NEWS_FEEDS:
        try:
            resp = requests.get(feed_url, headers=headers, timeout=15)
            feed = feedparser.parse(resp.text)
            for entry in feed.entries[:10]:
                title = entry.get("title", "").strip()
                title_key = re.sub(r"\s+", " ", title.lower())[:80]
                if title_key in seen_titles:
                    continue
                seen_titles.add(title_key)

                source = "Unknown"
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    title = parts[0].strip()
                    source = parts[1].strip()

                articles.append({
                    "title": title,
                    "source": source,
                    "url": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "origin": "google_news",
                })
        except Exception as e:
            print(f"[news] Warning: Failed to fetch {feed_url[:60]}... — {e}")

    return articles


def fetch_newsapi() -> list[dict]:
    """Fetch articles from NewsAPI (if key is available)."""
    api_key = os.getenv("NEWSAPI_KEY")
    if not api_key:
        return []

    articles = []
    seen_titles = set()

    for query in NEWSAPI_QUERIES:
        try:
            resp = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "from": YESTERDAY_ISO,
                    "to": TODAY_ISO,
                    "sortBy": "relevancy",
                    "pageSize": 10,
                    "apiKey": api_key,
                },
                timeout=15,
            )
            data = resp.json()
            for art in data.get("articles", []):
                title = art.get("title", "").strip()
                title_key = re.sub(r"\s+", " ", title.lower())[:80]
                if title_key in seen_titles:
                    continue
                seen_titles.add(title_key)

                articles.append({
                    "title": title,
                    "source": art.get("source", {}).get("name", "Unknown"),
                    "description": art.get("description", ""),
                    "url": art.get("url", ""),
                    "published": art.get("publishedAt", ""),
                    "origin": "newsapi",
                })
        except Exception as e:
            print(f"[newsapi] Warning: Query '{query}' failed — {e}")

    return articles


def fetch_all_news() -> list[dict]:
    """Combine all news sources and deduplicate."""
    google = fetch_google_news()
    newsapi = fetch_newsapi()
    all_articles = google + newsapi

    print(f"[news] Fetched {len(google)} from Google News, {len(newsapi)} from NewsAPI")
    print(f"[news] Total unique articles: {len(all_articles)}")
    return all_articles


# ── Background Research Data ──────────────────────────────────────────────────

RESEARCH_CONTEXT = """
## VERIFIED RESEARCH DATA — Mexico's Semiconductor Industry (March 2026)

### Market Overview
- Mexico's semiconductor market: USD 10.41 billion (2024), projected USD 18.41 billion by 2033 (CAGR 6.54%)
- Electronics Manufacturing Services in Mexico: USD 53.2B (2025) → USD 97.4B (2031)
- Mexico ranked 17th largest exporter of semiconductor devices globally (2023), ~0.8% of global export value
- Government goal under Plan Mexico: double semiconductor exports by 2030
- Mexico imports >USD 23.5 billion in semiconductors annually
- Mexico graduates 110,000–130,000 engineers annually; 26% of graduates from STEM fields
- Critical gap: Mexico has NO fabs and NO OSAT facilities currently

### Key Companies in Mexico

1. **Intel** — Guadalajara, Jalisco
   - Guadalajara Design Center: ~1,800 engineers, 104,000 sq meter facility, LEED Gold
   - Activities: chip design, testing, validation, R&D
   - USD 177M investment in design center

2. **Foxconn / Nvidia** — Tonalá, Jalisco
   - USD 900M mega-plant for GB200 NVL72 AI superchip assembly
   - World's largest GB200 production facility, completion 2026
   - Producing servers for Project Stargate (OpenAI)
   - 64,000 chips housed by end of 2026

3. **Skyworks Solutions** — Mexicali, Baja California
   - 3,600+ employees, assembly/test/finishing for RF analog semiconductors + R&D
   - Won Mexico's National Export Award and National Technology & Innovation Award

4. **Texas Instruments** — Aguascalientes
   - Major manufacturing, assembly, and testing operations

5. **Infineon Technologies** — Jalisco
   - Assembly and testing operations

6. **NXP Semiconductors** — Mexico (subsidiary: NXP Semiconductors Mexico, S. de R.L. de C.V.)

7. **ON Semiconductor** — Mexico operations confirmed

8. **Qualcomm** — Baja California, design operations

9. **SK Hynix, Micron, ASE Group, Bosch** — Jalisco operations

10. **QSM Semiconductor** — USD 12M investment, new plant, operations beginning 2025

11. **Lenovo** — Nuevo León, electronics manufacturing

NOTE: No major Mexican-owned semiconductor companies exist yet. The Kutsari initiative aims to foster 10 Jalisco-based semiconductor design startups by 2030.

### States / Semiconductor Hubs

1. **Jalisco** — "Silicon Valley de México"
   - 600+ electronics/IT companies, premier semiconductor hub
   - Players: Intel, Foxconn/Nvidia, Infineon, Bosch, SK Hynix, NXP, ASE, Micron
   - FDI (1999–2024): USD 3.82 billion (highest)
   - New: Chip Design Park in Zapopan (18M pesos initial → 50M pesos permanent facility)
   - Goal: 3,000 semiconductor design engineers, 10 startups, 3x FDI by 2030

2. **Baja California** (Tijuana, Mexicali)
   - Main electronics manufacturing center
   - Players: Skyworks (3,600 employees), Foxconn, Qualcomm
   - FDI (1999–2024): USD 2.96 billion (second)
   - ASU–Tec de Monterrey semiconductor workforce training partnership

3. **Chihuahua** (Ciudad Juárez)
   - Major electronics manufacturing on US border
   - Players: Foxconn, various OEMs
   - FDI (1999–2024): USD 2.13 billion (third)

4. **Nuevo León** (Monterrey)
   - Emerging high-tech hub; industrial/business center
   - Preparing two tech development hubs in Pesquería and Colombia municipalities
   - Players: Lenovo, various tech firms

5. **Aguascalientes**
   - Key manufacturing hub in El Bajío
   - Players: Texas Instruments
   - Second-highest income among municipalities in semiconductor manufacturing

6. **Querétaro**
   - Growing high-tech hub with logistics connectivity
   - Assembly, testing, packaging; part of Bajío electronics corridor

7. **Sonora & Puebla** — Designated sites for Kutsari National Semiconductor Design Center hubs

### Government Policy

- **Jan 2025**: Sheinbaum presidential decree — tax incentives for semiconductor nearshoring (deductions for equipment investment, employee training)
- **Feb 2025**: Launch of Kutsari Project (from Purépecha word for "sand"/silicon):
  - National Semiconductor Design Center (Jalisco, Puebla, Sonora)
  - Accelerated Training Program for Semiconductor Designers
  - Fast-track patent registration reforms
  - Phase 1 (2024–2027): Design centers and chip design hubs
  - Phase 2 (2027–2030): Wafer fabrication for mature process nodes
- **Plan Mexico**: Double semiconductor exports and employment by 2030

### Mexico-Malaysia Bilateral Semiconductor Data
- Malaysia exports ~USD 993M in chipsets to Mexico
- Electronic integrated circuits: Mexico's main export TO Malaysia (USD 151M) AND main import FROM Malaysia (USD 6.03B)
- Trade heavily skewed toward Malaysian exports to Mexico
- Both are CPTPP members (preferential trade framework)
- 50 years of diplomatic relations commemorated in 2024
- Malaysia controls ~13% of global OSAT market, packages ~26% of US chips
- Complementarity: Mexico's design + ATP strengths ↔ Malaysia's OSAT + packaging leadership

### Risk Factors
- No fabs or OSAT facilities in Mexico
- Infrastructure gaps: water, energy reliability in some regions
- USMCA 2026 review uncertainty
- Competition from Malaysia, Vietnam, India, Poland for semiconductor FDI
"""


ANALYSIS_PROMPT = """You are an intelligence analyst preparing a DAILY semiconductor intelligence
report for the Mexican Ambassador to Malaysia. Write the report IN SPANISH.

You have two inputs:
1. TODAY'S NEWS — fresh articles from today about semiconductors, Mexico nearshoring, Malaysia chips, and global supply chain developments.
2. BACKGROUND RESEARCH — standing reference data on Mexico's semiconductor ecosystem (companies, states, policies, bilateral data with Malaysia).

Produce a structured JSON report that leads with what's NEW today, contextualized by the background data.

## Output valid JSON with this exact structure:

{{
  "key_stats": [
    {{"value": "USD 10.4B", "label": "Mercado 2024"}},
    {{"value": "USD 18.4B", "label": "Proyección 2033"}},
    {{"value": "130K", "label": "Ingenieros/año"}}
  ],

  "overview": "2-3 sentence executive overview in Spanish. Lead with the most important news developments today, then frame them within Mexico's semiconductor landscape.",

  "companies_intro": "1 sentence in Spanish. If today's news mentions specific companies, highlight that; otherwise introduce the section normally.",

  "companies": [
    {{
      "name": "Company Name",
      "location": "City, State",
      "description": "1 concise sentence in Spanish. Incorporate any fresh news about this company if available, otherwise use background data.",
      "tags": [{{"label": "Diseño", "class": ""}}, {{"label": "IED USD 900M", "class": "investment"}}]
    }}
  ],

  "states_intro": "1 sentence in Spanish introducing the states section.",

  "states": [
    {{
      "name": "State Name",
      "nickname": "Optional nickname like Silicon Valley de México",
      "description": "1-2 sentences in Spanish about the state's semiconductor ecosystem. Incorporate any fresh news.",
      "fdi": "USD 3.82 mil millones",
      "tier": ""
    }}
  ],

  "policies": [
    {{
      "date": "Marzo 2026 (or relevant date)",
      "title": "Policy title in Spanish",
      "description": "1-2 sentences in Spanish. Prioritize NEW policy developments from today's news; include standing policies as context."
    }}
  ],

  "bilateral_intro": "2 sentences in Spanish about why Mexico-Malaysia semiconductor cooperation matters, referencing any fresh developments.",

  "opportunities": [
    {{
      "title": "Opportunity title in Spanish",
      "text": "2-3 sentences explaining the bilateral opportunity."
    }}
  ],

  "risks": [
    {{
      "icon": "⚠️",
      "level": "red or '' (amber)",
      "title": "Risk title in Spanish",
      "text": "1-2 sentences explaining the risk. Flag any NEW risks from today's news."
    }}
  ]
}}

## Guidelines:
- Write ALL content in Spanish (professional diplomatic register)
- PRIORITIZE today's news — the report should feel fresh and timely, not like a static reference
- Use background data to contextualize and enrich the news, not as the main content
- If there's very little semiconductor news today, note that and focus on the most relevant background + broader trends
- Include the 6 most important companies (prioritize any with fresh news, then largest investments)
- Include 5 states (top hubs first, then 1-2 emerging)
- For states, use tier "" for top hubs and tier "tier2" for emerging ones
- Include 3-4 policies (prioritize new developments)
- Include 3-4 bilateral opportunities (focus on complementarity with Malaysia)
- Include 3-4 risk factors
- Tag classes for companies: "" (default green) for design/R&D, "foreign" (blue) for manufacturing, "investment" (red) for major investments
- Be specific with numbers, data, and company details
- Keep ALL descriptions concise: 1-2 sentences max per item
- RETURN ONLY VALID JSON, no markdown fences

## TODAY'S NEWS:

{articles}

## BACKGROUND RESEARCH DATA:

{research}
"""


def generate_report(articles: list[dict]) -> dict:
    """Use Claude to analyze fresh news + background research and produce structured report."""
    client = OpenAI()

    # Format articles for the prompt
    articles_text = ""
    for i, art in enumerate(articles[:40], 1):
        desc = art.get("description", "")
        articles_text += f"\n[{i}] {art['title']}\n"
        articles_text += f"    Source: {art['source']}\n"
        if desc:
            articles_text += f"    Description: {desc}\n"
        articles_text += f"    Published: {art.get('published', 'Unknown')}\n"

    if not articles_text.strip():
        articles_text = "(No fresh semiconductor news found today. Generate the report using background data and note the quiet news day.)"

    prompt = ANALYSIS_PROMPT.format(articles=articles_text, research=RESEARCH_CONTEXT)

    print("[openai] Generating semiconductor intelligence report...")
    message = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.choices[0].message.content.strip()
    response_text = re.sub(r"^```json\s*", "", response_text)
    response_text = re.sub(r"\s*```$", "", response_text)

    try:
        return json.loads(response_text)
    except json.JSONDecodeError as e:
        print(f"[openai] Warning: Failed to parse JSON — {e}")
        print(f"[openai] Raw response:\n{response_text[:500]}")
        return {}


def render_html(report: dict) -> str:
    """Render the report into HTML."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    template = env.get_template("semiconductor_report.html")

    return template.render(
        date=TODAY,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        key_stats=report.get("key_stats", []),
        overview=report.get("overview", ""),
        companies_intro=report.get("companies_intro", ""),
        companies=report.get("companies", []),
        states_intro=report.get("states_intro", ""),
        states=report.get("states", []),
        policies=report.get("policies", []),
        bilateral_intro=report.get("bilateral_intro", ""),
        opportunities=report.get("opportunities", []),
        risks=report.get("risks", []),
    )


def send_email(html_body: str) -> bool:
    """Send the report email via Gmail SMTP."""
    from_addr = os.getenv("EMAIL_FROM", "")
    to_raw = os.getenv("EMAIL_TO", "")
    password = os.getenv("EMAIL_PASSWORD", "")
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))

    if not all([from_addr, to_raw, password]):
        print("[email] Missing EMAIL_FROM, EMAIL_TO, or EMAIL_PASSWORD — skipping send.")
        return False

    to_addrs = [a.strip() for a in to_raw.split(",") if a.strip()]
    subject = f"🇲🇽 Semiconductores en México — {TODAY}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Briefing Diplomático <{from_addr}>"
    msg["To"] = ", ".join(to_addrs)

    plain = f"Informe Especial: Industria de Semiconductores en México — {TODAY}"
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(from_addr, password)
            server.sendmail(from_addr, to_addrs, msg.as_string())
        print(f"[email] Sent to {', '.join(to_addrs)}")
        return True
    except Exception as e:
        print(f"[email] Failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Semiconductor Special Report")
    parser.add_argument("--preview", action="store_true", help="Save HTML preview only")
    args = parser.parse_args()

    print(f"{'='*55}")
    print(f"  Informe Diario: Semiconductores en México")
    print(f"  {TODAY}")
    print(f"{'='*55}\n")

    # 1. Fetch fresh news
    articles = fetch_all_news()

    # 2. Generate report with Claude (fresh news + background data)
    report = generate_report(articles)
    if not report:
        print("[error] Failed to generate report.")
        return

    # 3. Render HTML
    html = render_html(report)

    # 4. Save preview
    preview_path = OUTPUT_DIR / f"semiconductores-{TODAY_ISO}.html"
    preview_path.write_text(html, encoding="utf-8")
    print(f"[preview] Saved to {preview_path}")

    # 5. Send email (unless preview-only)
    if not args.preview:
        send_email(html)
    else:
        print("[preview] Preview mode — email not sent.")

    # 6. Copy to docs/ for GitHub Pages
    docs_path = SCRIPT_DIR / "docs" / "semiconductores.html"
    docs_path.write_text(html, encoding="utf-8")
    print(f"[docs] Saved to {docs_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
