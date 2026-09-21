#!/usr/bin/env python3
"""Autonomous finance-commentary Twitter/X bot. Run with --dry-run to test without posting."""
import argparse
import calendar
import hashlib
import html
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests
import trafilatura
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from dotenv import load_dotenv
from openai import OpenAI

FINNHUB_URL = "https://finnhub.io/api/v1/news"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
LLM_MODEL = "openai/gpt-oss-120b"
BUFFER_API_URL = "https://api.buffer.com"
POSTED_LOG = Path(__file__).resolve().parent / "posted_log.json"
GROWTH_PLAYBOOK_PATH = Path(__file__).resolve().parent / "growth_playbook.md"
VOICE_EXAMPLES_PATH = Path(__file__).resolve().parent / "voice_examples.txt"
SCHEDULE_CONFIG_PATH = Path(__file__).resolve().parent / "schedule_config.json"
DEFAULT_SCHEDULE = {"posts_per_day": 3, "start_hour": 9, "end_hour": 18}
PROFILE_PATH = Path(__file__).resolve().parent / "profile.json"
PERSONA_PATH = Path(__file__).resolve().parent / "persona.md"
IDEAS_PATH = Path(__file__).resolve().parent / "ideas.txt"
USED_PATH = Path(__file__).resolve().parent / "used.json"
STARTER_DIR = Path(__file__).resolve().parent / "starter"
DEFAULT_PROFILE = {
    "topic": "your niche", "char_limit": 280, "feeds": [], "finnhub": False,
    "hashtag_examples": "#blessed, #love, #trending, #viral, #follow",
    "hedge_examples": '"just my opinion", "hope this helps"',
}
MAX_ITEM_AGE = timedelta(days=30)

HUMOR_GUARDRAILS = """<humor_guardrails>
A forced joke is worse than no joke — if nothing in today's material is actually funny,
use mode 1 instead. Never explain the joke. Never laugh at your own joke (no "😂", no "lol"
as a sentence-ender). Don't reach for slang you're not confident lands naturally — a
wrong-generation meme reference is more embarrassing than just being sincere. The joke
needs a real insight underneath it, not a meme format slapped onto a headline.
</humor_guardrails>"""

HARD_CONSTRAINTS = """<hard_constraints>
- Under {char_limit} characters, total, including any emoji/punctuation.
- 0 or 1 emoji. Never more than 1. Most tweets should have 0.
- No hashtags. Not even one. Not {hashtag_examples} —
  none of that.
- Output ONLY the tweet text. No preamble, no "Here's a tweet:", no quotation marks around
  it, no explanation after.
- Never write as an assistant, never mention you are an AI, never hedge legally
  ({hedge_examples}).
</hard_constraints>"""

BANNED_PHRASES = """<banned_phrases>
Never use these or close variants — they read as obviously AI-generated:
"In the fast-paced world of", "Delving into", "A tapestry of", "It's important to note",
"In today's ever-evolving", "Navigating the landscape", "Let's dive in", "Unpack",
"Game-changer", "In conclusion", "Overall,", "As we can see", "It's worth noting",
"In summary", "At the end of the day", "The bottom line is"
</banned_phrases>"""

NEWS_TASK = """<task>
You'll be given a handful of today's real {topic} stories, with the full article text
where it was available. Read the actual story, not just the headline. Pick the single most
tweet-worthy one and write a tweet with a real opinion or insight about what it MEANS —
an implication, a consequence, who it affects and how, what happens next — not a
restatement of the headline in your own words. Choose whichever voice mode actually fits.
</task>"""

IDEA_TASK = """<task>
You'll be given a personal note from the account owner — an idea, a win, something they
learned or noticed — not a news story. Turn it into a post in their voice. Use ONLY what the
note actually says: never invent numbers, results, events, names or experiences that aren't
in it, because this is their real life and they'll be posting it as their own. Keep whatever
makes it specific and personal, lead with the most interesting part, and add an opinion or
takeaway only if the note supports one. Choose whichever voice mode actually fits.
</task>"""


def _retry(func, *args, attempts=3, base_delay=2, label=None, **kwargs):
    label = label or func.__name__
    last_exc = None
    for i in range(attempts):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exc = e
            logging.warning(f"{label} failed (attempt {i + 1}/{attempts}): {e}")
            if i < attempts - 1:
                time.sleep(base_delay * 2 ** i)
    logging.error(f"{label} failed after {attempts} attempts: {last_exc}")
    return None


