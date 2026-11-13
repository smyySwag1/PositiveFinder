import os
import random
import re
import time
import unicodedata
import urllib.parse

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import (StaleElementReferenceException, TimeoutException,
                                        WebDriverException)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# Optional: detects Zawgyi-encoded text (pip install myanmartools).
# Zawgyi text will not match a Unicode lexicon, so it is skipped when detected.
try:
    from myanmartools import ZawgyiDetector
    _ZAWGYI = ZawgyiDetector()
except ImportError:
    _ZAWGYI = None

# ============================================================
# BURMESE-ONLY + POSITIVE-ONLY + NO LINKS
# ============================================================

MAIN_KEYWORDS = [
    "ဂျပန်တက္ကသိုလ်",
    "ဂျပန်ပညာသင်ဆု",
]

KEYWORD_VARIANTS = {
    "ဂျပန်တက္ကသိုလ်": [
        "ဂျပန်တက္ကသိုလ်",
        "ဂျပန် uni",
        "ဂျပန် ယူနီ",
        "ဂျပန် တက္ကသိုလ်ဝင်ခွင့်",
        "ဂျပန် တက္ကသိုလ် လျှောက်",
        "E-track",
        "J-track",
        "EJU",
        "JLPT",
        # positive-leaning searches: success stories and congratulations
        "ဂျပန် တက္ကသိုလ် အောင်မြင်",
        "ဂျပန် တက္ကသိုလ် ဝင်ခွင့်ရ",
        "ဂျပန် တက္ကသိုလ် ဂုဏ်ယူပါတယ်",
        "ဂျပန် ကျောင်း ပျော်",
        "JLPT အောင်",
        "EJU အောင်",
    ],
    "ဂျပန်ပညာသင်ဆု": [
        "ဂျပန်ပညာသင်ဆု",
        "ပညာသင်ဆု",
        "ဂျပန် ပညာသင်ဆု လျှောက်",
        "scholarship",
        "MEXT",
        # positive-leaning searches: success stories and congratulations
        "ပညာသင်ဆု ရရှိ",
        "ပညာသင်ဆု ရရှိခဲ့",
        "ပညာသင်ဆု ဂုဏ်ယူပါတယ်",
        "ပညာသင်ဆု ဝမ်းသာ",
        "MEXT ရရှိ",
        "MEXT အောင်",
    ],
}

# ---------------------------
# Myanmar sentiment lexicon WITH LEVELS
# ---------------------------
# Higher level = stronger. A word directly after မ is flipped
# (ကောင်း = good -> မကောင်း = not good), so negated positives are rejected.
POS_WORDS = {
    3: [
        "ရရှိခဲ့", "အောင်မြင်", "ဂုဏ်ယူ", "ဂုဏ်ပြု", "ဝမ်းသာ", "ဝမ်းမြောက်",
        "ပျော်ရွှင်", "ပီတိ", "အရမ်းကောင်း", "အကောင်းဆုံး", "ကံကောင်း",
        "ထူးချွန်", "အားကျ", "Congrat", "congrat",
    ],
    2: [
        "ပျော်", "ကောင်း", "ကျေနပ်", "ကျေးဇူးတင်", "ကျေးဇူးအများကြီး", "သဘောကျ",
        "ကြိုက်", "အားပေး", "ဖော်ရွေ", "မွေ့လျော်", "သဘောကောင်း", "လှပ",
        "အဆင်ပြေ", "ချောမွေ့", "တန်ဖိုးရှိ", "အသုံးဝင်", "ထိုက်တန်",
        "စိတ်ချ", "ယုံကြည်", "လိမ်မာ",
    ],
    1: [
        "ချစ်", "စိတ်ဝင်စား", "ဆုတောင်း", "အားရ",
        "❤", "❤️", "😍", "🥰", "👍", "👏", "🎉", "💕", "😊", "🥳",
    ],
}

