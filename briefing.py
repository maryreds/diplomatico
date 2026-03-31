"""
briefing.py — Daily Diplomatic Briefing Digest

Aggregates Mexico-Malaysia bilateral news, FX rates, and regional context,
then uses GPT-4o to produce an executive summary and priority alerts.
Sends a beautiful HTML email.

Usage:
    python briefing.py              # Run and send email
    python briefing.py --preview    # Generate HTML preview only (no email)
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


# ── News Fetching ──────────────────────────────────────────────────────────────

# Google News RSS feeds — no API key needed
GOOGLE_NEWS_FEEDS = [
    # Bilateral
    "https://news.google.com/rss/search?q=Mexico+Malaysia&hl=en&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Mexico+ASEAN&hl=en&gl=US&ceid=US:en",
    # Mexico in Malaysia context
    "https://news.google.com/rss/search?q=embajada+Mexico+Malasia&hl=es&gl=MX&ceid=MX:es",
    # Trade & economy
    "https://news.google.com/rss/search?q=Mexico+Malaysia+trade&hl=en&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Mexico+Southeast+Asia+trade&hl=en&gl=US&ceid=US:en",
    # Regional security & politics
    "https://news.google.com/rss/search?q=Malaysia+Latin+America&hl=en&gl=US&ceid=US:en",
    # Mexican nationals abroad
    "https://news.google.com/rss/search?q=mexicanos+Malasia&hl=es&gl=MX&ceid=MX:es",
    # Key sectors
    "https://news.google.com/rss/search?q=Mexico+Malaysia+semiconductor+OR+palm+oil+OR+automotive&hl=en&gl=US&ceid=US:en",
]

# NewsAPI queries (if key is available)
NEWSAPI_QUERIES = [
    "Mexico AND Malaysia",
    "Mexico AND ASEAN",
    "Mexican embassy",
    "Mexico trade Southeast Asia",
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
                # Deduplicate
                title_key = re.sub(r"\s+", " ", title.lower())[:80]
                if title_key in seen_titles:
                    continue
                seen_titles.add(title_key)

                # Parse source from title (Google News appends " - Source")
                source = "Unknown"
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    title = parts[0].strip()
                    source = parts[1].strip()

                pub_date = entry.get("published", "")
                link = entry.get("link", "")

                articles.append({
                    "title": title,
                    "source": source,
                    "url": link,
                    "published": pub_date,
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


# ── FX Rates ───────────────────────────────────────────────────────────────────

def fetch_fx_rates() -> list[dict]:
    """Fetch MXN/MYR, MXN/USD, and USD/MYR exchange rates."""
    rates = []
    pairs = [
        ("MXN", "MYR", "MXN/MYR"),
        ("USD", "MXN", "USD/MXN"),
        ("USD", "MYR", "USD/MYR"),
    ]

    for base, target, label in pairs:
        try:
            # Using the free exchangerate.host API
            resp = requests.get(
                f"https://open.er-api.com/v6/latest/{base}",
                timeout=10,
            )
            data = resp.json()
            if data.get("result") == "success":
                rate_val = data["rates"].get(target, 0)
                rates.append({
                    "pair": label,
                    "rate": f"{rate_val:.4f}" if rate_val < 10 else f"{rate_val:.2f}",
                    "change": 0.0,  # Free API doesn't provide change; could cache yesterday's
                })
        except Exception as e:
            print(f"[fx] Warning: Failed to fetch {label} — {e}")
            rates.append({"pair": label, "rate": "N/A", "change": 0.0})

    return rates


# ── OpenAI Summarization ──────────────────────────────────────────────────────

BRIEFING_PROMPT = """You are a diplomatic intelligence analyst preparing a daily briefing
for the Mexican Ambassador to Malaysia. Analyze the following news articles and produce
a structured briefing.

## Your output must be valid JSON with this exact structure:

{{
  "executive_summary": "2-3 sentence overview of the most important developments for Mexico-Malaysia bilateral relations today.",

  "alerts": [
    {{
      "icon": "🔴 or 🟡 or 🟢",
      "title": "Short alert title",
      "text": "1-2 sentence explanation of why this matters for the embassy.",
      "positive": false
    }}
  ],

  "categories": [
    {{
      "name": "Category name (e.g., Bilateral Relations, Trade & Economy, Regional/ASEAN, Consular & Diaspora, Culture & Soft Power)",
      "stories": [
        {{
          "headline": "Clear headline",
          "source": "Source name",
          "summary": "2-3 sentence summary focused on relevance to the ambassador."
        }}
      ]
    }}
  ]
}}

