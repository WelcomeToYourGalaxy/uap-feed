#!/usr/bin/env python3
"""
harvest_uap.py — the UAP wire: unidentified aerial and anomalous phenomena,
underwater objects, and the question of non-human intelligence, worldwide.

Self-contained: fetching, feed parsing, word-edge matching and deduplication are
all in this file. Reads sources_uap.json, writes wire_uap.json. Standard library
only — no dependencies, no API keys, no model calls.

This subject attracts more nonsense than almost any other, so the harvester does
two things instead of one. It gates: a story has to concern the phenomenon
itself, and anything trading in reptilians, channelled messages, galactic
federations or predicted disclosure dates is refused outright. Then it grades:
every story carries a standing — official, science, press, specialist or sceptic
— and an evidence score built from documents, sensor data, named witnesses,
hearings and peer review. A sighting reported by one person and a released radar
tape both appear, and the page never lets you mistake one for the other.

    python3 harvest_uap.py
    python3 harvest_uap.py --dry-run
    python3 harvest_uap.py --fixtures DIR
"""

import argparse
import gzip
import html
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES_PATH = os.path.join(HERE, "sources_uap.json")
OUT_PATH = os.path.join(HERE, "wire_uap.json")

RETAIN_DAYS = 45
MAX_ITEMS = 1200
WORKERS = 6
DOCUMENTED_SCORE = 3    # at or above this a story is marked as documented

# --------------------------------------------------------------------------
# Plumbing: fetching, feed parsing, word-edge matching, fingerprints.
# --------------------------------------------------------------------------
USER_AGENT = ("Mozilla/5.0 (compatible; space-life-news/1.0; "
              "+https://github.com/WelcomeToYourGalaxy/space-life-news)")

TIMEOUT = 25

SNIPPET_CHARS = 240

TAG_RE = re.compile(r"<[^>]+>")

WS_RE = re.compile(r"\s+")

PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)

def build_gnews_url(loc):
    q = loc["query"] + " when:30d"
    return ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q) +
            "&hl=" + loc["hl"] + "&gl=" + loc["gl"] + "&ceid=" + loc["ceid"])

def fetch(url, tries=3):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
                "Accept-Encoding": "gzip",
                "Accept-Language": "*",
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                return raw
        except Exception as exc:                       # noqa: BLE001 — report, don't crash the run
            last = exc
            time.sleep(1.5 * (attempt + 1))
    print("  ! unreachable: %s (%s)" % (url[:90], last), file=sys.stderr)
    return None

