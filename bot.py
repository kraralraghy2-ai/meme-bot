import base64, io, json, os, random, sys, time, datetime
import requests
import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont, ImageOps

MODEL = os.getenv("MODEL", "gemini-3.1-flash-lite")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
IG_BASE = "https://graph.instagram.com/v23.0"
QUERIES = [
    "football fans stadium", "soccer goalkeeper save", "referee yellow card",
    "kids playing football street", "soccer ball goal net", "football coach sideline",
    "soccer player celebrating", "disappointed football fan", "football crowd cheering",
    "soccer penalty kick", "football boots grass", "football stadium night",
    "soccer team huddle", "soccer tackle", "fan watching football tv",
]
IDEA_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "top": {"type": "STRING"}, "bottom": {"type": "STRING"},
        "caption": {"type": "STRING"}, "hashtags": {"type": "STRING"},
    },
    "required": ["top", "bottom", "caption", "hashtags"],
}
CHECK_SCHEMA = {
    "type": "OBJECT",
    "properties": {"approved": {"type": "BOOLEAN"}, "reason": {"type": "STRING"}},
    "required": ["approved", "reason"],
}


def gem(parts, schema):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    for i in range(6):
        r = requests.post(
            url, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
            json={"contents": [{"parts": parts}],
                  "generationConfig": {"responseMimeType": "application/json",
                                       "responseSchema": schema}},
            timeout=90)
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(8 * (i + 1))
            continue
        r.raise_for_status()
        t = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        try:
            return json.loads(t)
        except ValueError:
            try:
                return json.loads(t[t.index("{"): t.rindex("}") + 1])
            except ValueError:
                time.sleep(3)
                continue
    raise RuntimeError("Gemini unavailable or returned bad JSON")


def load(path, default):
    return json.load(open(path)) if os.path.exists(path) else default


def ar(t):
    return get_display(arabic_reshaper.reshape(t))


def wrap(d, text, font, width):
    lines, line = [], ""
    for w in text.split():
        t = f"{line} {w}".strip()
        if d.textlength(ar(t), font=font) <= width:
            line = t
        else:
            lines.append(line)
            line = w
    return [l for l in lines + [line] if l]


def render(img, top, bottom, path):
    img = ImageOps.fit(img, (1080, 1080)).convert("RGBA")
    ov = Image.new("RGBA", (1080, 1080), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    for y in range(1080):
        if y < 380:
            a = int(170 * (380 - y) / 380)
        elif y > 700:
            a = int(170 * (y - 700) / 380)
        else:
            a = 0
        od.line([(0, y), (1080, y)], fill=(0, 0, 0, a))
    img = Image.alpha_composite(img, ov).convert("RGB")
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONT, 72)

    def block(text, at_bottom):
        lines = wrap(d, text, f, 960)
        y = (1040 - len(lines) * 90) if at_bottom else 40
        for ln in lines:
            s = ar(ln)
            w = d.textlength(s, font=f)
            d.text(((1080 - w) / 2, y), s, font=f, fill="white",
                   stroke_width=5, stroke_fill="black")
            y += 90

    block(top, False)
    block(bottom, True)
    img.save(path, "JPEG", quality=92)


def pick_photo(used):
    q = random.choice(QUERIES)
    r = requests.get("https://pixabay.com/api/", params={
        "key": os.environ["PIXABAY_API_KEY"], "q": q, "image_type": "photo",
        "safesearch": "true", "per_page": 50}, timeout=30)
    r.raise_for_status()
    hits = [h for h in r.json().get("hits", []) if h["id"] not in used]
    if not hits:
        raise RuntimeError("no photos for " + q)
    h = random.choice(hits)
    data = requests.get(h["largeImageURL"], timeout=60).content
    return h["id"], Image.open(io.BytesIO(data)).convert("RGB")


def generate():
    posted = load("posted.json", [])
    used = load("used_photos.json", [])
    pid, img = pick_photo(used)
    small = img.copy()
    small.thumbnail((768, 768))
    buf = io.BytesIO()
    small.save(buf, "JPEG", quality=85)
    prompt = (
        "You write Iraqi-Arabic football banter memes (تحشيش كروي) for an Instagram page. "
        "Look at the photo and write a funny two-line meme text that fits what is visible. "
        "Rules: Iraqi dialect Arabic; each line at most 9 words; football banter only "
        "(fans, referees, goalkeepers, clubs, the league, the national team, watching matches "
        "with friends). Do NOT identify or name anyone in the photo. Do not insult any real "
        "person. No politics, religion, sectarian or tragic content, no profanity. "
        "Do not use double quotation marks inside the text. "
        f"Do not repeat these recent memes: {posted[-15:]}. "
        "Fields: top and bottom are the meme lines; caption is a short Iraqi-Arabic caption "
        "with 1-2 emojis; hashtags is 5 Arabic hashtags separated by spaces."
    )
    idea = gem([{"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg",
                                 "data": base64.b64encode(buf.getvalue()).decode()}}],
               IDEA_SCHEMA)
    check = gem([{"text": (
        "You are a strict brand-safety reviewer for an Iraqi football meme page. Reject "
        "anything insulting to a real person, hateful, sectarian, political, religious, "
        "sexual, about tragedies, profane, misleading, or copied from a known joke. "
        f"Content: {json.dumps(idea, ensure_ascii=False)}")}], CHECK_SCHEMA)
    if not check.get("approved"):
        print("Rejected by safety check:", check.get("reason"))
        return
    os.makedirs("images", exist_ok=True)
    name = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S") + ".jpg"
    render(img, idea["top"], idea["bottom"], f"images/{name}")
    used.append(pid)
    json.dump(used[-500:], open("used_photos.json", "w"))
    json.dump({"file": name,
               "caption": f'{idea["caption"]}\n\n{idea["hashtags"]}\n\n📷 Pixabay',
               "text": f'{idea["top"]} / {idea["bottom"]}'},
              open("pending.json", "w"), ensure_ascii=False)
    print("Generated", name)


def publish():
    if not os.path.exists("pending.json"):
        print("Nothing to publish")
        return
    if not os.path.exists("PUBLISH_ON"):
        print("Publishing is OFF (create a file named PUBLISH_ON to enable)")
        return
    p = json.load(open("pending.json"))
    uid, tok = os.environ["IG_USER_ID"], os.environ["IG_ACCESS_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.getenv("GITHUB_REF_NAME", "main")
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/images/{p['file']}"
    r = requests.post(f"{IG_BASE}/{uid}/media", data={
        "image_url": url, "caption": p["caption"], "access_token": tok})
    r.raise_for_status()
    cid = r.json()["id"]
    for _ in range(20):
        s = requests.get(f"{IG_BASE}/{cid}", params={
            "fields": "status_code", "access_token": tok}).json()
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") == "ERROR":
            raise RuntimeError("Instagram rejected the image: " + str(s))
        time.sleep(5)
    r = requests.post(f"{IG_BASE}/{uid}/media_publish", data={
        "creation_id": cid, "access_token": tok})
    r.raise_for_status()
    posted = load("posted.json", [])
    posted.append(p["text"])
    json.dump(posted[-200:], open("posted.json", "w"), ensure_ascii=False)
    os.remove("pending.json")
    print("Published", r.json())


if __name__ == "__main__":
    {"generate": generate, "publish": publish}[sys.argv[1]]()
