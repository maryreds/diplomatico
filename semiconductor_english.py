"""
semiconductor_english.py — One-off English version of the semiconductor report.
Sends only to Maria.
"""

import json
import os
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
TEMPLATE_DIR = SCRIPT_DIR / "templates"
OUTPUT_DIR = SCRIPT_DIR / "output"
TODAY = datetime.now().strftime("%B %d, %Y")
TODAY_ISO = datetime.now().strftime("%Y-%m-%d")

RESEARCH_CONTEXT = open(SCRIPT_DIR / "semiconductor_report.py").read().split('RESEARCH_CONTEXT = """')[1].split('"""')[0]

PROMPT = """You are an intelligence analyst preparing a special report on Mexico's semiconductor
industry for a US-based executive. Write the report IN ENGLISH.

Using the research data below, produce a structured JSON report.

## Output valid JSON with this exact structure:

{{
  "key_stats": [
    {{"value": "USD 10.4B", "label": "Market 2024"}},
    {{"value": "USD 18.4B", "label": "Projected 2033"}},
    {{"value": "130K", "label": "Engineers/year"}}
  ],
  "overview": "2-3 sentence executive overview of Mexico's semiconductor landscape and the nearshoring opportunity.",
  "companies_intro": "1 sentence introducing the companies section.",
  "companies": [
    {{
      "name": "Company Name",
      "location": "City, State",
      "description": "1 concise sentence about what they do in Mexico and their scale.",
      "tags": [{{"label": "Design", "class": ""}}, {{"label": "FDI USD 900M", "class": "investment"}}]
    }}
  ],
  "states_intro": "1 sentence introducing the states section.",
  "states": [
    {{
      "name": "State Name",
      "nickname": "Optional nickname like Mexico's Silicon Valley",
      "description": "1-2 sentences about the state's semiconductor ecosystem.",
      "fdi": "USD 3.82 billion",
      "tier": ""
    }}
  ],
  "policies": [
    {{
      "date": "January 2025",
      "title": "Policy title",
      "description": "1-2 sentences explaining the policy and its impact."
    }}
  ],
  "bilateral_intro": "2 sentences about why Mexico-Malaysia semiconductor cooperation matters.",
  "opportunities": [
    {{
      "title": "Opportunity title",
      "text": "1-2 sentences explaining the bilateral opportunity."
    }}
  ],
  "risks": [
    {{
      "icon": "⚠️",
      "level": "red or ''",
      "title": "Risk title",
      "text": "1-2 sentences explaining the risk."
    }}
  ]
}}

## Guidelines:
- Write ALL content in English (professional, executive tone)
- Include the 6 most important companies
- Include 5 states (top hubs first, then 1-2 emerging)
- Include 3-4 government policies
- Include 3-4 bilateral opportunities
- Include 3-4 risk factors
- Keep ALL descriptions concise: 1-2 sentences max
- RETURN ONLY VALID JSON, no markdown fences

## Research Data:

{research}
"""


def main():
    client = anthropic.Anthropic()

    print(f"Generating English semiconductor report...")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[{"role": "user", "content": PROMPT.format(research=RESEARCH_CONTEXT)}],
    )

    text = message.content[0].text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    report = json.loads(text)

    # Render using the same template (it works for both languages)
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    template = env.get_template("semiconductor_report.html")

    html = template.render(
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

    # Save preview
    preview_path = OUTPUT_DIR / f"semiconductores-english-{TODAY_ISO}.html"
    preview_path.write_text(html, encoding="utf-8")
    print(f"[preview] Saved to {preview_path}")

    # Send ONLY to Maria
    from_addr = os.getenv("EMAIL_FROM", "")
    password = os.getenv("EMAIL_PASSWORD", "")
    to_addr = "maryreds@gmail.com"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🇲🇽 Special Report — Mexico's Semiconductor Industry (English)"
    msg["From"] = f"Briefing Diplomático <{from_addr}>"
    msg["To"] = to_addr
    msg.attach(MIMEText("This email requires an HTML-capable client.", "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(from_addr, password)
        server.sendmail(from_addr, [to_addr], msg.as_string())
    print(f"[email] Sent to {to_addr} only")

    print("Done.")


if __name__ == "__main__":
    main()