def strip_ns(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag

def text_of(el):
    return WS_RE.sub(" ", html.unescape(TAG_RE.sub(" ", el.text or ""))).strip() if el is not None else ""

def child(node, *names):
    for kid in node:
        if strip_ns(kid.tag) in names:
            return kid
    return None

def parse_date(raw):
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:  # noqa: BLE001
        pass
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:  # noqa: BLE001
        return None

def parse_feed(raw, src):
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        # Some publishers serve a stray byte before the declaration.
        try:
            root = ET.fromstring(raw[raw.index(b"<"):])
        except Exception:  # noqa: BLE001
            return []

    nodes = [n for n in root.iter() if strip_ns(n.tag) == "item"]
    atom = False
    if not nodes:
        nodes = [n for n in root.iter() if strip_ns(n.tag) == "entry"]
        atom = True

    out = []
    for n in nodes:
        title = text_of(child(n, "title"))
        if atom:
            link = ""
            for kid in n:
                if strip_ns(kid.tag) == "link" and kid.get("rel", "alternate") == "alternate":
                    link = kid.get("href", "")
                    break
        else:
            link_el = child(n, "link")
            link = (link_el.text or "").strip() if link_el is not None else ""
            if not link:
                link = text_of(child(n, "guid"))
        if not title or not link:
            continue

        outlet_el = child(n, "source")
        outlet = text_of(outlet_el) if outlet_el is not None else ""
        if outlet and title.endswith(" - " + outlet):
            title = title[: -(len(outlet) + 3)].strip()
        elif not outlet and src["name"].startswith("Google News") and " - " in title:
            # Google News appends the outlet to the headline when it omits <source>.
            head, _, tail = title.rpartition(" - ")
            if head and 2 <= len(tail) <= 45:
                title, outlet = head.strip(), tail.strip()

        stamp = parse_date(text_of(child(n, "pubDate", "published", "updated", "date")))
        snippet = text_of(child(n, "description", "summary", "content"))[:SNIPPET_CHARS]

        out.append({
            "t": title,
            "u": link,
            "o": outlet or src["name"].replace("Google News · ", ""),
            "g": src["lang"],
            "r": src["region"],
            "k": src.get("kind", "news"),
            "d": stamp,
            "s": snippet,
            "w": src["name"],
        })
    return out

def _compile(term):
    if any(ord(ch) > 0x24F for ch in term):        # non-Latin script
        # substring matching is already prefix-like in scripts without word
        # breaks, so a trailing * is a no-op — strip it rather than search for
        # a literal asterisk, which is what used to happen.
        return term[:-1] if term.endswith("*") else term
    if term.endswith("*"):
        return re.compile(r"(?<![a-z0-9])" + re.escape(term[:-1]) + r"[a-z0-9\-]*", re.I)
    return re.compile(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", re.I)

def _compile_all(terms):
    return [_compile(t) for t in terms]

def hit(text, compiled):
    """True when any compiled term matches."""
    for c in compiled:
        if isinstance(c, str):
            if c in text:
                return True
        elif c.search(text):
            return True
    return False

def fingerprint(title):
    norm = PUNCT_RE.sub(" ", title.lower())
    return " ".join(WS_RE.sub(" ", norm).strip().split()[:9])

def canon_url(url):
    try:
        parts = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parts.query)
        query = [(k, v) for k, v in query if not k.lower().startswith("utm_")]
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"),
                                        urllib.parse.urlencode(query), ""))
    except Exception:  # noqa: BLE001
        return url


