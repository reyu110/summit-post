#!/usr/bin/env python3
"""One tick of the cloud scheduler; .github/workflows/post.yml runs it hourly so the computer can stay off.
Each tick hands at most one upcoming slot to Buffer, which publishes it at the slot's exact planned time.
`--dry-run` just generates a tweet and prints it."""
import argparse
import json
import logging
import os
import random
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

import bot

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "cloud_state.json"
LOOKAHEAD = timedelta(minutes=75)  # a slot is handed to Buffer this far ahead of its planned time
MAX_LATE = timedelta(hours=3)      # a slot this overdue is skipped rather than posted at some odd hour


def load_state():
    return json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}


def todays_slots(state, now):
    """The saved plan if it's today's, else one seeded by the date so every run agrees on it."""
    today = now.date().isoformat()
    if state.get("date") == today:
        return state["slots"]
    c = bot.load_schedule_config()
    rng = random.Random(f"{today}|{c['posts_per_day']}|{c['start_hour']}|{c['end_hour']}")
    times = bot._pick_daily_times(now, c["posts_per_day"], c["start_hour"], c["end_hour"], rng)
    return [{"at": t.isoformat(timespec="seconds"), "status": "pending"} for t in times]


def next_action(slots, now):
    """Mark hopelessly late slots skipped; return the index of the first pending slot due within LOOKAHEAD."""
    for i, slot in enumerate(slots):
        if slot["status"] != "pending":
            continue
        at = datetime.fromisoformat(slot["at"])
        if now - at > MAX_LATE:
            slot["status"] = "skipped"
        elif at - now <= LOOKAHEAD:
            return i
        else:
            return None  # slots are chronological, so nothing later is due yet either
    return None


def commit_state(message):
    """Save state into the repo (GitHub Actions only). Raises on failure — and tick() saves BEFORE posting,
    so a failed save means nothing gets posted: at most once, never a duplicate."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return

    def git(*args, check=True):
        return subprocess.run(["git", *args], cwd=ROOT, check=check)

    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    git("add", "-A")
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        return
    git("commit", "-m", message)
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    try:
        git("push", "origin", f"HEAD:{branch}")
    except subprocess.CalledProcessError:
        git("pull", "--rebase", "origin", branch)
        git("push", "origin", f"HEAD:{branch}")


def persist(slots, history, used, now, message):
    new = json.dumps({"date": now.date().isoformat(), "slots": slots, "history": history, "used": used}, indent=2) + "\n"
    if STATE_PATH.exists() and STATE_PATH.read_text() == new:
        return
    STATE_PATH.write_text(new)
    commit_state(message)


def tick(now):
    """Returns 'idle', 'posted', 'skipped' (nothing new to post about) or 'failed'."""
    state = load_state()
    slots, history, used = todays_slots(state, now), state.get("history", []), state.get("used", {})
    i = next_action(slots, now)
    if i is None:
        persist(slots, history, used, now, f"cloud: {now.date()} plan")
        return "idle"

    slot = slots[i]
    slot["status"] = "claimed"
    persist(slots, history, used, now, f"cloud: claim {slot['at']}")

    draft, reason = bot.draft_post(used)
    if not draft:
        # a slow niche with nothing new is normal, not an error; anything else is a real failure
        slot.update(status="skipped" if reason == "nothing new" else "failed", error=reason)
    else:
        due = max(datetime.fromisoformat(slot["at"]), now + timedelta(seconds=30))
        ok = bot.post_tweet(draft["text"], due_at=due.astimezone())
        slot.update(status="posted" if ok else "failed", text=draft["text"])
        if ok:
            history.append({"timestamp": due.isoformat(timespec="seconds"), "text": draft["text"]})
            del history[:-100]  # the dashboard only shows recent posts
            if draft["key"]:
                bot.mark_used(used, draft["key"])
                used = bot.prune_used(used)
        else:
            slot["error"] = "Buffer rejected the post"
    persist(slots, history, used, now, f"cloud: {slot['status']} {slot['at']}")
    return slot["status"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Generate a tweet and print it; post and save nothing")
    args = parser.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    needs = ["GROQ_API_KEY"] + (["FINNHUB_API_KEY"] if bot.load_profile()["finnhub"] else [])
    if args.dry_run:
        bot._require_env(*needs)
        draft, reason = bot.draft_post({})
        if not draft:
            sys.exit(f"Dry run failed: {reason} (see warnings above).")
        print(f"[{draft['kind']}] {draft['source']}\n{draft['note']}")
        bot.post_tweet(draft["text"], dry_run=True)
        return

    bot._require_env(*needs, "BUFFER_API_KEY", "BUFFER_CHANNEL_ID")
    if os.environ.get("GITHUB_ACTIONS") == "true" and not os.environ.get("TZ"):
        sys.exit("The TZ repo variable isn't set, so your posting window would be read as UTC. "
                 "Run: gh variable set TZ --body <your timezone, e.g. America/Toronto>")
    now = datetime.now()
    logging.info("tick at %s (TZ=%s)", now.isoformat(timespec="seconds"), os.environ.get("TZ", "system default"))
    if tick(now) == "failed":
        sys.exit(1)  # a red run makes GitHub email you


if __name__ == "__main__":
    main()
