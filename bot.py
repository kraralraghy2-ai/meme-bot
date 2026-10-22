import json, os, random, sys, time, datetime
import feedparser, requests
from PIL import Image, ImageDraw, ImageFont

MODEL = os.getenv("MODEL", "gemini-3.1-flash-lite")
NICHE = os.getenv("NICHE", "relatable everyday life, tech, and work humor")
LANG = os.getenv("LANG_OUT", "English")
FEEDS = [
    "https://www.reddit.com/r/technology/top/.rss?t=day",
    "https://www.reddit.com/r/Showerthoughts/top/.rss?t=day",
    "https://www.reddit.com/r/AskReddit/top/.rss?t=day",
]
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def ask(prompt):
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"responseMimeType": "application/json"}},
        timeout=60)
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def load(path, default):
    return json.load(open(path)) if os.path.exists(path) else default


def wrap(draw, text, font, width):
    lines, line = [], ""
    for w in text.split():
        t = f"{line} {w}".strip()
        if draw.textlength(t, font=font) <= width:
            line = t
        else:
            lines.append(line); line = w
    return lines + [line]


def render(top, bottom, path):
    img = Image.new("RGB", (1080, 1080), (20, 20, 28))
    d = ImageDraw.Draw(img)
    for y in range(1080):
        c = int(20 + 40 * y / 1080)
        d.line([(0, y), (1080, y)], fill=(c, c, c + 25))
    f = ImageFont.truetype(FONT, 64)
    for text, y0, y1 in ((top, 60, 520), (bottom, 560, 1020)):
        lines = wrap(d, text, f, 940)
        h = len(lines) * 80
        y = y0 + (y1 - y0 - h) // 2
        for ln in lines:
            w = d.textlength(ln, font=f)
            d.text(((1080 - w) / 2, y), ln, font=f, fill="white",
                   stroke_width=3, stroke_fill="black")
            y += 80
    d.line([(100, 540), (980, 540)], fill=(255, 255, 255), width=3)
    img.save(path)


def generate():
    posted = load("posted.json", [])
    topics = []
    for u in FEEDS:
        topics += [e.title for e in feedparser.parse(u).entries[:15]]
    random.shuffle(topics)
    idea = ask(
        f"Write ONE original two-part meme (setup / punchline) in {LANG} for an Instagram "
        f"page about: {NICHE}. Take loose inspiration from these trending titles but do NOT copy "
        f"any joke or text from them: {topics[:12]}. Avoid repeating recent posts: {posted[-15:]}. "
        'Keep it short, clever, and safe for all audiences. Reply ONLY JSON: '
        '{"top": "...", "bottom": "...", "caption": "...", "hashtags": "#a #b #c #d #e"}'
    )
    check = ask(
        "You are a strict brand-safety reviewer. Reject anything hateful, sexual, political, "
        "about tragedies, insulting to real people, misleading, or copied from a known joke. "
        f"Content: {json.dumps(idea, ensure_ascii=False)}. "
        'Reply ONLY JSON: {"approved": true/false, "reason": "..."}'
    )
    if not check.get("approved"):
        print("Rejected by safety check:", check.get("reason"))
        return
    os.makedirs("images", exist_ok=True)
    name = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S") + ".png"
    render(idea["top"], idea["bottom"], f"images/{name}")
    json.dump({"file": name, "caption": f'{idea["caption"]}\n\n{idea["hashtags"]}',
               "text": f'{idea["top"]} / {idea["bottom"]}'},
              open("pending.json", "w"), ensure_ascii=False)
    print("Generated", name)


def publish():
    if not os.path.exists("pending.json"):
        print("Nothing to publish"); return
    p = json.load(open("pending.json"))
    uid, tok = os.environ["IG_USER_ID"], os.environ["IG_ACCESS_TOKEN"]
    repo, branch = os.environ["GITHUB_REPOSITORY"], os.getenv("GITHUB_REF_NAME", "main")
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/images/{p['file']}"
    base = "https://graph.facebook.com/v21.0"
    r = requests.post(f"{base}/{uid}/media",
                      data={"image_url": url, "caption": p["caption"], "access_token": tok})
    r.raise_for_status()
    cid = r.json()["id"]
    for _ in range(20):
        s = requests.get(f"{base}/{cid}", params={"fields": "status_code", "access_token": tok}).json()
        if s.get("status_code") == "FINISHED":
            break
        time.sleep(5)
    r = requests.post(f"{base}/{uid}/media_publish", data={"creation_id": cid, "access_token": tok})
    r.raise_for_status()
    posted = load("posted.json", [])
    posted.append(p["text"])
    json.dump(posted[-200:], open("posted.json", "w"), ensure_ascii=False)
    os.remove("pending.json")
    print("Published", r.json())


if __name__ == "__main__":
    {"generate": generate, "publish": publish}[sys.argv[1]]()
