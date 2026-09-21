"""Runnable self-check for the deterministic logic: python test_bot.py"""
import json
import os
import random
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest import mock

from apscheduler.schedulers.background import BackgroundScheduler

import bot
import cloud_run
from bot import _enforce_length, _is_extractable_url, _pick_daily_times, add_daily_reschedule


def test_pick_daily_times_within_window():
    now = datetime(2026, 9, 5, 6, 0, 0)
    for _ in range(200):
        times = _pick_daily_times(now)
        assert len(times) == 3
        assert times[0].hour in range(9, 12)
        assert times[1].hour in range(12, 15)
        assert times[2].hour in range(15, 18)
        assert times[0] < times[1] < times[2]


def test_enforce_length_truncates():
    result = _enforce_length("x" * 300)
    assert len(result) == 280
    assert result.endswith("...")


def test_enforce_length_passthrough():
    assert _enforce_length("short tweet") == "short tweet"


def test_is_extractable_url():
    assert _is_extractable_url("https://www.cnbc.com/2026/09/08/some-story.html")
    assert not _is_extractable_url("https://news.google.com/rss/articles/CBMi...?oc=5")
    assert not _is_extractable_url("")
    assert not _is_extractable_url(None)


def test_seeded_plan_is_reproducible():
    now = datetime(2026, 9, 5, 6, 0, 0)
    assert _pick_daily_times(now, rng=random.Random("d")) == _pick_daily_times(now, rng=random.Random("d"))


def test_midnight_job_survives_a_sleeping_machine():
    scheduler = BackgroundScheduler()
    add_daily_reschedule(scheduler)
    assert scheduler.get_job("daily_reschedule").misfire_grace_time == 18 * 3600


# ---------- cloud scheduling ----------

def _slots(*specs):
    return [{"at": f"2026-09-21T{t}:00", "status": st} for t, st in specs]


def test_next_action_picks_the_right_slot():
    at = lambda h, m: datetime(2026, 9, 21, h, m)
    assert cloud_run.next_action(_slots(("10:30", "pending")), at(9, 0)) is None      # 90 min out: too early
    assert cloud_run.next_action(_slots(("10:30", "pending")), at(9, 20)) == 0        # 70 min out: hand to Buffer
    assert cloud_run.next_action(_slots(("10:30", "pending")), at(12, 0)) == 0        # late but not stale
    stale = _slots(("10:30", "pending"), ("13:00", "pending"))
    assert cloud_run.next_action(stale, at(14, 0)) == 1 and stale[0]["status"] == "skipped"
    assert cloud_run.next_action(_slots(("10:30", "posted"), ("13:00", "pending")), at(12, 0)) == 1


DRAFT = {"text": "a tweet", "kind": "rss", "key": "http://x/1", "source": "s", "note": "n"}


def _run_ticks(*nows, commit_error=None, draft=(DRAFT, None), posts=None):
    """Run tick() at each time with the outside world faked; returns (results, posted_texts, state)."""
    posts = [] if posts is None else posts
    with tempfile.TemporaryDirectory() as d, mock.patch.multiple(
        bot,
        load_schedule_config=lambda: {"posts_per_day": 1, "start_hour": 10, "end_hour": 11},
        draft_post=lambda used, rng=random: draft,
        post_tweet=lambda text, dry_run=False, due_at=None: posts.append(text) or True,
    ), mock.patch.object(cloud_run, "STATE_PATH", Path(d) / "cloud_state.json"), mock.patch.object(
        cloud_run, "commit_state", side_effect=commit_error
    ):
        results = [cloud_run.tick(now) for now in nows]
        return results, posts, json.loads(cloud_run.STATE_PATH.read_text())


def test_tick_posts_a_slot_exactly_once_and_remembers_the_source():
    results, posts, state = _run_ticks(datetime(2026, 9, 21, 9, 50), datetime(2026, 9, 21, 10, 5))
    assert results == ["posted", "idle"] and posts == ["a tweet"]
    assert state["slots"][0]["status"] == "posted" and "http://x/1" in state["used"]


def test_tick_treats_nothing_new_as_a_quiet_skip_not_a_failure():
    results, posts, state = _run_ticks(datetime(2026, 9, 21, 9, 50), draft=(None, "nothing new"))
    assert results == ["skipped"] and posts == [] and state["slots"][0]["error"] == "nothing new"


def test_tick_records_a_real_failure():
    results, posts, state = _run_ticks(datetime(2026, 9, 21, 9, 50), draft=(None, "tweet generation failed"))
    assert results == ["failed"] and posts == [] and state["slots"][0]["status"] == "failed"


