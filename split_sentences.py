"""Split the scraped posts/comments into single sentences and keep only the positive ones.

Usage (in PyCharm's Terminal):
    venv\\Scripts\\python.exe split_sentences.py
Reads the two CSVs made by fb_burmese_sentiment.py and writes
positive_sentences.xlsx (one sentence per row) and positive_sentences.txt.
"""
import os
import re
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
# Reuse the same word lists and rules as the scraper (importing it doesn't open Chrome)
from fb_burmese_sentiment import (POSTS_CSV, COMMENTS_CSV, QUESTION_RE, clean_text,  # noqa: E402
                                  find_sentiment, is_burmese_only, PHONE_RE)

OUT_XLSX = os.path.join(BASE_DIR, "positive_sentences.xlsx")
OUT_TXT = os.path.join(BASE_DIR, "positive_sentences.txt")
MIN_LEN = 12  # characters; drops tiny fragments

# Burmese full stop ။, plus ! ? and line breaks
SPLIT_RE = re.compile(r"(?<=[။!?！？])|\n+")


def split_sentences(text):
    for part in SPLIT_RE.split(clean_text(text)):
        s = part.strip(" ()*-–—\"“”'")
        if s:
            yield s


def positive_sentences(texts):
    seen, out = set(), []
    for text in texts:
        for s in split_sentences(text):
            if len(s) < MIN_LEN or s in seen:
                continue
            if QUESTION_RE.search(s) or PHONE_RE.search(s) or not is_burmese_only(s):
                continue
            label, level, words = find_sentiment(s)
            if label == "positive":
                seen.add(s)
                out.append({"sentence": s, "sentiment": "positive",
                            "sentiment_level": level, "matched_words": ",".join(sorted(set(words)))})
    return out


def main(paths):
    texts = []
    for path in paths:
        if os.path.exists(path):
            df = pd.read_csv(path, encoding="utf-8-sig")
            col = "post" if "post" in df.columns else "comment"
            texts += df[col].dropna().astype(str).tolist()
    rows = positive_sentences(texts)
    pd.DataFrame(rows).to_excel(OUT_XLSX, index=False)
    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(r["sentence"] for r in rows))
    print(f"{len(rows)} positive sentences -> {OUT_XLSX}")


if __name__ == "__main__":
    main(sys.argv[1:] or [POSTS_CSV, COMMENTS_CSV])