def _require_env(*names):
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        sys.exit(f"Missing required environment variables: {', '.join(missing)}")


def _log_post(text, when=None):
    entries = json.loads(POSTED_LOG.read_text()) if POSTED_LOG.exists() else []
    entries.append({"timestamp": (when or datetime.now()).isoformat(), "text": text})
    POSTED_LOG.write_text(json.dumps(entries, indent=2))


def _build_user_message(news_items, topic="financial"):
    stories = []
    for n in news_items:
        block = f"HEADLINE: {n['headline']} ({n['source']})"
        if n.get("body"):
            block += f"\nARTICLE TEXT: {n['body']}"
        stories.append(block)
    return (
        f"Here are today's top {topic} stories, with article text where it was available:\n\n"
        + "\n\n".join(stories) +
        "\n\nPick the single most tweet-worthy one. Read past the headline — react to what "
        "the story actually says, not just its title."
    )


def _build_idea_message(idea):
    return (
        "Here is a note from the account owner — a personal idea or experience, not a news story:\n\n"
        f"NOTE: {idea}\n\n"
        "Write the post. Use only what the note says; don't add facts, numbers or events that aren't in it."
    )


def _enforce_length(text, limit=280):
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def load_schedule_config():
    if SCHEDULE_CONFIG_PATH.exists():
        return {**DEFAULT_SCHEDULE, **json.loads(SCHEDULE_CONFIG_PATH.read_text())}
    return dict(DEFAULT_SCHEDULE)


def save_schedule_config(posts_per_day, start_hour, end_hour):
    SCHEDULE_CONFIG_PATH.write_text(json.dumps(
        {"posts_per_day": posts_per_day, "start_hour": start_hour, "end_hour": end_hour}, indent=2
    ))


def _pick_daily_times(now, posts_per_day=3, start_hour=9, end_hour=18, rng=random):
    """Pick one random datetime inside each equal slice of the [start_hour, end_hour) window."""
    window_start = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    slice_seconds = (end_hour - start_hour) * 3600 / posts_per_day
    times = []
    for i in range(posts_per_day):
        slice_start = window_start + timedelta(seconds=i * slice_seconds)
        times.append(slice_start + timedelta(seconds=rng.randint(0, int(slice_seconds))))
    return times


def _is_extractable_url(url):
    """Google News redirect links (news.google.com/rss/articles/...) resolve client-side via JS —
    a plain GET returns Google's own shell page, not the article, so they're not worth fetching."""
    return bool(url) and "news.google.com" not in url


def _fetch_article_text(url, max_chars=1500):
    """Best-effort full article text so the model can react to substance, not just a headline."""
    try:
        resp = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0 (compatible; SummitBot/1.0)"})
        resp.raise_for_status()
        text = trafilatura.extract(resp.text)
        return text[:max_chars] if text else None
    except Exception:
        return None