# --------------------------------------------------------------------------
# Where the story is.  This is the region the finding concerns, not the region
# the wire was read from — a Japanese outlet reporting on the Amazon files
# under Latin America.  A story with global scope files under Global, and one
# can carry several: a study spanning Africa and South Asia files under both.
# --------------------------------------------------------------------------
GEO = [
    ("africa", "Africa", [
        ("africa*", None), ("sahel", None), ("congo basin", None), ("nigeria*", None),
        ("kenya*", None), ("ethiopia*", None), ("democratic republic of congo", None),
        ("drc", None), ("ghana", None), ("tanzania*", None), ("uganda*", None),
        ("south africa*", None), ("zimbabwe*", None), ("zambia*", None), ("mozambique", None),
        ("angola*", None), ("senegal", None), ("mali", ["africa", "sahel", "bamako", "drought"]),
        ("chad", ["lake", "africa", "sahel", "basin"]), ("sudan*", None), ("somalia*", None),
        ("madagascar", None), ("cameroon", None), ("côte d'ivoire", None), ("ivory coast", None),
        ("botswana", None), ("namibia", None), ("malawi", None), ("rwanda", None),
        ("okavango", None), ("lake victoria", None), ("serengeti", None), ("kalahari", None),
        ("horn of africa", None), ("afrique", None), ("áfrica", None), ("afrika", None),
        ("非洲", None), ("アフリカ", None), ("африк*", None), ("أفريقيا", None), ("अफ्रीका", None),
    ]),
    ("mena", "Middle East & North Africa", [
        ("middle east*", None), ("egypt*", None), ("morocco", None), ("algeria*", None),
        ("tunisia*", None), ("libya*", None), ("saudi arabia", None), ("emirates", None),
        ("qatar", None), ("kuwait", None), ("oman", None), ("yemen*", None), ("iraq*", None),
        ("iran*", None), ("israel*", None), ("palestin*", None), ("gaza", None), ("jordan", None),
        ("lebanon", None), ("syria*", None), ("turkey", ["drought", "climate", "pollution", "earthquake", "istanbul", "anatolia"]),
        ("türkiye", None), ("persian gulf", None), ("red sea", None), ("euphrates", None),
        ("tigris", None), ("dead sea", None), ("sahara", None), ("الشرق الأوسط", None),
        ("中东", None), ("北アフリカ", None),
    ]),
    ("asia", "Asia", [
        ("asia*", None), ("china", None), ("chinese", ["government", "province", "coal", "emissions", "cities"]),
        ("japan*", None), ("korea*", None), ("india", None), ("indian", ["ocean", "government", "farmers", "cities", "monsoon", "state"]),
        ("pakistan*", None), ("bangladesh*", None), ("nepal*", None), ("sri lanka", None),
        ("indonesia*", None), ("vietnam*", None), ("thailand", None), ("philippines", None),
        ("malaysia*", None), ("myanmar", None), ("cambodia*", None), ("laos", None),
        ("mongolia*", None), ("kazakhstan", None), ("uzbekistan", None), ("central asia", None),
        ("himalaya*", None), ("mekong", None), ("ganges", None), ("yangtze", None),
        ("brahmaputra", None), ("tibet*", None), ("borneo", None), ("sumatra", None),
        ("aral sea", None), ("gobi", None), ("siberia*", None), ("アジア", None), ("亚洲", None),
        ("아시아", None), ("एशिया", None), ("азия", None),
    ]),
    ("europe", "Europe", [
        ("europe*", ["union", "countries", "climate", "commission", "continent", "wide", "study", "across"]),
        ("european union", None), ("european commission", None), ("brussels", None),
        ("eu", ["deforestation", "regulation", "law", "directive", "commission", "member states",
                "emissions", "green deal", "farm", "policy", "ban", "target"]),
        ("united kingdom", None), ("britain", None), ("england", None),
        ("scotland", None), ("wales", ["climate", "flood", "farm", "coast"]), ("ireland", None),
        ("france", None), ("germany", None), ("spain", None), ("portugal", None), ("italy", None),
        ("greece", None), ("netherlands", None), ("belgium", None), ("poland", None),
        ("ukraine", None), ("russia*", None), ("sweden", None), ("norway", None), ("finland", None),
        ("denmark", None), ("switzerland", None), ("austria", None), ("romania", None),
        ("hungary", None), ("czech*", None), ("balkans", None), ("danube", None), ("alps", None),
        ("mediterranean", None), ("baltic", None), ("北欧", None), ("欧洲", None), ("ヨーロッパ", None),
        ("유럽", None), ("европ*", None), ("أوروبا", None),
    ]),
    ("latam", "Latin America & Caribbean", [
        ("latin america*", None), ("south america*", None), ("central america*", None),
        ("brazil*", None), ("brasil", None), ("amazon", None), ("amazônia", None), ("amazonía", None),
        ("argentina", None), ("chile", None), ("peru", None), ("colombia*", None),
        ("venezuela*", None), ("ecuador", None), ("bolivia*", None), ("paraguay", None),
        ("uruguay", None), ("mexico", None), ("méxico", None), ("guatemala", None),
        ("honduras", None), ("nicaragua", None), ("costa rica", None), ("panama", None),
        ("cuba", None), ("haiti", None), ("dominican republic", None), ("caribbean", None),
        ("patagonia", None), ("andes", None), ("cerrado", None), ("pantanal", None),
        ("gran chaco", None), ("orinoco", None), ("américa latina", None), ("拉丁美洲", None),
        ("ラテンアメリカ", None), ("латинская америка", None),
    ]),
    ("northam", "North America", [
        ("united states", None), ("u.s.", None), ("usa", None), ("american", ["government", "cities", "states", "west", "farmers", "midwest", "coast"]),
        ("canada", None), ("canadian", None), ("alaska*", None), ("california", None),
        ("texas", None), ("florida", None), ("great lakes", None), ("colorado river", None),
        ("mississippi", None), ("appalachia*", None), ("quebec", None), ("ontario", None),
        ("british columbia", None), ("gulf of mexico", None), ("états-unis", None),
        ("estados unidos", None), ("美国", None), ("加拿大", None), ("アメリカ合衆国", None),
        ("미국", None), ("сша", None),
    ]),
    ("oceania", "Oceania", [
        ("australia*", None), ("new zealand", None), ("aotearoa", None), ("papua", None),
        ("pacific island*", None), ("fiji", None), ("samoa", None), ("tonga", None),
        ("vanuatu", None), ("solomon islands", None), ("kiribati", None), ("tuvalu", None),
        ("great barrier reef", None), ("tasmania*", None), ("murray-darling", None),
        ("オセアニア", None), ("大洋洲", None), ("océanie", None),
    ]),
    ("polar", "Arctic & Antarctic", [
        ("arctic", None), ("antarctic*", None), ("greenland", None), ("svalbard", None),
        ("north pole", None), ("south pole", None), ("tundra", None), ("北極", None),
        ("南極", None), ("арктик*", None), ("antártic*", None), ("arctique", None),
    ]),
    ("ocean", "Oceans & high seas", [
        ("pacific ocean", None), ("atlantic ocean", None), ("indian ocean", None),
        ("southern ocean", None), ("high seas", None), ("open ocean", None),
        ("coral triangle", None), ("mariana", None), ("deep sea", None), ("north sea", None),
        ("bering sea", None), ("south china sea", None), ("océan pacifique", None),
        ("公海", None), ("深海", None),
    ]),
]