# Only used to REJECT text: a negative word as strong as (or stronger than)
# the strongest positive word means the text is not saved.
NEG_WORDS = {
    3: ["စိတ်မပါ", "စိတ်ပျက်", "လိမ်လည်", "လိမ်", "ကျရှုံး", "မုန်း"],
    2: ["ဝမ်းနည်း", "ဆိုး", "စိတ်ညစ်", "ရှုံး", "ဒေါသ", "အဆင်မပြေ", "😡", "😢", "😭", "👎"],
    1: ["ညံ့", "မရ", "ခက်ခဲ", "ပင်ပန်း", "စိုးရိမ်", "ပူပန်"],
    # "မရ" only counts as a whole syllable (not မရေ / မရော / မရှိ)
}

# Facebook text is NFC-normalized in clean_text(), so the lexicon must be too.
POS_WORDS = {lv: [unicodedata.normalize("NFC", w) for w in ws] for lv, ws in POS_WORDS.items()}
NEG_WORDS = {lv: [unicodedata.normalize("NFC", w) for w in ws] for lv, ws in NEG_WORDS.items()}

# Questions ("ကောင်းလား" = is it good?) aren't positive statements.
QUESTION_RE = re.compile(r"[?？]|လား")

NEGATOR = "မ"  # a word directly preceded by မ flips polarity (မချစ် = don't like)

# ---------------------------
# PATHS
# ---------------------------
# Everything lives next to this script, so the project works from any folder.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Optional: put chromedriver.exe next to this script. If it isn't there,
# Selenium downloads a matching driver automatically.
CHROMEDRIVER_PATH = os.path.join(BASE_DIR, "chromedriver.exe")
SELENIUM_PROFILE_DIR = os.path.join(BASE_DIR, "selenium_profile")  # keeps your Facebook login
os.makedirs(SELENIUM_PROFILE_DIR, exist_ok=True)

POSTS_CSV = os.path.join(BASE_DIR, "posts_BURMESE_ONLY_POSITIVE_test3_main.csv")
COMMENTS_CSV = os.path.join(BASE_DIR, "comments_BURMESE_ONLY_POSITIVE_test3_main.csv")

# ---------------------------
# TUNING
# ---------------------------
# Stop the whole run once this many positive rows (posts + comments) are saved.
# Set to None to collect as much as possible.
TARGET_TOTAL = 200

SEARCH_SCROLLS = 45
MAX_OPEN_POSTS_PER_VARIANT = 18
COMMENT_ROUNDS = 6
MAX_COMMENTS_PER_POST = 40  # spread rows over many posts instead of a few busy ones

TARGET_POSTS_PER_MAIN = 450
TARGET_COMMENTS_PER_MAIN = 1200

MIN_SLEEP = 0.5
MAX_SLEEP = 1.2

MIN_POST_LEN = 1
MIN_COMMENT_LEN = 1
MAX_LATIN_RATIO = 0.25  # lets posts with EJU / JLPT / MEXT through

# Skip advertising posts (schools/agencies with phone numbers, "contact us", "register").
# They use friendly words but aren't real opinions. Set False to keep them.
SKIP_PROMOTIONS = True

# ---------------------------
# CLEANING / FILTERS
# ---------------------------
URL_RE = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)
SHORTENER_RE = re.compile(r"\b(bit\.ly|t\.co|goo\.gl|tinyurl\.com|t\.me|fb\.me)\b", re.IGNORECASE)
HASHTAG_RE = re.compile(r"#\S+")
MENTION_RE = re.compile(r"@\w+")
ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200D\u2060\uFEFF\u00AD]")
WS_RE = re.compile(r"\s+")
SEE_MORE_RE = re.compile(r"(…|\.\.\.)?\s*\b(See more|See less|See original|See translation)\b", re.IGNORECASE)

JP_CHAR_RE = re.compile(r"[\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uFF00-\uFFEF]")

SPONSORED_WORDS = ["sponsored", "広告", "スポンサー", "ကြော်ငြာ", "စပွန်ဆာ"]
LOW_VALUE_RE = re.compile(
    r"(?<![a-z])(inbox|dm|pm|messenger|cb|link|pls|please|info)(?![a-z])", re.IGNORECASE
)
UI_LABELS = {
    "like", "reply", "share", "send", "see more", "view more", "edited", "author",
    "いいね！", "返信する", "シェア", "送信", "もっと見る", "編集済み",
}


