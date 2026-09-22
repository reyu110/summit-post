# Summit — an automated posting bot you run yourself, for free

Turns what you care about into posts in your own voice and publishes them to X on a randomised,
human-looking schedule. You set it up and manage it from a dashboard in your browser.

It runs on **your** computer with **your** free accounts. There is no server, no sign-up with this
project, and nobody hosting anything for you. Optionally it can run from GitHub's servers instead, so
your computer can be off.

## What it does

- **Reads your sources.** Add RSS feeds (blogs, news sites, subreddits) and the bot reads the full
  articles. Or keep an **idea bank** of your own notes and it turns them into posts, using only what
  you wrote. Or both: each post picks one at random. Finance accounts can also use Finnhub market news.
- **Sounds like you.** An AI-drafted, editable *persona* for your niche, plus your own past posts as
  voice samples. You pick them straight from your own X archive in the dashboard (see below).
- **Never repeats itself.** Every story and idea is used once.
- **Posts at random times** inside a window you choose (default: 3 a day, 9am–6pm), not on the hour.
- **You stay in control.** Automation is off until you switch it on, and you can draft, edit and publish
  any post by hand from the dashboard.
  <img width="1536" height="1024" alt="image" src="https://github.com/user-attachments/assets/62de1e0c-eed9-45d0-b18a-b7b269aba323" />


## Quick start (about 5 minutes, no git needed)

