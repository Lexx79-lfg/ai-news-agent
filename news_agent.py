import os, json, html
from datetime import date
from dotenv import load_dotenv
import anthropic

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# INSTRUCTIONS: now asking for structured JSON
instructions = (
    "You are a news agent. Find the 5 most important AI and AI security news "
    "stories from the last 24 hours, using reputable sources. Summarize each "
    "in your own words, 2 to 3 sentences, never copying text. "
    "Respond with ONLY a JSON array, no other text, like: "
    '[{"title": "...", "summary": "...", "source": "...", '
    '"url": "https://...", "category": "AI" or "AI Security"}]'
)

response = client.messages.create(
    model="claude-sonnet-5-5",
    max_tokens=3000,
    system=instructions,
    tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
    messages=[{"role": "user", "content": f"Today is {date.today()}. Get today's AI news."}],
)

raw = "".join(b.text for b in response.content if b.type == "text")

# PARSE: pull out just the JSON part, in case Claude added extra words
try:
    stories = json.loads(raw[raw.find("["): raw.rfind("]") + 1])
except ValueError:
    stories = []
    print("Could not read the stories. Raw output was:\n", raw)

# BUILD CARDS: escape every field, and only allow https links
cards = ""
for s in stories:
    url = s.get("url", "")
    link = f'<a href="{html.escape(url)}" target="_blank" rel="noopener">Read at {html.escape(s.get("source", "source"))}</a>' if url.startswith("https://") else ""
    tag_class = "sec" if "Security" in s.get("category", "") else "ai"
    cards += f"""
    <article class="card">
      <span class="tag {tag_class}">{html.escape(s.get("category", "AI"))}</span>
      <h2>{html.escape(s.get("title", ""))}</h2>
      <p>{html.escape(s.get("summary", ""))}</p>
      {link}
    </article>"""

page = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI News {date.today()}</title>
<style>
  body {{ margin: 0; font-family: -apple-system, Segoe UI, sans-serif; background: #f2f4f7; color: #16202c; }}
  header {{ background: #12263f; color: #fff; padding: 36px 24px; text-align: center; }}
  header h1 {{ margin: 0; font-size: 2rem; }}
  header p {{ margin: 8px 0 0; opacity: 0.8; }}
  main {{ max-width: 1000px; margin: 28px auto; padding: 0 16px; display: grid;
         grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 18px; }}
  .card {{ background: #fff; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
  .card h2 {{ font-size: 1.1rem; margin: 10px 0; }}
  .card p {{ line-height: 1.5; margin: 0 0 14px; }}
  .card a {{ color: #1f5fbf; font-weight: 600; text-decoration: none; }}
  .tag {{ font-size: 0.75rem; font-weight: 700; padding: 4px 10px; border-radius: 99px; }}
  .ai {{ background: #e3edfb; color: #1f4e8c; }}
  .sec {{ background: #fde8e1; color: #a63a14; }}
</style></head>
<body>
<header><h1>Daily AI Briefing</h1><p>{date.today():%A, %B %d, %Y} · Built by Alex Wray</p></header>
<main>{cards}</main>
</body></html>"""

with open("news.html", "w") as f:
    f.write(page)
print(f"Done. Saved news.html with {len(stories)} stories.")