class TargetReached(Exception):
    pass


def check_target(all_posts, all_comments):
    if TARGET_TOTAL is not None and len(all_posts) + len(all_comments) >= TARGET_TOTAL:
        raise TargetReached


def sleep_human(a=MIN_SLEEP, b=MAX_SLEEP):
    time.sleep(random.uniform(a, b))


def clean_text(text: str) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFC", text)
    t = ZERO_WIDTH_RE.sub("", t)  # zero-width chars silently break substring matching
    t = URL_RE.sub(" ", t)
    t = HASHTAG_RE.sub(" ", t)
    t = MENTION_RE.sub(" ", t)
    t = SEE_MORE_RE.sub(" ", t)
    return WS_RE.sub(" ", t).strip()


def dedup_key(main_kw, text):
    # The start of the text, so a cut-off copy and the full post count as the same post
    return main_kw, re.sub(r"\W+", "", text)[:80]


PHONE_RE = re.compile(r"(\+?95|\b0)\s?9[\d\s-]{7,12}\d|[၀၉][၀-၉\s-]{7,12}[၀-၉]")
PROMO_WORDS = [
    "စုံစမ်း", "စာရင်းပေးသွင်း", "စာရင်းသွင်း", "ဆက်သွယ်", "ဖိတ်ခေါ်", "သင်တန်းကြေး",
    "Messenger", "Viber", "Telegram", "Register", "Intake", "Seminar", "Webinar",
]


def is_promotion(text: str) -> bool:
    if PHONE_RE.search(text):
        return True
    low = text.lower()
    return sum(w.lower() in low for w in PROMO_WORDS) >= 2  # one word alone can be innocent


def has_any_link_left(text: str) -> bool:
    return bool(URL_RE.search(text) or SHORTENER_RE.search(text))


def is_low_value_comment(text: str) -> bool:
    return len(text) < MIN_COMMENT_LEN or bool(LOW_VALUE_RE.search(text))


def looks_zawgyi(text: str) -> bool:
    return _ZAWGYI is not None and _ZAWGYI.get_zawgyi_probability(text) > 0.95


# ---------------------------
# BURMESE FILTER
# ---------------------------
def is_burmese_only(text: str) -> bool:
    if not text or JP_CHAR_RE.search(text):
        return False
    # Count letters, marks and digits (Burmese vowel signs are marks, not \w)
    chars = [c for c in text if unicodedata.category(c)[0] in "LMN"]
    if not chars:
        return False
    my = sum(1 for c in chars if "\u1000" <= c <= "\u109F")
    latin = sum(1 for c in chars if c.isascii() and c.isalpha())
    if my == 0 or latin / len(chars) > MAX_LATIN_RATIO:
        return False
    return my / len(chars) >= 0.60


# ---------------------------
# SENTIMENT DETECTION (with levels)
# ---------------------------
def _is_mark(c: str) -> bool:
    return unicodedata.category(c) in ("Mn", "Mc")


def _occurrences(text: str, word: str):
    """Start indexes where `word` occurs on Burmese syllable boundaries."""
    start = 0
    while True:
        i = text.find(word, start)
        if i == -1:
            return
        end = i + len(word)
        # Not cut mid-syllable: the next char must not be a vowel sign/mark, and must not be
        # a final consonant (consonant + ် or stacked ္), e.g. အားကျ inside အားကျင်းပ
        ends_ok = end >= len(text) or not (
            _is_mark(text[end])
            or (end + 1 < len(text) and text[end + 1] in "\u103A\u1039")
        )
        starts_ok = i == 0 or text[i - 1] != "\u1039"            # not a stacked consonant
        if ends_ok and starts_ok:
            yield i
        start = i + 1