# --------------------------------------------------------------------------
# Subjects
# --------------------------------------------------------------------------
TOPICS = [
    ("oversight", "Government & oversight", [
        ("aaro", None), ("all-domain anomaly resolution", None), ("uap task force", None),
        ("congressional hearing", ["uap", "ufo", "anomalous"]), ("senate hearing", ["uap", "ufo"]),
        ("house oversight", ["uap", "ufo"]), ("uap disclosure act", None), ("aatip", None),
        ("inspector general", ["uap", "ufo", "anomalous"]), ("whistleblower", ["uap", "ufo", "anomalous"]),
        ("geipan", None), ("cefaa", None), ("ministry of defence", ["ufo", "uap", "files"]),
        ("defence ministry", ["ufo", "uap"]), ("norad", ["object", "unidentified", "balloon"]),
        ("audition parlementaire", ["ovni", "pan"]), ("comisión", ["ovni", "fani"]),
        ("国会", ["ufo", "未確認"]), ("国防部", ["不明飞行物", "不明"]),
    ]),
    ("military", "Military encounters", [
        ("navy pilot*", None), ("air force pilot*", None), ("fighter jet", ["unidentified", "object", "intercept", "uap"]),
        ("intercept*", ["unidentified", "object", "uap", "airspace"]),
        ("carrier strike group", ["unidentified", "object"]), ("nimitz", None), ("gimbal", None),
        ("go fast", ["video", "navy", "uap"]), ("tic tac", ["object", "uap", "navy"]),
        ("restricted airspace", ["unidentified", "drone", "object"]),
        ("base incursion*", None), ("drone incursion*", None), ("airspace closure", ["unidentified", "object"]),
        ("rafale", ["ovni", "pan", "non identifié"]), ("戦闘機", ["未確認"]),
    ]),
    ("sensor", "Sensor & imagery", [
        ("radar", ["unidentified", "uap", "object", "track", "anomalous"]),
        ("infrared", ["unidentified", "uap", "object"]), ("flir", None),
        ("multi-sensor", None), ("telemetry", ["unidentified", "object", "uap"]),
        ("spectrograph*", ["anomalous", "uap"]), ("all-sky camera*", None),
        ("photogrammetr*", None), ("trajectory analysis", None), ("satellite imagery", ["unidentified", "object"]),
        ("footage analys*", None), ("video authenticat*", None),
    ]),
    ("science", "Scientific study", [
        ("galileo project", None), ("scientific coalition", ["uap", "anomalous"]),
        ("peer-reviewed", ["uap", "ufo", "anomalous", "technosignature"]),
        ("technosignature*", None), ("interstellar object", None), ("3i/atlas", None),
        ("'oumuamua", None), ("oumuamua", None), ("seti", ["signal", "search", "institute", "radio"]),
        ("instrument*", ["uap", "anomalous", "observatory", "detection"]),
        ("statistical analysis", ["sighting*", "uap", "report*"]),
        ("hypothesis", ["uap", "anomalous", "extraterrestrial"]),
    ]),
    ("records", "Records & archives", [
        ("foia", None), ("freedom of information", None), ("declassified", None),
        ("released documents", None), ("archive release", None), ("project blue book", None),
        ("condign", None), ("operação prato", None), ("operacion prato", None),
        ("national archives", ["ufo", "uap"]), ("desclasificad*", None), ("dossier déclassifié", None),
        ("rassekrech*", None), ("рассекречен*", None), ("機密解除", None), ("解密文件", ["不明"]),
    ]),
    ("sightings", "Sightings & reports", [
        ("sighting*", ["uap", "ufo", "unidentified", "object", "ovni", "нло"]),
        ("witness*", ["uap", "ufo", "unidentified", "sighting"]),
        ("reported object", None), ("mass sighting", None), ("wave of sightings", None),
        ("avistamiento*", None), ("avistamento*", None), ("observation*", ["ovni", "pan non identifié"]),
        ("目撃", ["ufo", "未確認"]), ("목격", ["미확인"]),
    ]),
    ("uso", "USOs & maritime", [
        ("unidentified submerged", None), ("uso", ["unidentified", "submerged", "underwater", "object"]),
        ("transmedium", None), ("underwater object", None), ("sonar", ["unidentified", "anomalous", "contact"]),
        ("submarine crew", ["unidentified", "object"]), ("objeto sumergido", None),
    ]),
    ("sceptic", "Explanations & debunks", [
        ("prosaic explanation", None), ("identified as a balloon", None), ("weather balloon", None),
        ("starlink", ["mistaken", "sighting", "ufo", "reported"]),
        ("misidentif*", None), ("debunk*", None), ("hoax", None), ("parallax", None),
        ("camera artefact*", None), ("camera artifact*", None), ("lens flare", None),
        ("explained by", ["ufo", "uap", "sighting", "object"]),
        ("desmentid*", None), ("erklärt", ["ufo", "sichtung"]),
    ]),
    ("policy", "Policy & law", [
        ("legislation", ["uap", "ufo", "anomalous"]), ("amendment", ["uap", "ufo", "disclosure"]),
        ("classification review", None), ("security clearance", ["uap", "programme", "program"]),
        ("reverse engineering", ["craft", "material", "programme", "program"]),
        ("appropriations", ["uap", "aaro"]), ("policy directive", ["uap", "unidentified"]),
        ("air safety", ["unidentified", "object", "report"]), ("icao", ["unidentified", "reporting"]),
    ]),
    ("life", "Life beyond Earth", [
        ("extraterrestrial life", None), ("non-human intelligence", None), ("biosignature*", None),
        ("exoplanet", ["habitable", "life", "biosignature"]), ("astrobiolog*", None),
        ("vida extraterrestre", None), ("vie extraterrestre", None), ("地球外生命", None),
        ("외계 생명", None), ("внеземная жизнь", None), ("حياة خارج الأرض", None),
    ]),
]

