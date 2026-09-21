#!/usr/bin/env python3
"""Local control panel for bot.py: setup wizard + automation dashboard. Run: python webapp.py"""
import json
import logging
import os
from pathlib import Path

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv, set_key, dotenv_values
from flask import Flask, jsonify, render_template, request

import bot
import cloud_run

ENV_PATH = Path(__file__).resolve().parent / ".env"
AUTOMATION_STATE_PATH = Path(__file__).resolve().parent / "automation_state.json"
LOG_PATH = Path(__file__).resolve().parent / "bot.log"

load_dotenv(ENV_PATH)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_PATH)],
)

app = Flask(__name__)
app.jinja_env.auto_reload = True
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
scheduler = BackgroundScheduler()
scheduler.start()


def _load_automation_state():
    if AUTOMATION_STATE_PATH.exists():
        return json.loads(AUTOMATION_STATE_PATH.read_text())
    return {"enabled": False}


def _save_automation_state(enabled):
    automation["enabled"] = enabled
    AUTOMATION_STATE_PATH.write_text(json.dumps({"enabled": enabled}))


automation = _load_automation_state()


def _arm_automation():
    bot.add_daily_reschedule(scheduler)
    bot.schedule_day(scheduler, False)


if automation["enabled"]:
    _arm_automation()


def _all_history():
    """Posts made from this machine plus posts the cloud runner made while it was off (arrives via git pull)."""
    local = json.loads(bot.POSTED_LOG.read_text()) if bot.POSTED_LOG.exists() else []
    return sorted(local + cloud_run.load_state().get("history", []), key=lambda h: h["timestamp"])


def _http_error_message(e):
    if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
        if e.response.status_code in (401, 403):
            return "Key rejected — double check it's correct."
        return f"API returned HTTP {e.response.status_code}."
    return "Couldn't reach the API — check your network connection."


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def state():
    env = dotenv_values(ENV_PATH)
    profile = bot.load_profile()
    ideas = bot.load_ideas()
    used = {**cloud_run.load_state().get("used", {}), **bot.load_used()}
    history = _all_history()
    jobs = [j for j in scheduler.get_jobs() if j.id != "daily_reschedule"]
    has_source = bool(profile["finnhub"] or profile["feeds"] or ideas)
    keys_ok = all([env.get("GROQ_API_KEY"), env.get("BUFFER_API_KEY"), env.get("BUFFER_CHANNEL_ID")]) and (
        not profile["finnhub"] or bool(env.get("FINNHUB_API_KEY")))
    return jsonify(
        groq_configured=bool(env.get("GROQ_API_KEY")),
        finnhub_configured=bool(env.get("FINNHUB_API_KEY")),
        buffer_configured=bool(env.get("BUFFER_API_KEY")),
        buffer_channel_configured=bool(env.get("BUFFER_CHANNEL_ID")),
        persona_set=bot.PERSONA_PATH.exists(),
        has_source=has_source,
        profile={k: profile[k] for k in ("topic", "feeds", "finnhub")},
        ideas_left=sum(1 for i in ideas if bot._idea_key(i) not in used),
        voice_examples_count=len(bot.load_voice_examples()),
        setup_complete=bool(keys_ok and has_source and bot.PERSONA_PATH.exists()),
        automation_enabled=automation["enabled"],
        schedule=bot.load_schedule_config(),
        next_posts=sorted(j.next_run_time.isoformat() for j in jobs if j.next_run_time),
        total_posts=len(history),
        history=list(reversed(history))[:10],
    )