def find_sentiment(text: str):
    # Collect every candidate match from both lexicons
    candidates = []
    for polarity, lexicon in (("positive", POS_WORDS), ("negative", NEG_WORDS)):
        for lvl, words in lexicon.items():
            for w in words:
                for i in _occurrences(text, w):
                    candidates.append((i, i + len(w), w, lvl, polarity))

    # Longest match wins; shorter words inside an already-matched span are ignored
    candidates.sort(key=lambda c: c[1] - c[0], reverse=True)
    taken = [False] * len(text)
    result = {"positive": [0, []], "negative": [0, []]}
    flip = {"positive": "negative", "negative": "positive"}

    for start, end, w, lvl, polarity in candidates:
        if any(taken[start:end]):
            continue
        negated = start > 0 and text[start - 1] == NEGATOR and not taken[start - 1]
        if negated:
            polarity, w = flip[polarity], NEGATOR + w
            start -= 1
        for k in range(start, end):
            taken[k] = True
        result[polarity][0] = max(result[polarity][0], lvl)
        result[polarity][1].append(w)

    pos_level, pos_hits = result["positive"]
    neg_level, neg_hits = result["negative"]

    # Mixed text counts as positive only when the positive side is stronger:
    # "ခက်ခဲပေမဲ့ အောင်မြင်ခဲ့" (hard, but succeeded: 1 vs 3) -> positive
    # "ကောင်းပေမဲ့ စိတ်ပျက်" (good, but disappointed: 2 vs 3) -> negative
    if pos_hits and pos_level > neg_level:
        return "positive", pos_level, pos_hits
    if neg_hits:
        return "negative", neg_level, neg_hits
    return None, None, []


# ---------------------------
# BROWSER HELPERS
# ---------------------------
POST_JS = """
const sel = "div[data-ad-preview='message'], div[data-ad-comet-preview*='message']";
return Array.from(document.querySelectorAll(sel)).map(e => {
  const body = e.innerText || "";
  const art = e.closest("div[role='article']");
  let rest = art ? (art.innerText || "") : "";
  if (body) rest = rest.split(body).join(" ");   // header/footer only, not the post body
  return [body, rest.slice(0, 3000)];
});
"""

COMMENT_JS = """
const out = [];
document.querySelectorAll("div[role='article'] div[dir='auto']").forEach(e => {
  if (e.querySelector("div[dir='auto']")) return;                       // innermost only
  if (e.closest("[data-ad-preview='message'], [data-ad-comet-preview*='message']")) return; // skip post body
  const t = e.innerText;
  if (t) out.push(t);
});
return out;
"""

LINKS_JS = """
return Array.from(document.querySelectorAll(
  "a[href*='/posts/'], a[href*='permalink.php'], a[href*='story.php']"
)).map(a => a.href);
"""


def open_page(url):
    """Open a page without hanging: Facebook pages never fully finish loading."""
    try:
        driver.get(url)
    except TimeoutException:
        try:
            driver.execute_script("window.stop();")  # use whatever has loaded so far
        except WebDriverException:
            pass


def normalize_post_url(href: str) -> str:
    """Strip tracking params so the same post isn't treated as many different links."""
    p = urllib.parse.urlsplit(href)
    if "permalink.php" in p.path or "story.php" in p.path:
        q = urllib.parse.parse_qs(p.query)
        keep = {k: q[k][0] for k in ("story_fbid", "id") if k in q}
        return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(keep), ""))
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def click_buttons(patterns, limit=150, pause=0.05):
    for pat in patterns:
        try:
            elems = driver.find_elements(
                By.XPATH,
                f"//div[@role='button' and contains(., '{pat}')] | "
                f"//span[@role='button' and contains(., '{pat}')]"
            )
        except WebDriverException:
            continue
        for e in elems[:limit]:
            try:
                driver.execute_script("arguments[0].click();", e)
                time.sleep(pause)
            except (StaleElementReferenceException, WebDriverException):
                pass


def click_see_more():
    click_buttons(["See more", "ပိုပြီး", "もっと見る"], limit=120, pause=0.04)


def click_more_comments_buttons():
    click_buttons([
        "more comments", "previous comments", "more replies", "replies", "View all",
        "ပိုမိုကြည့်ရန်", "မှတ်ချက်များ ပိုမိုကြည့်ရန်", "ပြန်ကြားချက်များ ပိုမိုကြည့်ရန်",
        "コメントをもっと見る", "他のコメントを表示", "以前のコメントを表示", "件の返信",
    ], limit=200, pause=0.12)