def fetch_news():
    def _fetch():
        resp = requests.get(
            FINNHUB_URL,
            params={"category": "general"},
            headers={"X-Finnhub-Token": os.environ["FINNHUB_API_KEY"]},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    data = _retry(_fetch, label="fetch_news")
    if not data:
        return []
    data.sort(key=lambda n: n.get("datetime", 0), reverse=True)

    items = []
    for n in data:
        if not n.get("headline") or not _is_extractable_url(n.get("url")):
            continue
        items.append({"headline": n["headline"], "source": n.get("source", ""), "url": n["url"]})
        if len(items) == 5:
            break

    for item in items:
        item["body"] = _fetch_article_text(item["url"])
    return items


def load_profile():
    saved = json.loads(PROFILE_PATH.read_text()) if PROFILE_PATH.exists() else {}
    return {**DEFAULT_PROFILE, **saved}


def save_profile(profile):
    PROFILE_PATH.write_text(json.dumps({k: profile[k] for k in DEFAULT_PROFILE}, indent=2) + "\n")


def load_persona():
    return (PERSONA_PATH if PERSONA_PATH.exists() else STARTER_DIR / "persona.md").read_text().strip()


def save_persona(text):
    PERSONA_PATH.write_text(text.strip() + "\n")


def _load_growth_playbook():
    """Re-read on every call so edits to growth_playbook.md take effect without a restart."""
    path = GROWTH_PLAYBOOK_PATH if GROWTH_PLAYBOOK_PATH.exists() else STARTER_DIR / "growth_playbook.md"
    return path.read_text() if path.exists() else ""


def load_voice_examples():
    if not VOICE_EXAMPLES_PATH.exists():
        return []
    return [line.strip() for line in VOICE_EXAMPLES_PATH.read_text().splitlines() if line.strip()]


def save_voice_examples(examples):
    VOICE_EXAMPLES_PATH.write_text("\n".join(e.strip() for e in examples if e.strip()) + "\n")


def load_ideas():
    return [l.strip() for l in IDEAS_PATH.read_text().splitlines() if l.strip()] if IDEAS_PATH.exists() else []


def save_ideas(ideas):
    IDEAS_PATH.write_text("".join(" ".join(i.split()) + "\n" for i in ideas if i.strip()))


def _idea_key(idea):
    return "idea:" + hashlib.sha1(idea.encode()).hexdigest()[:12]


def load_used():
    return json.loads(USED_PATH.read_text()) if USED_PATH.exists() else {}


def prune_used(used, keep=500):
    return dict(sorted(used.items(), key=lambda kv: kv[1])[-keep:])


def save_used(used):
    USED_PATH.write_text(json.dumps(prune_used(used), indent=2))


def mark_used(used, key):
    used[key] = datetime.now().isoformat()


def _voice_examples_block():
    examples = load_voice_examples()
    if not examples:
        body = "(none provided yet — using a generic casual voice)"
    else:
        body = "\n".join(f"<example>{e}</example>" for e in examples)
    return f"<my_voice_examples>\n{body}\n</my_voice_examples>"


def build_system_prompt(profile, kind="news"):
    """Niche layer (persona.md) + fixed core rules + the task for this kind of post ('news' or 'idea')."""
    task = IDEA_TASK if kind == "idea" else NEWS_TASK.replace("{topic}", profile["topic"])
    rules = (HARD_CONSTRAINTS.replace("{char_limit}", str(profile["char_limit"]))
             .replace("{hashtag_examples}", profile["hashtag_examples"])
             .replace("{hedge_examples}", profile["hedge_examples"]))
    return "\n\n".join([load_persona(), HUMOR_GUARDRAILS, rules, BANNED_PHRASES, task])


def _entry_ts(entry):
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    return calendar.timegm(t) if t else 0


def _strip_html(text):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text or "")).split())


def inspect_feed(url):
    """Fetch and parse one RSS/Atom feed. Returns {"title", "total", "walled", "items"}: items are the usable
    stories, newest first; walled counts entries hidden behind Google News redirects. Raises if it isn't a feed."""
    resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (compatible; SummitBot/1.0)"})
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    if not feed.get("version"):  # 'rss20'/'atom10'/... for real feeds (even empty or slightly broken); blank for web pages
        raise ValueError("that URL isn't an RSS/Atom feed")
    source = feed.feed.get("title") or url
    cutoff = time.time() - MAX_ITEM_AGE.total_seconds()
    items, walled = [], 0
    for e in sorted(feed.entries, key=_entry_ts, reverse=True):
        link, ts = e.get("link"), _entry_ts(e)
        if not e.get("title") or not link:
            continue
        if not _is_extractable_url(link):
            walled += 1
        elif not ts or ts >= cutoff:
            items.append({"headline": e.title, "source": source, "url": link, "summary": _strip_html(e.get("summary"))})
    return {"title": source, "total": len(feed.entries), "walled": walled, "items": items}


def read_feed(url, used=()):
    """Newest-first, unseen, readable stories from one feed."""
    return [i for i in inspect_feed(url)["items"] if i["url"] not in used]


def next_feed_item(feeds, used, rng=random):
    """A random feed's newest unseen story, with its article text. Returns (item or None, feeds that failed)."""
    by_feed, failed = [], 0
    for url in feeds:
        try:
            items = read_feed(url, used)
        except Exception as e:
            logging.warning(f"feed {url} failed: {e}")
            failed += 1
            continue
        if items:
            by_feed.append(items)
    if not by_feed:
        return None, failed
    item = rng.choice(by_feed)[0]
    article = _fetch_article_text(item["url"])
    item["body"] = article or item["summary"][:1500] or None
    item["body_from"] = "full article" if article else "feed summary" if item["body"] else "headline only"
    return item, failed