@app.route("/api/verify/groq", methods=["POST"])
def verify_groq():
    key = request.json.get("api_key", "").strip()
    try:
        resp = requests.get(f"{bot.GROQ_BASE_URL}/models", headers={"Authorization": f"Bearer {key}"}, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        return jsonify(ok=False, error=_http_error_message(e))
    os.environ["GROQ_API_KEY"] = key
    set_key(ENV_PATH, "GROQ_API_KEY", key)
    return jsonify(ok=True)


@app.route("/api/verify/finnhub", methods=["POST"])
def verify_finnhub():
    key = request.json.get("api_key", "").strip()
    try:
        resp = requests.get(bot.FINNHUB_URL, params={"category": "general"},
                             headers={"X-Finnhub-Token": key}, timeout=10)
        resp.raise_for_status()
        if not isinstance(resp.json(), list):
            return jsonify(ok=False, error="Key accepted but the response looked wrong — try again.")
    except requests.exceptions.RequestException as e:
        return jsonify(ok=False, error=_http_error_message(e))
    os.environ["FINNHUB_API_KEY"] = key
    set_key(ENV_PATH, "FINNHUB_API_KEY", key)
    return jsonify(ok=True)


@app.route("/api/verify/buffer", methods=["POST"])
def verify_buffer():
    key = request.json.get("api_key", "").strip()
    previous = os.environ.get("BUFFER_API_KEY")
    os.environ["BUFFER_API_KEY"] = key
    try:
        channels = bot.get_buffer_channels()
    except Exception as e:
        os.environ["BUFFER_API_KEY"] = previous if previous is not None else ""
        if previous is None:
            os.environ.pop("BUFFER_API_KEY", None)
        return jsonify(ok=False, error=str(e))
    set_key(ENV_PATH, "BUFFER_API_KEY", key)
    return jsonify(ok=True, channels=channels)


@app.route("/api/buffer/channels")
def buffer_channels():
    try:
        return jsonify(ok=True, channels=bot.get_buffer_channels())
    except Exception as e:
        return jsonify(ok=False, error=str(e))


@app.route("/api/buffer/channel", methods=["POST"])
def set_buffer_channel():
    channel_id = request.json.get("channel_id", "").strip()
    os.environ["BUFFER_CHANNEL_ID"] = channel_id
    set_key(ENV_PATH, "BUFFER_CHANNEL_ID", channel_id)
    return jsonify(ok=True)


@app.route("/api/voice_examples", methods=["GET", "POST"])
def voice_examples():
    if request.method == "POST":
        bot.save_voice_examples(request.json.get("examples", []))
        return jsonify(ok=True)
    return jsonify(examples=bot.load_voice_examples())


@app.route("/api/growth_playbook", methods=["GET", "POST"])
def growth_playbook():
    if request.method == "POST":
        bot.GROWTH_PLAYBOOK_PATH.write_text(request.json.get("content", ""))
        return jsonify(ok=True)
    return jsonify(content=bot._load_growth_playbook())


def _feed_error(e):
    if isinstance(e, ValueError):
        return "That address isn't an RSS/Atom feed. Look for a link labelled RSS or Feed on the site."
    if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
        return f"The site answered with HTTP {e.response.status_code}."
    return "Couldn't reach that address — check the link."


@app.route("/api/feeds/verify", methods=["POST"])
def verify_feed():
    url = request.json.get("url", "").strip()
    if not url.startswith(("http://", "https://")):
        return jsonify(ok=False, error="Paste the full feed address, starting with https://")
    try:
        info = bot.inspect_feed(url)
    except Exception as e:
        return jsonify(ok=False, error=_feed_error(e))
    if not info["items"]:
        if info["total"] == 0:
            error = "This feed is valid but has no posts in it right now."
        elif info["walled"] == info["total"]:
            error = ("Every link in this feed goes through Google News, which the bot can't read. "
                     "Use the publisher's own RSS feed instead.")
        else:
            error = "None of this feed's posts are from the last 30 days."
        return jsonify(ok=False, error=error)
    readable = bool(bot._fetch_article_text(info["items"][0]["url"]))
    return jsonify(ok=True, title=info["title"], fresh=len(info["items"]), readable=readable,
                   sample=[i["headline"] for i in info["items"][:3]])


@app.route("/api/profile", methods=["GET", "POST"])
def profile():
    if request.method == "GET":
        return jsonify(bot.load_profile())
    data, current = request.json, bot.load_profile()
    feeds = [f.strip() for f in data.get("feeds", current["feeds"]) if f.strip()]
    errors = {}
    for url in feeds:
        try:
            bot.inspect_feed(url)
        except Exception as e:
            errors[url] = _feed_error(e)
    if errors:
        return jsonify(ok=False, errors=errors)
    topic = " ".join(str(data.get("topic", current["topic"])).split()) or current["topic"]
    bot.save_profile({**current, "topic": topic, "feeds": feeds, "finnhub": bool(data.get("finnhub", current["finnhub"]))})
    return jsonify(ok=True)


@app.route("/api/niche/draft", methods=["POST"])
def niche_draft():
    description = request.json.get("description", "").strip()
    if len(description) < 15:
        return jsonify(ok=False, error="Say a bit more — a sentence or two on what you post about and how you sound.")
    try:
        topic, persona_text = bot.draft_persona(description)
    except Exception as e:
        return jsonify(ok=False, error=str(e))
    return jsonify(ok=True, topic=topic, persona=persona_text)


@app.route("/api/persona", methods=["GET", "POST"])
def persona():
    if request.method == "POST":
        text = request.json.get("persona", "")
        if "<voice>" not in text or "</voice>" not in text:
            return jsonify(ok=False, error="Keep the <voice> ... </voice> block — the bot relies on it.")
        bot.save_persona(text)
        if request.json.get("topic"):
            bot.save_profile({**bot.load_profile(), "topic": " ".join(request.json["topic"].split())})
        return jsonify(ok=True)
    return jsonify(persona=bot.load_persona(), topic=bot.load_profile()["topic"])


@app.route("/api/ideas", methods=["GET", "POST"])
def ideas():
    if request.method == "POST":
        bot.save_ideas(request.json.get("ideas", []))
        return jsonify(ok=True)
    used = {**cloud_run.load_state().get("used", {}), **bot.load_used()}
    return jsonify(ideas=[{"text": i, "used": bot._idea_key(i) in used} for i in bot.load_ideas()])


@app.route("/api/schedule", methods=["GET", "POST"])
def schedule_config():
    if request.method == "POST":
        data = request.json
        bot.save_schedule_config(int(data["posts_per_day"]), int(data["start_hour"]), int(data["end_hour"]))
        if automation["enabled"]:
            scheduler.remove_all_jobs()
            _arm_automation()
        return jsonify(ok=True)
    return jsonify(bot.load_schedule_config())


@app.route("/api/preview", methods=["POST"])
def preview():
    used = {**cloud_run.load_state().get("used", {}), **bot.load_used()}
    draft, reason = bot.draft_post(used)
    if not draft:
        return jsonify(ok=False, error=f"Couldn't draft a post: {reason}.")
    return jsonify(ok=True, tweet=draft["text"], chars=len(draft["text"]), source_headline=draft["source"],
                   key=draft["key"], kind=draft["kind"])


@app.route("/api/post_now", methods=["POST"])
def post_now():
    tweet = request.json.get("tweet", "").strip()
    if not tweet:
        return jsonify(ok=False, error="No tweet text given.")
    ok = bot.post_tweet(tweet, dry_run=False)
    if ok and request.json.get("key"):
        used = bot.load_used()
        bot.mark_used(used, request.json["key"])
        bot.save_used(used)
    return jsonify(ok=ok, error=None if ok else "Buffer rejected the post — check the logs.")


@app.route("/api/automation/start", methods=["POST"])
def automation_start():
    _arm_automation()
    _save_automation_state(True)
    return jsonify(ok=True)


@app.route("/api/automation/stop", methods=["POST"])
def automation_stop():
    scheduler.remove_all_jobs()
    _save_automation_state(False)
    return jsonify(ok=True)


@app.route("/api/logs")
def logs():
    if not LOG_PATH.exists():
        return jsonify(lines=[])
    return jsonify(lines=LOG_PATH.read_text().splitlines()[-100:])


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8420, debug=False)