def test_tick_posts_nothing_if_the_claim_cannot_be_saved():
    posts = []
    try:
        _run_ticks(datetime(2026, 9, 21, 9, 50), commit_error=RuntimeError("push failed"), posts=posts)
    except RuntimeError:
        pass
    else:
        raise AssertionError("tick should have aborted")
    assert posts == []


def test_live_cloud_run_refuses_to_guess_the_timezone():
    keys = {k: "x" for k in ("GITHUB_ACTIONS", "GROQ_API_KEY", "FINNHUB_API_KEY", "BUFFER_API_KEY", "BUFFER_CHANNEL_ID")}
    keys["GITHUB_ACTIONS"] = "true"
    with mock.patch.dict(os.environ, keys), mock.patch.object(sys, "argv", ["cloud_run.py"]), \
            mock.patch.object(cloud_run, "tick") as tick:
        os.environ.pop("TZ", None)
        try:
            cloud_run.main()
        except SystemExit as e:
            assert "TZ" in str(e.code)
        else:
            raise AssertionError("a live Actions run without TZ must stop")
        tick.assert_not_called()


def test_the_model_can_be_overridden_without_editing_code():
    with mock.patch.dict(os.environ, {"LLM_MODEL": ""}):
        default = bot._llm_kwargs()
    assert default["model"] == bot.LLM_MODEL and default["reasoning_effort"] == "low"     # unchanged behaviour
    with mock.patch.dict(os.environ, {"LLM_MODEL": "llama-3.3-70b-versatile"}):
        other = bot._llm_kwargs()
    assert other == {"model": "llama-3.3-70b-versatile"}                                   # no param it would reject


def test_dashboard_only_answers_requests_addressed_to_this_machine():
    import webapp
    client = webapp.app.test_client()
    for ok_host in ("localhost:8420", "localhost", "127.0.0.1:8421"):
        assert client.get("/api/state", headers={"Host": ok_host}).status_code == 200
    for bad_host in ("evil.example.com", "evil.example.com:8420", "localhost.evil.com", "127.0.0.1.evil.com:8420"):
        assert client.get("/api/state", headers={"Host": bad_host}).status_code == 400
    assert client.post("/api/post_now", json={"tweet": "x"}, headers={"Host": "evil.example.com"}).status_code == 400


# ---------- niche profiles: what a post is about ----------