PERSONA_DRAFT_PROMPT = """Below is the persona section of a system prompt that makes an LLM ghostwrite short X posts for a person who posts about stocks and macro markets:

<example_persona>
{example}
</example_persona>

Write the equivalent persona section for someone who describes their account like this:

<their_description>
{description}
</their_description>

Rules:
- Keep the exact same structure: one intro line ("You are ghostwriting tweets for a real person who ..."), then a <voice> block with the same bullets — two modes (hot take, funny observation), the explicit decision rule, and the closing style bullet.
- Adapt the tone, the example stances and the joke formats to THIS niche and to how they said they sound. Riff on formats that insiders of this niche genuinely share; never invent specific inside jokes, facts or events.
- If the niche is personal or hobby-based rather than newsy, keep both modes but make the decision rule about genuinely serious material (tragedy, safety, real hardship) versus everything else.
- No markdown, no commentary.

Reply in exactly this format:
TOPIC: <one to three lowercase words naming the niche, usable in the phrase "today's real ___ stories">
---
<the persona text>"""


def parse_persona_draft(raw):
    """Split the model's reply into (topic, persona); raises ValueError if it isn't in the expected shape."""
    head, sep, body = (raw or "").partition("\n---")
    topic = " ".join(head.removeprefix("TOPIC:").strip().strip('"').lower().split())[:40]
    persona = body.strip()
    if not (sep and topic and "<voice>" in persona and "</voice>" in persona):
        raise ValueError("The draft came back in the wrong shape — please try again.")
    return topic, persona


def draft_persona(description):
    """Draft a persona for a new niche from a plain-English description, modelled on the finance example."""
    client = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url=GROQ_BASE_URL)
    example = (STARTER_DIR / "example_persona_finance.md").read_text().strip()
    prompt = PERSONA_DRAFT_PROMPT.replace("{example}", example).replace("{description}", description.strip())

    def _ask():
        resp = client.chat.completions.create(model=LLM_MODEL, max_tokens=2500, reasoning_effort="low",
                                              messages=[{"role": "user", "content": prompt}])
        return resp.choices[0].message.content.strip()

    raw = _retry(_ask, label="draft_persona")
    if raw is None:
        raise RuntimeError("Couldn't reach the AI right now — please try again shortly.")
    return parse_persona_draft(raw)


def generate_tweet(news_items=None, idea=None):
    profile = load_profile()
    client = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url=GROQ_BASE_URL)
    user = _build_idea_message(idea) if idea else _build_user_message(news_items, profile["topic"])

    def _generate():
        system = "\n\n".join([build_system_prompt(profile, "idea" if idea else "news"),
                               _voice_examples_block(), _load_growth_playbook()])
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            max_tokens=300,
            reasoning_effort="low",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content.strip().strip('"')

    tweet = _retry(_generate, label="generate_tweet")
    return _enforce_length(tweet, profile["char_limit"]) if tweet else None


def draft_post(used, rng=random):
    """Choose what the next post is about (news, a feed story, or one of the owner's ideas) and write it.
    Returns (draft, reason). draft is {"text", "kind", "key", "source", "note"} — key is what to mark used once it's
    actually posted — or None with a reason. "nothing new" is normal for slow niches; anything else is a failure."""
    profile = load_profile()
    idea = next((i for i in load_ideas() if _idea_key(i) not in used), None)
    kinds = [k for k, on in (("finnhub", profile["finnhub"]), ("rss", profile["feeds"]), ("idea", idea)) if on]
    rng.shuffle(kinds)
    reason = "nothing new"
    for kind in kinds:
        if kind == "idea":
            material, key, source, note = {"idea": idea}, _idea_key(idea), "Your idea: " + idea, "personal note"
        elif kind == "rss":
            item, failed = next_feed_item(profile["feeds"], used, rng)
            if not item:
                if failed == len(profile["feeds"]):
                    reason = "couldn't reach any of your feeds"
                continue
            material, key, source, note = {"news_items": [item]}, item["url"], item["headline"], f"story text: {item['body_from']}"
        else:
            news = fetch_news()
            if not news:
                reason = "couldn't fetch news"
                continue
            material, key, source = {"news_items": news}, None, news[0]["headline"]
            note = f"{sum(1 for n in news if n.get('body'))}/{len(news)} stories had readable article text"
        text = generate_tweet(**material)
        draft = {"text": text, "kind": kind, "key": key, "source": source, "note": note}
        return (draft, None) if text else (None, "tweet generation failed")
    return None, reason


def _buffer_graphql(query):
    resp = requests.post(
        BUFFER_API_URL,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['BUFFER_API_KEY']}"},
        json={"query": query},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    return payload["data"]