def scroll_page(max_scrolls=20, on_step=None):
    last_height = driver.execute_script("return document.body.scrollHeight")
    stable = 0
    for _ in range(max_scrolls):
        driver.execute_script(
            "window.scrollTo(0, document.body.scrollHeight - arguments[0]);",
            random.randint(200, 700)
        )
        sleep_human(0.9, 1.6)
        click_see_more()
        if on_step:
            on_step()  # extract while scrolling: Facebook unloads posts that scroll off-screen
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        last_height = new_height


def collect_post_links():
    try:
        hrefs = driver.execute_script(LINKS_JS) or []
    except WebDriverException:
        return []
    links = []
    for href in hrefs:
        if not href or "/groups/" in href:
            continue
        url = normalize_post_url(href)
        if url not in links:
            links.append(url)
    return links


def load_more_comments_round():
    click_see_more()
    click_more_comments_buttons()
    click_see_more()
    driver.execute_script("window.scrollBy(0, arguments[0]);", random.randint(900, 1500))
    sleep_human(0.6, 1.1)


# ---------------------------
# EXTRACT POSTS / COMMENTS
# ---------------------------
def build_row(main_kw, variant_kw, text, label, level, matched, text_col):
    variants = KEYWORD_VARIANTS.get(main_kw, [])
    kw_matched = [kw for kw in variants if kw.lower() in text.lower()]
    return {
        "keyword": main_kw,
        "variant": variant_kw,
        "matched_keywords": ",".join(kw_matched),
        "sentiment": label,
        "sentiment_level": level,
        "matched_words": ",".join(sorted(set(matched))),
        text_col: text,
    }


def extract_posts(main_kw, variant_kw, post_set, out_list) -> int:
    try:
        items = driver.execute_script(POST_JS) or []
    except WebDriverException:
        return 0
    added = 0
    for body, rest in items:
        text = clean_text(body)
        if len(text) < MIN_POST_LEN:
            continue
        rest_low = (rest or "").lower()
        if any(w.lower() in rest_low for w in SPONSORED_WORDS):
            continue
        if has_any_link_left(text) or not is_burmese_only(text) or looks_zawgyi(text):
            continue
        if QUESTION_RE.search(text):
            continue
        if SKIP_PROMOTIONS and is_promotion(text):
            continue
        key = dedup_key(main_kw, text)
        if key in post_set:
            continue
        label, level, matched = find_sentiment(text)
        if label != "positive":  # positive only; a strong-enough negative word rejects the text
            continue
        post_set.add(key)
        out_list.append(build_row(main_kw, variant_kw, text, label, level, matched, "post"))
        added += 1
    return added


def extract_comments(main_kw, variant_kw, comment_set, out_list) -> int:
    try:
        raws = driver.execute_script(COMMENT_JS) or []
    except WebDriverException:
        return 0
    added = 0
    for raw in raws:
        raw = (raw or "").strip()
        if not raw or raw.lower() in UI_LABELS:
            continue
        text = clean_text(raw)
        if len(text) < MIN_COMMENT_LEN:
            continue
        if has_any_link_left(text) or not is_burmese_only(text) or looks_zawgyi(text):
            continue
        if is_low_value_comment(text) or QUESTION_RE.search(text):
            continue
        key = dedup_key(main_kw, text)
        if key in comment_set:
            continue
        label, level, matched = find_sentiment(text)
        if label != "positive":  # positive only; a strong-enough negative word rejects the text
            continue
        comment_set.add(key)
        out_list.append(build_row(main_kw, variant_kw, text, label, level, matched, "comment"))
        added += 1
    return added


# ---------------------------
# SAVE
# ---------------------------
BASE_COLS = ["keyword", "variant", "matched_keywords", "sentiment", "sentiment_level", "matched_words"]