def _rss(*items):
    """items: (title, link, days_old)"""
    body = "".join(
        f"<item><title>{t}</title><link>{link}</link><description>&lt;p&gt;{t} summary&lt;/p&gt;</description>"
        f"<pubDate>{format_datetime(datetime.now(timezone.utc) - timedelta(days=d))}</pubDate></item>"
        for t, link, d in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Test Feed</title>{body}</channel></rss>'.encode()


def _draft(profile, used=None, ideas=(), feed_xml=None, feed_error=None, rng=random):
    """Run draft_post with the profile/ideas/feed/LLM faked; returns (draft, reason, what the LLM was given)."""
    seen = {}

    def fake_generate(news_items=None, idea=None):
        seen.update(news_items=news_items, idea=idea)
        return "a tweet"

    resp = mock.Mock(content=feed_xml, raise_for_status=lambda: None)
    get = mock.Mock(side_effect=feed_error) if feed_error else mock.Mock(return_value=resp)
    with mock.patch.multiple(bot, load_profile=lambda: {**bot.DEFAULT_PROFILE, **profile}, load_ideas=lambda: list(ideas),
                             generate_tweet=fake_generate, _fetch_article_text=lambda url: "Article text"), \
            mock.patch.object(bot.requests, "get", get):
        draft, reason = bot.draft_post(dict(used or {}), rng)
    return draft, reason, seen


def test_rss_post_uses_the_newest_unseen_story_and_its_article_text():
    xml = _rss(("Old story", "http://a/old", 5), ("New story", "http://a/new", 1))
    draft, reason, seen = _draft({"feeds": ["http://feed"]}, feed_xml=xml)
    assert draft["kind"] == "rss" and draft["key"] == "http://a/new"
    assert seen["news_items"][0]["headline"] == "New story" and seen["news_items"][0]["body"] == "Article text"


def test_rss_never_repeats_a_story_and_goes_quiet_when_all_are_used():
    xml = _rss(("Old story", "http://a/old", 5), ("New story", "http://a/new", 1))
    draft, _, _ = _draft({"feeds": ["http://feed"]}, used={"http://a/new": "t"}, feed_xml=xml)
    assert draft["key"] == "http://a/old"
    draft, reason, _ = _draft({"feeds": ["http://feed"]}, used={"http://a/new": "t", "http://a/old": "t"}, feed_xml=xml)
    assert draft is None and reason == "nothing new"


def test_rss_ignores_google_news_redirects_and_stale_items():
    xml = _rss(("Walled", "https://news.google.com/rss/articles/abc", 1), ("Ancient", "http://a/ancient", 90))
    draft, reason, _ = _draft({"feeds": ["http://feed"]}, feed_xml=xml)
    assert draft is None and reason == "nothing new"


def test_unreachable_feeds_are_a_failure_not_a_quiet_skip():
    draft, reason, _ = _draft({"feeds": ["http://feed"]}, feed_error=OSError("down"))
    assert draft is None and reason == "couldn't reach any of your feeds"


def test_a_non_feed_url_is_rejected():
    try:
        with mock.patch.object(bot.requests, "get", return_value=mock.Mock(content=b"<html><body>hi</body></html>",
                                                                        raise_for_status=lambda: None)):
            bot.read_feed("http://not-a-feed")
    except ValueError:
        return
    raise AssertionError("an HTML page should not be accepted as a feed")


def test_ideas_are_used_in_order_once_each():
    draft, _, seen = _draft({}, ideas=["first idea", "second idea"])
    assert draft["kind"] == "idea" and seen["idea"] == "first idea"
    draft, _, seen = _draft({}, used={bot._idea_key("first idea"): "t"}, ideas=["first idea", "second idea"])
    assert seen["idea"] == "second idea"
    draft, reason, _ = _draft({}, used={bot._idea_key(i): "t" for i in ("first idea", "second idea")},
                              ideas=["first idea", "second idea"])
    assert draft is None and reason == "nothing new"


def test_mixed_sources_fall_through_to_whatever_has_material():
    xml = _rss(("Only story", "http://a/only", 1))
    used = {"http://a/only": "t"}                       # the feed is exhausted...
    for seed in range(20):                              # ...so it must be the idea, whatever order sources are tried in
        draft, _, _ = _draft({"feeds": ["http://feed"]}, used=used, ideas=["my idea"], feed_xml=xml, rng=random.Random(seed))
        assert draft["kind"] == "idea"


def test_system_prompt_swaps_the_niche_layer_but_keeps_the_core_rules():
    profile = {**bot.DEFAULT_PROFILE, "topic": "woodworking", "char_limit": 500}
    with mock.patch.object(bot, "load_persona", return_value="PERSONA"):
        news, idea = bot.build_system_prompt(profile, "news"), bot.build_system_prompt(profile, "idea")
    assert news.startswith("PERSONA") and "today's real woodworking stories" in news and "Under 500 characters" in news
    assert "personal note" in idea and "handful of today's real" not in idea
    for prompt in (news, idea):
        assert "<banned_phrases>" in prompt and "<humor_guardrails>" in prompt and "financial" not in prompt


def test_inspect_feed_explains_why_a_feed_is_unusable():
    def inspect(xml):
        with mock.patch.object(bot.requests, "get", return_value=mock.Mock(content=xml, raise_for_status=lambda: None)):
            return bot.inspect_feed("http://feed")
    walled = inspect(_rss(("a", "https://news.google.com/rss/articles/1", 1), ("b", "https://news.google.com/rss/articles/2", 2)))
    assert (walled["total"], walled["walled"], walled["items"]) == (2, 2, [])
    assert inspect(_rss())["total"] == 0                                  # valid but empty
    old = inspect(_rss(("Ancient", "http://a/x", 90)))
    assert old["total"] == 1 and old["items"] == []                       # nothing recent
    ok = inspect(_rss(("Fresh", "http://a/y", 1)))
    assert ok["title"] == "Test Feed" and [i["headline"] for i in ok["items"]] == ["Fresh"]
    assert ok["items"][0]["summary"] == "Fresh summary"                   # html stripped from the feed's own summary


def test_persona_draft_parsing():
    good = "TOPIC: Woodworking\n---\nYou are ghostwriting tweets for a real person who...\n\n<voice>\n- casual\n</voice>"
    topic, persona = bot.parse_persona_draft(good)
    assert topic == "woodworking" and persona.startswith("You are ghostwriting") and persona.endswith("</voice>")
    for bad in (None, "", "no delimiter here", "TOPIC: x\n---\nno voice block", "TOPIC:\n---\n<voice>a</voice>"):
        try:
            bot.parse_persona_draft(bad)
        except ValueError:
            continue
        raise AssertionError(f"should have rejected {bad!r}")


def test_used_list_is_pruned_to_the_newest_entries():
    used = {f"k{i}": f"2026-01-01T00:00:{i:02d}" for i in range(10)}
    assert list(bot.prune_used(used, keep=3)) == ["k7", "k8", "k9"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"All {len(tests)} checks passed.")