def get_buffer_channels():
    """Returns [{id, name, service, organization}] for every channel connected in Buffer."""
    orgs = _buffer_graphql("query { account { organizations { id name } } }")["account"]["organizations"]
    channels = []
    for org in orgs:
        result = _buffer_graphql(
            f'query {{ channels(input: {{ organizationId: {json.dumps(org["id"])} }}) {{ id name service }} }}'
        )["channels"]
        for ch in result:
            channels.append({**ch, "organization": org["name"]})
    return channels


def list_buffer_channels():
    """One-off setup helper (python bot.py --list-channels): prints channelIds to put in .env."""
    for ch in get_buffer_channels():
        print(f"[{ch['organization']}] {ch['service']:10s} {ch['name']:20s} BUFFER_CHANNEL_ID={ch['id']}")


def create_buffer_post(text, due_at=None):
    """Hand `text` to Buffer to publish at due_at (an aware datetime; default 30s from now). Returns the post id."""
    due = (due_at or datetime.now(timezone.utc) + timedelta(seconds=30)).astimezone(timezone.utc)
    due_str = due.strftime("%Y-%m-%dT%H:%M:%S.") + f"{due.microsecond // 1000:03d}Z"
    mutation = f"""
    mutation {{
      createPost(input: {{
        text: {json.dumps(text)},
        channelId: {json.dumps(os.environ["BUFFER_CHANNEL_ID"])},
        schedulingType: automatic,
        mode: customScheduled,
        dueAt: {json.dumps(due_str)}
      }}) {{
        ... on PostActionSuccess {{ post {{ id }} }}
        ... on MutationError {{ message }}
      }}
    }}
    """
    result = _buffer_graphql(mutation)["createPost"]
    if "message" in result:
        raise RuntimeError(result["message"])
    return result["post"]["id"]


def post_tweet(text, dry_run=False, due_at=None):
    if dry_run:
        print("\n--- DRY RUN: would post ---")
        print(text)
        print(f"({len(text)} chars)")
        print("---------------------------\n")
        return True

    ok = _retry(lambda: create_buffer_post(text, due_at), label="post_tweet")
    if ok:
        _log_post(text, due_at.astimezone().replace(tzinfo=None) if due_at else None)
        logging.info("Posted tweet.")
    else:
        logging.error("Failed to post tweet after retries.")
    return bool(ok)


def run_cycle(dry_run=False):
    logging.info("Starting posting cycle...")
    used = load_used()
    draft, reason = draft_post(used)
    if not draft:
        logging.warning(f"Skipping this cycle — {reason}.")
        return
    if post_tweet(draft["text"], dry_run=dry_run) and draft["key"] and not dry_run:
        mark_used(used, draft["key"])
        save_used(used)


def schedule_day(scheduler, dry_run):
    now = datetime.now()
    config = load_schedule_config()
    for t in _pick_daily_times(now, config["posts_per_day"], config["start_hour"], config["end_hour"]):
        if t <= now:
            logging.info(f"Skipping past slot {t.strftime('%H:%M')}")
            continue
        scheduler.add_job(run_cycle, DateTrigger(run_date=t), args=[dry_run], misfire_grace_time=3600)
        logging.info(f"Scheduled post at {t.strftime('%H:%M:%S')}")


def add_daily_reschedule(scheduler, dry_run=False):
    """Midnight job that picks the next day's random times. The 18h grace matters: without it a machine
    asleep at 00:05 misses the job (APScheduler's default grace is 1s) and posts nothing that day."""
    scheduler.add_job(schedule_day, CronTrigger(hour=0, minute=5), args=[scheduler, dry_run],
                      id="daily_reschedule", replace_existing=True, misfire_grace_time=18 * 3600)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Fetch news + generate a tweet, print instead of posting")
    parser.add_argument("--list-channels", action="store_true", help="Print Buffer channelIds for .env, then exit")
    args = parser.parse_args()

    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(Path(__file__).resolve().parent / "bot.log")],
    )

    if args.list_channels:
        _require_env("BUFFER_API_KEY")
        list_buffer_channels()
        return

    needs = ["GROQ_API_KEY"] + (["FINNHUB_API_KEY"] if load_profile()["finnhub"] else [])
    if args.dry_run:
        _require_env(*needs)
        run_cycle(dry_run=True)
        return

    _require_env(*needs, "BUFFER_API_KEY", "BUFFER_CHANNEL_ID")
    scheduler = BlockingScheduler()
    add_daily_reschedule(scheduler)
    schedule_day(scheduler, False)
    logging.info("Scheduler started. Waiting for scheduled posts...")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