# --------------------------------------------------------------------------
# The gate.
#
# ANCHOR — the story concerns the phenomenon itself.
# BLOCK — the two ways this subject goes wrong: the word "alien" used for
#         immigration, invasive species or a film franchise, and the esoteric
#         end of the field. High-quality independent journalism is welcome;
#         channelled messages and galactic federations are not.
# --------------------------------------------------------------------------
ANCHOR = [
    "uap", "u.a.p.", "ufo", "u.f.o", "ufos", "unidentified aerial phenomen*",
    "unidentified anomalous phenomen*", "unidentified flying object*",
    "unidentified submerged object*", "unidentified object*", "anomalous phenomen*",
    "flying saucer*", "aaro", "aatip", "project blue book", "geipan", "cefaa",
    "non-human intelligence", "extraterrestrial*", "transmedium",
    "galileo project", "technosignature*", "interstellar object", "'oumuamua", "oumuamua",
    "ovni*", "ovnis", "fani", "pan non identifié*", "phénomènes aérospatiaux non identifiés",
    "unidentifizierte flugobjekt*", "objeto voador não identificado", "objeto volador no identificado",
    "oggetti volanti non identificati", "niezidentyfikowany obiekt latający",
    "нло", "неопознанный летающий объект", "невідомий літальний об'єкт",
    "未確認飛行物体", "未確認異常現象", "不明飞行物", "不明飛行物", "미확인 비행 물체",
    "أجسام طائرة مجهولة", "ظواهر جوية مجهولة", "עב\"מ", "اجسام پرنده ناشناس",
    "यूएफओ", "अज्ञात उड़न", "benda terbang tak dikenal", "vật thể bay không xác định",
    "tanımlanamayan uçan cisim", "วัตถุบินไม่ทราบชนิด", "άγνωστο ιπτάμενο αντικείμενο",
    "oidentifierat flygande föremål", "onbekend vliegend object",
    "alien", "aliens",   # guarded below by BLOCK, which removes the other senses
]

