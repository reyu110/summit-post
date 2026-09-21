# Summit — an automated posting bot you run for free

Turns what you care about into posts in your own voice and publishes them to X on a randomised,
human-looking schedule. It can run from GitHub's servers, so your computer can be off.

Everything runs on free tiers: **Groq** writes the posts, **Buffer** publishes them, **GitHub Actions**
runs it. Nothing passes through anyone else's server, and your keys stay in your own accounts.

## What it does

- **Reads your sources.** Add RSS feeds (blogs, news sites, subreddits) and the bot reads the full
  articles. Or keep an **idea bank** of your own notes and it turns them into posts, using only what
  you wrote. Or both: each post picks one at random. Finance accounts can also use Finnhub market news.
- **Sounds like you.** An AI-drafted, editable *persona* for your niche, plus your own past posts as
  voice samples.
- **Never repeats itself.** Every story and idea is used once.
- **Posts at random times** inside a window you choose (default: 3 a day, 9am–6pm), not on the hour.
- **You stay in control.** Automation is off until you switch it on, and the dashboard lets you draft,
  edit and publish any post by hand.

## Setup (about 15 minutes)

You need: Python 3.11+, git, a GitHub account, and the [GitHub CLI](https://cli.github.com) (`gh`).

1. **Copy this repo.** Click **Use this template → Create a new repository** and make it **private**.
   Then clone it.
2. **Create three free accounts.**
   - [Groq](https://console.groq.com/keys): an API key.
   - [Buffer](https://buffer.com): sign up, connect your X account as a channel, then create an API key
     at publish.buffer.com/settings/api. (X's own API is no longer free, which is why posting goes
     through Buffer.)
3. **Run the setup wizard.**
   ```bash
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   python webapp.py
   ```
   Open http://localhost:8420. The wizard checks each key live before letting you continue, drafts
   your persona from a description of your niche, and checks your feeds.
4. **Put it in the cloud.** The dashboard's **Cloud** button shows these commands:
   ```bash
   git add -A && git commit -m "my setup" && git push
   gh secret set -f .env
   ```
5. **Test it.** On GitHub: **Actions → post → Run workflow** (leave *dry run* ticked). It writes one post
   and prints it without publishing anything.
6. **Go live.** Set your timezone; this switches the hourly job on:
   ```bash
   gh variable set TZ --body America/Toronto     # your timezone
   ```

If you use the cloud job, keep the dashboard's automation switch **off**, or you'll post twice.

## How the cloud job works

Once an hour a GitHub Actions job wakes up, looks at today's random schedule, and hands the next post
to Buffer with its exact publish time. State is saved back to the repo *before* posting, so a failed save
can never cause a duplicate post. If something breaks, the run turns red and GitHub emails you.
Changes you make locally (voice samples, persona, sources, schedule) reach the cloud when you `git push`.

## Costs and limits

- Free tiers only, at the time of writing: Groq's free tier, Buffer's free plan (3 channels), and
  GitHub's 2,000 free Actions minutes a month on private repos (this uses about 720).
- **Buffer's free plan is the fragile part.** X now charges for its API, and Buffer's free plan is what
  makes this free. If Buffer changes that, posting is the piece that would need to change.
- Feeds must be the publisher's own RSS feed. Google News links can't be read (the setup wizard tells
  you when a feed is one of these).
- Check X's rules on automated accounts and AI-generated content before you turn posting on. You're
  responsible for what your account publishes.

## Troubleshooting

- **The cloud dry run fails with `403 Access denied` from Groq.** Some providers block cloud IP ranges.
  Try again later, or open an issue with the log.
- **The workflow run says "skipped".** The `TZ` variable isn't set yet. It's the on switch, so set it
  once your dry run works: `gh variable set TZ --body <your timezone>`.
- **A run went red.** Open it under Actions; the last lines say why. "Nothing new" is *not* an error:
  a quiet feed just skips that slot.

## Files you'll edit (all from the dashboard, or by hand)

| File | What it is |
|---|---|
| `profile.json` | Topic, feeds, and whether Finnhub is on |
| `persona.md` | Who the bot writes as |
| `voice_examples.txt` | Your own past posts, one per line |
| `ideas.txt` | Your idea bank, one per line |
| `growth_playbook.md` | Research-backed writing rules, re-read before every post |
| `schedule_config.json` | Posts per day and the time window |

`python test_bot.py` runs the self-checks.