## Guidelines:
- Focus on what matters to a DIPLOMAT: bilateral relations, trade, consular issues, diaspora, cultural exchange, regional politics
- Flag anything requiring embassy action (consular emergencies, VIP visits, trade disputes)
- If articles are not relevant to Mexico-Malaysia relations, skip them
- Use 🔴 for urgent/negative alerts, 🟡 for notable, 🟢 for positive opportunities
- Set "positive": true for green alerts
- Group stories into 3-5 categories maximum
- If there's very little news, note that in the summary and include broader ASEAN-LatAm context
- Write in English but feel free to include key Spanish terms where appropriate
- RETURN ONLY VALID JSON, no markdown code fences

## Articles to analyze:

{articles}
"""


def analyze_with_claude(articles: list[dict]) -> dict:
    """Send articles to GPT-4o for analysis and structuring."""
    client = OpenAI()

    # Format articles for the prompt
    articles_text = ""
    for i, art in enumerate(articles[:30], 1):  # Cap at 30 most relevant articles
        desc = art.get("description", "")
        articles_text += f"\n[{i}] {art['title']}\n"
        articles_text += f"    Source: {art['source']}\n"
        if desc:
            articles_text += f"    Description: {desc}\n"
        articles_text += f"    Published: {art.get('published', 'Unknown')}\n"

    if not articles_text.strip():
        articles_text = "(No articles found today. Generate a briefing noting the quiet news day and suggest proactive diplomatic activities.)"

    prompt = BRIEFING_PROMPT.format(articles=articles_text)

    print("[openai] Analyzing articles...")
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = response.choices[0].message.content.strip()

    # Clean potential markdown fences
    response_text = re.sub(r"^```json\s*", "", response_text)
    response_text = re.sub(r"\s*```$", "", response_text)

    try:
        return json.loads(response_text)
    except json.JSONDecodeError as e:
        print(f"[openai] Warning: Failed to parse JSON — {e}")
        print(f"[openai] Raw response:\n{response_text[:500]}")
        return {
            "executive_summary": "Unable to parse briefing. Please check the raw output.",
            "alerts": [],
            "categories": [],
        }


# ── HTML Rendering ─────────────────────────────────────────────────────────────

def render_html(briefing: dict, rates: list[dict], story_count: int) -> str:
    """Render the briefing data into an HTML email."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    template = env.get_template("briefing_email.html")

    return template.render(
        date=TODAY,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        story_count=story_count,
        executive_summary=briefing.get("executive_summary", "No summary available."),
        rates=rates,
        alerts=briefing.get("alerts", []),
        categories=briefing.get("categories", []),
    )


# ── Email Delivery ─────────────────────────────────────────────────────────────

def send_email(html_body: str) -> bool:
    """Send the briefing email via Gmail SMTP."""
    from_addr = os.getenv("EMAIL_FROM", "")
    to_raw = os.getenv("EMAIL_TO", "")
    password = os.getenv("EMAIL_PASSWORD", "")
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))

    if not all([from_addr, to_raw, password]):
        print("[email] Missing EMAIL_FROM, EMAIL_TO, or EMAIL_PASSWORD — skipping send.")
        return False

    to_addrs = [a.strip() for a in to_raw.split(",") if a.strip()]
    subject = f"🇲🇽 Briefing Diplomático — {TODAY}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Briefing Diplomático <{from_addr}>"
    msg["To"] = ", ".join(to_addrs)

    plain = (
        f"Mexico-Malaysia Diplomatic Briefing — {TODAY}\n"
        "This email requires an HTML-capable client."
    )
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(from_addr, password)
            server.sendmail(from_addr, to_addrs, msg.as_string())
        print(f"[email] Sent to {', '.join(to_addrs)}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("[email] Auth failed. Use a Gmail App Password: myaccount.google.com/apppasswords")
        return False
    except Exception as e:
        print(f"[email] Failed: {e}")
        return False


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Diplomatic Briefing Digest")
    parser.add_argument("--preview", action="store_true", help="Save HTML preview only, don't email")
    args = parser.parse_args()

    print(f"{'='*50}")
    print(f"  Briefing Diplomático — {TODAY}")
    print(f"{'='*50}\n")

    # 1. Fetch news
    articles = fetch_all_news()

    # 2. Fetch FX rates
    rates = fetch_fx_rates()

    # 3. Analyze with GPT-4o
    briefing = analyze_with_claude(articles)

    # 4. Render HTML
    html = render_html(briefing, rates, len(articles))

    # 5. Save preview
    preview_path = OUTPUT_DIR / f"briefing-{TODAY_ISO}.html"
    preview_path.write_text(html, encoding="utf-8")
    print(f"[preview] Saved to {preview_path}")

    # 6. Send email (unless preview-only)
    if not args.preview:
        send_email(html)
    else:
        print("[preview] Preview mode — email not sent.")

    print("\nDone.")


if __name__ == "__main__":
    main()