BLOCK = [
    # "alien" in its legal, biological and cinematic senses
    "illegal alien*", "criminal alien*", "resident alien", "alien registration",
    "alien enemies act", "alien land law", "deportation", "immigration enforcement",
    "invasive alien species", "alien species", "alien plant*", "alien invasive",
    "alien: earth", "alien romulus", "alien covenant", "xenomorph", "prometheus film",
    "box office", "streaming series", "season finale", "episode recap", "video game",
    "alien isolation", "mass effect", "halo series", "cosplay", "comic con",
    # the esoteric end: claims that cannot be examined
    "reptilian*", "annunaki", "anunnaki", "nibiru", "galactic federation", "starseed*",
    "channell*", "channeled message*", "psychic contact", "telepathic contact",
    "ascension", "fifth dimension", "lightworker*", "pleiadian*", "arcturian*",
    "ancient astronaut*", "ancient aliens", "aliens built", "flat earth", "hollow earth",
    "abduction memory", "regression hypnosis", "chemtrail*", "illuminati", "qanon",
    "horoscope", "astrolog*", "tarot", "psychic reading", "crop circle message",
    "prophecy", "predicted date of disclosure", "channeler",
]

# --------------------------------------------------------------------------
# Evidence scoring. Standing says who is speaking; this says what they brought.
# --------------------------------------------------------------------------
DOCUMENT = [
    "declassified", "foia", "freedom of information", "released documents", "document release",
    "memo", "cable", "report to congress", "official report", "annual report", "archive release",
    "court filing", "affidavit", "transcript", "desclasificad*", "déclassifié*", "рассекречен*",
    "機密解除", "解密",
]
SENSOR = [
    "radar", "infrared", "flir", "sonar", "telemetry", "multi-sensor", "sensor data",
    "satellite imagery", "spectrum analysis", "photogrammetr*", "flight data recorder",
    "all-sky camera", "instrument data", "レーダー", "雷达",
]
TESTIMONY = [
    "pilot", "aircrew", "air traffic controller", "navy officer", "air force officer",
    "testimony", "testified", "under oath", "sworn statement", "named witness",
    "witness statement", "témoignage", "testimonio", "証言", "증언",
]
FORMAL = [
    "hearing", "subcommittee", "select committee", "peer-reviewed", "published in",
    "journal", "preprint", "study finds", "analysis finds", "inspector general",
    "government accountability office", "audition", "audiencia", "公聴会",
]
RESOLVED = [
    "identified as", "explained by", "turned out to be", "prosaic explanation",
    "misidentif*", "debunk*", "hoax", "weather balloon", "camera artefact*",
    "camera artifact*", "lens flare", "starlink satellites",
]