1. **Install Python 3.10 or newer** from [python.org](https://www.python.org/downloads/). On Windows,
   tick *Add python.exe to PATH* in the installer.
2. **Get the code.** On this page click **Code → Download ZIP** and unzip it.
3. **Open a terminal in that folder and run:**
   ```bash
   python run.py
   ```
   On macOS/Linux use `python3 run.py`; on Windows, if `python` isn't found, use `py run.py`.
   The first run sets up a private Python environment by itself (about a minute), then opens the
   dashboard in your browser.
4. **Follow the setup wizard.** It checks every key live before letting you continue, drafts your persona
   from a description of your niche, and checks your feeds. You'll need two free accounts:
   - [Groq](https://console.groq.com/keys): an API key. This writes the posts.
   - [Buffer](https://buffer.com): sign up, connect your X account as a channel, then create an API key
     at publish.buffer.com/settings/api. This publishes the posts. (X's own API is no longer free, which
     is why posting goes through Buffer.)
5. **Switch automation on** in the dashboard.

In this mode posts go out while `run.py` is running **and your computer is awake**. Press Ctrl+C to stop;
run the same command later to start again. Everything you set up is kept in this folder.

## Run it with your computer off (optional, free)

Instead of downloading the ZIP, click **Use this template → Create a new repository** (make it
**private**) and clone it. You'll also need [git](https://git-scm.com) and the
[GitHub CLI](https://cli.github.com) (`gh auth login`). Then, after the wizard, the dashboard's **Cloud**
button shows these steps with your timezone filled in:

1. Push your setup, then upload your keys as secrets:
   ```bash
   git add -A
   git commit -m "my setup"
   git push
   gh secret set -f .env
   ```
   (No `gh`? Add the same keys by hand under **Settings → Secrets and variables → Actions**.)
2. **Test it.** On GitHub open **Actions → post → Run workflow** and leave *dry run* ticked. It writes one
   post and prints it without publishing anything.
3. **Go live.** Set your timezone; this switches the hourly job on:
   ```bash
   gh variable set TZ --body America/Toronto     # your timezone
   ```

Keep the dashboard's automation switch **off** while the cloud job is running, or you'll post twice.

Once an hour a GitHub Actions job looks at today's random schedule and hands the next post to Buffer with
its exact publish time. It saves its state back to your repo *before* posting, so a failed save can never
cause a duplicate. If something breaks, the run turns red and GitHub emails you. Changes you make in the
dashboard reach the cloud when you `git push`.

## Making it sound like you

Nothing about anyone else's voice ships with this project. The bot starts generic, and the wizard's
**Voice** step is where it learns yours. In the dashboard, either:

- **Pick from your X archive.** On X go to **Settings → Your account → Download an archive of your data**
  (it can take a while to arrive), unzip it, and choose `data/tweets.js`. The dashboard shows your original
  posts, skipping retweets, replies and link-only posts, and you tick the ones that sound most like you.
  The file is read on your computer only, and nothing else in the archive is opened.
- **Paste them in.** No posts yet? Write three or four short ones the way you'd naturally say them.

Around five samples works well (up to eight). You can change them any time under **Voice samples**; the
dashboard nudges you until you've added at least three.

## Managing it from the dashboard

Automation on/off and a live countdown · draft, edit and publish a post by hand · **Sources** (feeds and
ideas) · **Persona** · **Voice samples** · **Growth playbook** · posting schedule · activity log · post
history · **Health check** · **Cloud** instructions · **Setup** (re-run the wizard to change a key or your
Buffer channel).

## Privacy: what leaves your machine

This project has no server and collects nothing. Your keys stay in a file called `.env` in this folder
(git-ignored, so it's never committed) and, if you use the cloud option, in your own repo's encrypted
secrets. The dashboard only answers requests addressed to your own computer.

The only network calls are the ones you'd expect: **Groq** (your persona, voice samples and the story text,
to write a post), **Buffer** (the finished post), the **feeds and articles** you chose, **GitHub** (only if
you use the cloud option), and **Google Fonts** (the dashboard's typefaces).

## Costs and limits

- Free tiers only, at the time of writing: Groq's free tier, Buffer's free plan (3 channels), and, for the
  cloud option, GitHub's 2,000 free Actions minutes a month on private repos (this uses about 720).
- **Buffer's free plan is the fragile part.** X now charges for its API, and Buffer's free plan is what
  makes this free. If Buffer changes that, posting is the piece that would need to change.
- Feeds must be the publisher's own RSS feed. Google News links can't be read (the wizard tells you when a
  feed is one of these).
- Check X's rules on automated accounts and AI-generated content before you turn posting on. You're
  responsible for what your account publishes.

## Updating

**ZIP users:** download the new ZIP and copy your `.env`, `persona.md`, `profile.json`, `voice_examples.txt`,
`ideas.txt` and `schedule_config.json` into it.

**Template users:** the first time,
```bash
git remote add upstream https://github.com/reyu110/summit-post.git
git fetch upstream
git merge upstream/main --allow-unrelated-histories -X theirs -m "Update from template"
```
(`-X theirs` takes the new code; your own data files aren't in the template, so they're untouched.) After that,
just `git fetch upstream` and `git merge upstream/main`.

## Troubleshooting

- **`python` isn't found.** Reinstall Python and tick *Add python.exe to PATH*, or try `py run.py` (Windows)
  or `python3 run.py` (macOS/Linux).
- **"Couldn't create the environment" on Linux.** Install the missing piece: `sudo apt install python3-venv`.
- **The dashboard is on a different port than 8420.** Another program was using 8420; `run.py` picked the
  next free one and prints the address.
- **Groq stops working with a "model" error.** Groq occasionally retires models. Set `LLM_MODEL=` to a
  current one in `.env` (or as a repository variable for the cloud job).
- **The cloud dry run fails with `403 Access denied` from Groq.** Some providers block cloud IP ranges. Try
  again later, or open an issue with the log.
- **The workflow run says "skipped".** The `TZ` variable isn't set yet. It's the on switch, so set it once
  your dry run works.
- **A run went red.** Open it under Actions; the last lines say why. "Nothing new" is *not* an error: a quiet
  feed just skips that slot.

## Files you'll edit (all from the dashboard, or by hand)

| File | What it is |
|---|---|
| `profile.json` | Topic, feeds, and whether Finnhub is on |
| `persona.md` | Who the bot writes as |
| `voice_examples.txt` | Your own past posts, one per line |
| `ideas.txt` | Your idea bank, one per line |
| `growth_playbook.md` | Research-backed writing rules, re-read before every post |
| `schedule_config.json` | Posts per day and the time window |

`python run.py --test` runs the self-checks; `python run.py --check` proves the dashboard starts.

## License

[The Prosperity Public License 3.0.0](LICENSE). In plain English: free for personal, hobby,
noncommercial and nonprofit/educational/government use. Commercial use gets a 30-day free trial,
after which a commercial user needs to work out a separate license with the contributor. Provided
as is, with no warranty and no hosted service.
