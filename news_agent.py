import os, re, json, html, urllib.request, urllib.error
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

REPO_URL = "https://github.com/Lexx79-lfg/ai-news-agent"
SITE_URL = "https://lexx79-lfg.github.io/ai-news-agent/"
USER_AGENT = f"ai-news-agent/1.0 (link previews for a daily briefing; +{REPO_URL})"
FETCH_TIMEOUT = 8
MAX_BYTES = 600_000

instructions = (
    "You are a news agent. Find the 5 most important AI and AI security news "
    "stories from the last 24 hours, using reputable sources. Order them from "
    "most to least important; the first is the top story. Summarize each in "
    "your own words, 2 to 3 sentences, never copying text. Add one sentence on "
    "why it matters, especially for security or everyday users. Then write "
    "one_idea: a single sentence, in your own words, connecting the day's stories. "
    "Respond with ONLY a JSON object, no other text, like: "
    '{"one_idea": "...", "stories": [{"title": "...", "summary": "...", "why": "...", '
    '"source": "...", "url": "https://...", "category": "AI" or "AI Security"}]}'
)


def e(value):
    return html.escape(str(value or ""))


def is_https(url):
    return isinstance(url, str) and urlparse(url.strip()).scheme.lower() == "https"


# ---------- reading Claude's answer ----------

def parse_response(raw):
    """Return (one_idea, stories). Accepts the new JSON object or the old plain list."""
    obj_at, list_at = raw.find("{"), raw.find("[")
    candidates = []
    if obj_at != -1:
        candidates.append(raw[obj_at: raw.rfind("}") + 1])
    if list_at != -1:
        candidates.append(raw[list_at: raw.rfind("]") + 1])
    if obj_at != -1 and list_at != -1 and list_at < obj_at:
        candidates.reverse()  # a list that starts first is the old format

    for text in candidates:
        try:
            data = json.loads(text)
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("stories"), list):
            idea = data.get("one_idea")
            return (idea.strip() if isinstance(idea, str) else ""), [s for s in data["stories"] if isinstance(s, dict)]
        if isinstance(data, list):
            return "", [s for s in data if isinstance(s, dict)]
    return "", []


def ask_claude():
    from dotenv import load_dotenv
    import anthropic

    load_dotenv()
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=3500,
        system=instructions,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        messages=[{"role": "user", "content": f"Today is {date.today()}. Get today's AI news."}],
    )
    return "".join(b.text for b in response.content if b.type == "text")


# ---------- link previews (og: meta tags) ----------

class HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_https(newurl):
            raise urllib.error.URLError(f"refused non-https redirect to {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(HttpsOnlyRedirect)


class MetaParser(HTMLParser):
    WANTED = {"og:image", "og:site_name", "og:image:alt"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        a = dict(attrs)
        key = (a.get("property") or a.get("name") or "").strip().lower()
        content = a.get("content")
        if key in self.WANTED and content and key not in self.meta:
            self.meta[key] = content.strip()


def fetch_page(url):
    """Return (final_url, text) for an https HTML page, or None."""
    if not is_https(url):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        with _opener.open(req, timeout=FETCH_TIMEOUT) as resp:
            final_url = resp.geturl()
            if not is_https(final_url):
                return None
            if "html" not in (resp.headers.get_content_type() or ""):
                return None
            body = resp.read(MAX_BYTES)
            charset = resp.headers.get_content_charset() or "utf-8"
    except (urllib.error.URLError, OSError, ValueError):
        return None
    try:
        return final_url, body.decode(charset, errors="replace")
    except LookupError:
        return final_url, body.decode("utf-8", errors="replace")


def parse_meta(page_html):
    parser = MetaParser()
    try:
        parser.feed(page_html)
    except Exception:
        pass
    return parser.meta


def get_preview(url, fetch=fetch_page):
    """Return {"image", "site_name", "alt"} only when there is an https image AND a site name."""
    page = fetch(url)
    if not page:
        return None
    final_url, text = page
    meta = parse_meta(text)
    site_name = meta.get("og:site_name", "")
    image = meta.get("og:image", "")
    if not site_name or not image:
        return None
    image = urljoin(final_url, image)
    if not is_https(image):
        return None
    return {"image": image, "site_name": site_name, "alt": meta.get("og:image:alt", "")}


def add_previews(stories, fetch=fetch_page):
    for s in stories:
        url = s.get("url", "")
        s["preview"] = get_preview(url, fetch) if is_https(url) else None
    return stories


# ---------- page ----------

def figure(s):
    p = s.get("preview")
    url = s.get("url", "")
    if not p or not is_https(url) or not is_https(p.get("image")) or not p.get("site_name"):
        return ""
    alt = p.get("alt") or s.get("title") or f"Image from {p['site_name']}"
    return f"""<figure class="thumb">
    <img src="{e(p['image'])}" alt="{e(alt)}" loading="lazy" decoding="async" onerror="this.closest('figure').remove()">
    <figcaption><a href="{e(url)}" target="_blank" rel="noopener">Image: {e(p['site_name'])}</a></figcaption>
  </figure>"""


def card(s, top=False):
    url = s.get("url", "")
    link = f'<a href="{e(url)}" target="_blank" rel="noopener">&gt; read at {e(s.get("source", "source"))}</a>' if is_https(url) else ""
    label = "TOP STORY" if top else e(s.get("category", "AI")).upper()
    return f"""<article class="card{' top' if top else ''}">
  {figure(s)}
  <div class="label">{label}</div>
  <h2>{e(s.get("title"))}</h2>
  <p>{e(s.get("summary"))}</p>
  <p class="why"><span>why it matters:</span> {e(s.get("why"))}</p>
  {link}
</article>"""


def one_idea_html(one_idea):
    if not one_idea:
        return ""
    return f"""<section class="one-idea" aria-label="One idea">
  <div class="label">One Idea</div>
  <p>{e(one_idea)}</p>
</section>"""


template = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Briefing __DATE__</title>
<meta name="description" content="__DESC__">
<meta property="og:type" content="website">
<meta property="og:title" content="AI Briefing __DATE__">
<meta property="og:description" content="__DESC__">
<meta property="og:url" content="__SITEURL__">
<meta property="og:site_name" content="Daily AI Briefing">
<style>
  body { margin: 0; background: #07130f; color: #cdeee2; font-family: -apple-system, Segoe UI, sans-serif; }
  .banner { position: relative; overflow: hidden; border-bottom: 1px solid #0F6E56; padding: 40px 28px;
            background-image: linear-gradient(#0F6E5640 1px, transparent 1px), linear-gradient(90deg, #0F6E5640 1px, transparent 1px);
            background-size: 40px 40px; }
  .banner h1 { margin: 0; font-family: Menlo, Consolas, monospace; color: #5DCAA5; font-size: 2rem; }
  .banner h1 .cursor { animation: blink 1s steps(1) infinite; }
  .banner p { margin: 10px 0 0; font-family: Menlo, Consolas, monospace; color: #9FE1CB; font-size: 0.9rem; }
  @keyframes blink { 50% { opacity: 0; } }
  #music { position: absolute; top: 20px; right: 24px; background: transparent; color: #5DCAA5;
           border: 1px solid #0F6E56; font-family: Menlo, Consolas, monospace; padding: 8px 12px; cursor: pointer; border-radius: 6px; }
  #music:hover { background: #0d1f19; }
  main { max-width: 1050px; margin: 28px auto; padding: 0 16px; }
  .one-idea .label { text-transform: uppercase; }
  .one-idea { border-left: 3px solid #5DCAA5; padding: 4px 0 4px 16px; margin-bottom: 20px; }
  .one-idea p { margin: 6px 0 0; font-size: 1.15rem; line-height: 1.5; color: #E1F5EE; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; margin-top: 16px; }
  .card { background: #0d1f19; border: 1px solid #0F6E56; border-radius: 10px; padding: 18px; }
  .card.top { border: 2px solid #5DCAA5; padding: 26px; }
  .card.top h2 { font-size: 1.6rem; }
  .label { font-family: Menlo, Consolas, monospace; font-size: 0.75rem; color: #5DCAA5; letter-spacing: 0.08em; }
  .card h2 { font-size: 1.1rem; color: #E1F5EE; margin: 8px 0; }
  .card p { line-height: 1.55; margin: 0 0 12px; }
  .why { color: #9FE1CB; font-size: 0.92rem; }
  .why span { font-family: Menlo, Consolas, monospace; color: #5DCAA5; }
  .card a { font-family: Menlo, Consolas, monospace; color: #5DCAA5; text-decoration: none; font-size: 0.9rem; }
  .card a:hover { text-decoration: underline; }
  .thumb { margin: 0 0 14px; }
  .thumb img { display: block; width: 100%; height: auto; max-height: 240px; object-fit: cover;
               border-radius: 6px; border: 1px solid #0F6E56; background: #07130f; }
  .card.top .thumb img { max-height: 360px; }
  .thumb figcaption { margin-top: 6px; }
  .thumb figcaption a { font-size: 0.75rem; color: #9FE1CB; }
  footer { text-align: center; font-family: Menlo, Consolas, monospace; color: #1D9E75; font-size: 0.8rem; padding: 30px; }
  .pill-wrap { text-align: center; padding-top: 10px; }
  .pill { display: inline-block; padding: 12px 34px; border-radius: 999px;
          background: linear-gradient(180deg, #ff6b6b 0%, #d61f1f 55%, #8f0d0d 100%);
          color: #fff; font-family: Menlo, Consolas, monospace; font-size: 0.9rem;
          letter-spacing: 0.08em; text-decoration: none; transition: transform 0.2s;
          box-shadow: 0 0 14px #d61f1f99, inset 0 2px 4px #ffffff66;
          animation: glow 2.5s ease-in-out infinite; }
  .pill:hover { transform: scale(1.06); }
  @keyframes glow { 50% { box-shadow: 0 0 28px #ff3b3bcc, inset 0 2px 4px #ffffff66; } }
  a:focus-visible, button:focus-visible { outline: 2px solid #E1F5EE; outline-offset: 3px; border-radius: 4px; }
  .pill:focus-visible { border-radius: 999px; }
  @media (prefers-reduced-motion: reduce) {
    .banner h1 .cursor, .pill { animation: none; }
    .pill { transition: none; }
    .pill:hover { transform: none; }
  }
</style></head>
<body>
<header class="banner">
  <button id="music">[ play ambient ]</button>
  <h1>&gt; daily_ai_briefing<span class="cursor">_</span></h1>
  <p>status: online &middot; __COUNT__ stories &middot; __LONGDATE__ &middot; built by Alex Wray</p>
</header>
<main>
  __IDEA__
  __TOP__
  <div class="grid">__REST__</div>
</main>
<div class="pill-wrap"><a class="pill" href="https://github.com/Lexx79-lfg/ai-news-agent/actions/workflows/daily.yml" target="_blank" rel="noopener noreferrer" title="Run a fresh briefing (owner only)">enter the matrix</a></div>

<footer>// generated by an AI agent &middot; summaries in its own words &middot; verify before sharing</footer>
<script>
  let ctx = null, timer = null;
  const btn = document.getElementById("music");
  const notes = [220, 261.6, 293.7, 329.6, 392, 440];
  function startMusic() {
    ctx = new AudioContext();
    const master = ctx.createGain(); master.gain.value = 0.06; master.connect(ctx.destination);
    [110, 164.8].forEach(f => {
      const o = ctx.createOscillator(); o.type = "sine"; o.frequency.value = f;
      o.connect(master); o.start();
    });
    timer = setInterval(() => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = "square"; o.frequency.value = notes[Math.floor(Math.random() * notes.length)];
      g.gain.setValueAtTime(0.05, ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.35);
      o.connect(g); g.connect(master); o.start(); o.stop(ctx.currentTime + 0.4);
    }, 450);
    btn.textContent = "[ stop ambient ]";
  }
  function stopMusic() {
    clearInterval(timer); ctx.close(); ctx = null;
    btn.textContent = "[ play ambient ]";
  }
  btn.addEventListener("click", () => ctx ? stopMusic() : startMusic());
</script>
</body></html>"""


def build_page(one_idea, stories, today=None):
    today = today or date.today()
    top_html = card(stories[0], top=True) if stories else "<p>No stories today.</p>"
    rest_html = "".join(card(s) for s in stories[1:])
    desc = f"A daily briefing of the most important AI and AI security news for {today:%B %d, %Y}, summarized by an AI agent."
    values = {
        "DATE": str(today),
        "LONGDATE": f"{today:%A, %B %d, %Y}",
        "COUNT": str(len(stories)),
        "DESC": e(desc),
        "SITEURL": e(SITE_URL),
        "IDEA": one_idea_html(one_idea),
        "TOP": top_html,
        "REST": rest_html,
    }
    # One pass, so text from Claude or web pages is never rescanned for placeholders.
    return re.sub(r"__([A-Z]+)__", lambda m: values.get(m.group(1), m.group(0)), template)


def main():
    raw = ask_claude()
    one_idea, stories = parse_response(raw)
    if not stories:
        print("Could not read the stories. Raw output was:\n", raw)
    add_previews(stories)
    with open("news.html", "w") as f:
        f.write(build_page(one_idea, stories))
    print(f"Done. Saved news.html with {len(stories)} stories.")


if __name__ == "__main__":
    main()