ANCHOR_C = _compile_all(ANCHOR)
BLOCK_C = _compile_all(BLOCK)
DOCUMENT_C = _compile_all(DOCUMENT)
SENSOR_C = _compile_all(SENSOR)
TESTIMONY_C = _compile_all(TESTIMONY)
FORMAL_C = _compile_all(FORMAL)
RESOLVED_C = _compile_all(RESOLVED)
TOPICS_C = [(tid, label, [(_compile(t), _compile_all(g) if g else None) for t, g in terms])
            for tid, label, terms in TOPICS]
GEO_C = [(gid, label, [(_compile(t), _compile_all(g) if g else None) for t, g in terms])
         for gid, label, terms in GEO]

STANDING_RANK = {"official": 3, "science": 3, "sceptic": 2, "press": 2, "specialist": 1}


def relevant(text):
    """Anything trading in the esoteric is refused outright; everything else has
    to name the phenomenon rather than merely gesture at it."""
    if hit(text, BLOCK_C):
        return False
    return hit(text, ANCHOR_C)


def evidence(text, standing):
    """What the story brought with it, as a score and the reasons for it."""
    total, reasons = 0, []
    if hit(text, DOCUMENT_C):
        total += 2
        reasons.append("document")
    if hit(text, SENSOR_C):
        total += 2
        reasons.append("sensor")
    if hit(text, FORMAL_C):
        total += 1
        reasons.append("on the record")
    if hit(text, TESTIMONY_C):
        total += 1
        reasons.append("named witness")
    if hit(text, RESOLVED_C):
        total += 1
        reasons.append("resolved")
    if standing in ("official", "science"):
        total += 1
        reasons.append("primary source")
    return total, reasons


def topics_for(text):
    hits = []
    for tid, _label, terms in TOPICS_C:
        for term, guards in terms:
            if not hit(text, [term]):
                continue
            if guards and not hit(text, guards):
                continue
            hits.append(tid)
            break
    return hits


def regions_for(text):
    hits = []
    for gid, _label, terms in GEO_C:
        for term, guards in terms:
            if not hit(text, [term]):
                continue
            if guards and not hit(text, guards):
                continue
            hits.append(gid)
            break
    return hits or ["unlocated"]


def load_sources():
    with open(SOURCES_PATH, encoding="utf-8") as fh:
        cfg = json.load(fh)
    srcs = []
    for s in cfg.get("direct", []):
        srcs.append({"name": s["name"], "lang": s["lang"], "standing": s["standing"],
                     "region": s["standing"],   # parse_feed labels each row with this
                     "kind": s.get("kind", "news"), "url": s["url"]})
    for block, prefix in (("gnews", "Google News · "), ("evidence", "Evidence · ")):
        for loc in cfg.get(block, []):
            srcs.append({"name": prefix + loc["label"], "lang": loc["lang"],
                         "standing": loc["standing"], "region": loc["standing"],
                         "kind": "news", "url": build_gnews_url(loc)})
    return srcs, cfg