def save(all_posts, all_comments):
    pd.DataFrame(all_posts, columns=BASE_COLS + ["post"]).to_csv(
        POSTS_CSV, index=False, encoding="utf-8-sig")
    pd.DataFrame(all_comments, columns=BASE_COLS + ["comment"]).to_csv(
        COMMENTS_CSV, index=False, encoding="utf-8-sig")


# ---------------------------
# MAIN
# ---------------------------
def collect_from_post(link, main_kw, vkw, post_set, comment_set, all_posts, all_comments):
    open_page(link)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    time.sleep(2.5)  # give comments time to appear
    click_see_more()
    extract_posts(main_kw, vkw, post_set, all_posts)  # full post text lives here, not truncated

    check_target(all_posts, all_comments)

    per_post = 0
    for _ in range(COMMENT_ROUNDS):
        load_more_comments_round()
        per_post += extract_comments(main_kw, vkw, comment_set, all_comments)
        check_target(all_posts, all_comments)
        if per_post >= MAX_COMMENTS_PER_POST:
            break


def main():
    all_posts, all_comments = [], []
    post_set, comment_set, visited_links = set(), set(), set()

    try:
        for main_kw in MAIN_KEYWORDS:
            variants = KEYWORD_VARIANTS.get(main_kw, [main_kw])
            start_posts, start_comments = len(all_posts), len(all_comments)
            print(f"\n==== MAIN KEYWORD: {main_kw} | variants: {len(variants)} ====")

            for vkw in variants:
                print(f"\nSearch variant: {vkw}")
                open_page(f"https://www.facebook.com/search/posts?q={urllib.parse.quote(vkw)}")
                wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                time.sleep(2.5)

                found_links = []

                def step():
                    extract_posts(main_kw, vkw, post_set, all_posts)
                    check_target(all_posts, all_comments)
                    for url in collect_post_links():
                        if url not in visited_links and url not in found_links:
                            found_links.append(url)

                scroll_page(SEARCH_SCROLLS, on_step=step)
                step()

                for link in found_links[:MAX_OPEN_POSTS_PER_VARIANT]:
                    visited_links.add(link)
                    try:
                        collect_from_post(link, main_kw, vkw, post_set, comment_set,
                                          all_posts, all_comments)
                    except TargetReached:
                        raise
                    except Exception as e:  # one bad post must not end the whole run
                        print(f"  skipped a post: {type(e).__name__}")
                    sleep_human(0.4, 0.9)

                print(f"  opened {min(len(found_links), MAX_OPEN_POSTS_PER_VARIANT)} posts for comments")
                save(all_posts, all_comments)  # checkpoint after every variant
                print(f"  so far: {len(all_posts)} posts, {len(all_comments)} comments")

                if (len(all_posts) - start_posts) >= TARGET_POSTS_PER_MAIN and \
                   (len(all_comments) - start_comments) >= TARGET_COMMENTS_PER_MAIN:
                    print("Reached targets for this MAIN keyword. Moving on.")
                    break

            print(f"Collected for {main_kw}: +{len(all_posts) - start_posts} posts, "
                  f"+{len(all_comments) - start_comments} comments")
    except TargetReached:
        print(f"\nReached {TARGET_TOTAL} positive rows. Stopping.")
    finally:
        save(all_posts, all_comments)  # also runs on Ctrl+C or a crash
        driver.quit()
        print(f"Total: {len(all_posts)} posts + {len(all_comments)} comments")
        print(f"Saved: {POSTS_CSV}")
        print(f"Saved: {COMMENTS_CSV}")


if __name__ == "__main__":
    options = Options()
    options.add_argument(f"--user-data-dir={SELENIUM_PROFILE_DIR}")
    options.add_argument("--profile-directory=SeleniumProfile")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.page_load_strategy = "eager"  # don't wait for every image/video to load

    if os.path.exists(CHROMEDRIVER_PATH):
        driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
    else:
        driver = webdriver.Chrome(options=options)  # Selenium finds/downloads the driver
    driver.set_page_load_timeout(30)  # well under Selenium's own 120 s connection timeout
    wait = WebDriverWait(driver, 15)

    driver.get("https://www.facebook.com")
    input("Log in manually, then press Enter here...")
    main()