def run(dry_run=False, fixtures=None):
    sources, cfg = load_sources()
    print("Reading %d wires…" % len(sources))

    def read(src):
        if fixtures:
            path = os.path.join(fixtures, re.sub(r"[^\w.-]", "_", src["name"]) + ".xml")
            if not os.path.exists(path):
                return src, None
            with open(path, "rb") as fh:
                return src, fh.read()
        return src, fetch(src["url"])

    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for src, raw in pool.map(read, sources):
            results.append((src, raw))

    previous = []
    if os.path.exists(OUT_PATH):
        try:
            with open(OUT_PATH, encoding="utf-8") as fh:
                previous = json.load(fh).get("items", [])
        except Exception:  # noqa: BLE001
            previous = []

    seen_fp, seen_url, items = set(), set(), []

    def absorb(row):
        fp = fingerprint(row["t"])
        cu = canon_url(row["u"])
        if fp in seen_fp or cu in seen_url:
            return False
        seen_fp.add(fp)
        seen_url.add(cu)
        items.append(row)
        return True

    stats, ok_count, refused = [], 0, 0
    for src, raw in results:
        stat = {"name": src["name"], "lang": src["lang"], "standing": src["standing"],
                "region": src["standing"], "kept": 0, "refused": 0, "ok": False}
        if raw:
            stat["ok"] = True
            ok_count += 1
            for row in parse_feed(raw, src):
                text = (row["t"] + " " + row["s"]).lower()
                if hit(text, BLOCK_C):
                    stat["refused"] += 1
                    refused += 1
                    continue
                if not hit(text, ANCHOR_C):
                    continue
                total, reasons = evidence(text, src["standing"])
                row["x"] = topics_for(text) or ["sightings"]
                row["w"] = regions_for(text)
                row["p"] = total
                row["y"] = reasons
                row["st"] = src["standing"]
                if absorb(row):
                    stat["kept"] += 1
        stats.append(stat)
        print("  %-34s %s" % (src["name"][:34],
                              "unreachable" if not raw
                              else "%d kept, %d refused" % (stat["kept"], stat["refused"])))

    fresh_urls = {canon_url(i["u"]) for i in items}
    for row in previous:
        if "x" in row:
            absorb(row)

    cutoff = int(time.time() * 1000) - RETAIN_DAYS * 86400000
    items = [i for i in items if (i.get("d") or cutoff + 1) >= cutoff]
    items.sort(key=lambda i: i.get("d") or 0, reverse=True)
    items = items[:MAX_ITEMS]
    fresh = sum(1 for i in items if canon_url(i["u"]) in fresh_urls)

    languages = {}
    for loc in cfg.get("gnews", []):
        languages.setdefault(loc["lang"], re.sub(r"\s*\(.*\)$", "", loc["label"]))
    languages.setdefault("en", "English")

    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": {"stories": len(items), "new_this_run": fresh,
                   "languages": len({i["g"] for i in items}),
                   "documented": sum(1 for i in items if i.get("p", 0) >= DOCUMENTED_SCORE),
                   "refused": refused,
                   "wires_ok": ok_count, "wires_total": len(sources)},
        "documented_score": DOCUMENTED_SCORE,
        "languages": languages,
        "standings": [
            {"id": "official", "label": "Official"},
            {"id": "science", "label": "Science"},
            {"id": "press", "label": "Press"},
            {"id": "specialist", "label": "Specialist"},
            {"id": "sceptic", "label": "Sceptical"},
        ],
        "topics": [{"id": tid, "label": label} for tid, label, _ in TOPICS],
        "geo": ([{"id": gid, "label": label} for gid, label, _ in GEO] +
                [{"id": "unlocated", "label": "No single region"}]),
        "sources": stats,
        "items": items,
    }

    print("\n%d stories (%d new, %d documented) · %d refused as esoteric · %d languages · %d/%d wires answered"
          % (len(items), fresh, payload["counts"]["documented"], refused,
             payload["counts"]["languages"], ok_count, len(sources)))

    if dry_run:
        print("\n--dry-run: wire_uap.json not written")
        return payload

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    print("Wrote %s (%.0f KB)" % (OUT_PATH, os.path.getsize(OUT_PATH) / 1024))
    return payload


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fixtures")
    args = ap.parse_args()
    run(dry_run=args.dry_run, fixtures=args.fixtures)
