# Weekly AI Digest – Setup Guide

This guide walks you through deploying the weekly digest system on GitHub Actions from scratch.
The system runs every Monday at 7 AM UTC, generates two digests (CS Leadership & CTO/Engineering),
and emails each one with a short summary, a full HTML attachment, and a link to a podcast audio file.

---

## What gets delivered each Monday

| Item | Format | How it's delivered |
|------|--------|--------------------|
| Short digest (top 5 stories) | HTML email body | In the email itself |
| Full structured digest | `.html` file attachment | Attached to the email — open in browser |
| Podcast / audio version | MP3 (~10 min) | Link in the email → GitHub Releases |

You receive **two separate emails**: one for CS Leadership, one for Engineering/CTO.

---

## Prerequisites

- A **GitHub account** with a repository for this project
- An **OpenAI API key** (ChatGPT Plus subscription is separate — you need an API key from platform.openai.com)
- A **Google Workspace / Gmail account** to send the emails from
- 2-Step Verification enabled on that Google account

---

## Step 1 — Push this project to GitHub

If you haven't already, create a GitHub repo and push this codebase:

```bash
git init
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
git add .
git commit -m "Initial commit: weekly AI digest system"
git push -u origin main
```

---

## Step 2 — Enable GitHub Actions write permissions

The workflow needs permission to create GitHub Releases (for audio hosting).

1. Go to your repo → **Settings** → **Actions** → **General**
2. Scroll to **Workflow permissions**
3. Select **Read and write permissions**
4. Click **Save**

---

## Step 3 — Create a Gmail App Password

> App Passwords let GitHub Actions send email on your behalf without exposing your real password.
> You must have **2-Step Verification** enabled first.

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Under "How you sign in to Google", click **2-Step Verification** (enable it if needed)
3. Scroll to the bottom of the 2-Step Verification page and click **App passwords**
4. Under "Select app" choose **Mail**, under "Select device" choose **Other** → type `GitHub Digest`
5. Click **Generate**
6. Copy the 16-character password shown (you won't see it again) — this is your `GMAIL_APP_PASSWORD`

> **Note:** If you don't see "App passwords", your account may use Advanced Protection or a managed
> Google Workspace policy. In that case, ask your Google Workspace admin to allow App Passwords, or
> use the [Gmail API with OAuth](https://developers.google.com/gmail/api) instead.

---

## Step 4 — Get your OpenAI API key

1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Click **Create new secret key**, give it a name like `GitHub Digest`
3. Copy the key immediately (it's only shown once)

> **Cost estimate:** Each weekly run costs approximately **$3–6** in OpenAI API credits:
> - 10 web search queries (~$0.50)
> - 4 GPT-4o generation calls (~$0.80)
> - 2 TTS-HD audio generations, ~8,000 chars each (~$0.48)
> Total: well under $10/week with a standard API plan.

---

## Step 5 — Add GitHub Secrets

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.

Add all four of the following:

| Secret name | Value |
|-------------|-------|
| `OPENAI_API_KEY` | Your OpenAI API key from Step 4 |
| `GMAIL_USER` | Your full Gmail address, e.g. `you@gmail.com` |
| `GMAIL_APP_PASSWORD` | The 16-character App Password from Step 3 |
| `RECIPIENT_EMAIL` | The email address to send digests to (can be the same as `GMAIL_USER`) |

---

## Step 6 — (Optional) Enable GitHub Pages for a nicer audio URL

Audio files are hosted as GitHub Release assets by default, which gives you URLs like:
`https://github.com/you/repo/releases/download/digest-2026-03-09/digest-cs-2026-03-09.mp3`

These work in any browser and audio player. No extra setup required.

If you later want a custom domain or a cleaner podcast feed, GitHub Pages is a good next step.

---

## Step 7 — Trigger a test run

Before waiting until Monday, trigger the workflow manually:

1. Go to your repo → **Actions** → **Weekly AI Digest**
2. Click **Run workflow** → select `both` (or `cs` / `cto` to test one at a time)
3. Click the green **Run workflow** button
4. Watch the logs in real time — the run takes 5–10 minutes
5. Check your inbox

If the run fails, click the failed step in the logs for details. Common issues:

| Error | Fix |
|-------|-----|
| `AuthenticationError: OPENAI_API_KEY` | Check the secret name and that the key has API credits |
| `SMTPAuthenticationError` | Check `GMAIL_USER` / `GMAIL_APP_PASSWORD`; ensure App Password is correct |
| `403 on GitHub Release` | Check that Actions write permissions are enabled (Step 2) |
| `openai.APIError: web_search_preview` | Your OpenAI plan may not include web search — see note below |

> **Web search note:** The script uses OpenAI's `web_search_preview` tool via the Responses API,
> which requires a paid OpenAI API plan (not just a ChatGPT subscription). If web search is not
> available on your plan, the research step will fall back gracefully and GPT-4o will use its
> training knowledge. The digests will still be generated but may not reflect the very latest news.

---

## Schedule

The workflow runs automatically every **Monday at 7:00 AM UTC**.

| Your timezone | UTC offset | Arrives at (approx.) |
|---------------|------------|----------------------|
| GMT (London) | UTC+0 | 7:00 AM |
| CET (Central Europe) | UTC+1 | 8:00 AM |
| EST (US Eastern) | UTC−5 | 2:00 AM Mon → adjust cron |
| PST (US Pacific) | UTC−8 | 11:00 PM Sun → adjust cron |

To change the schedule, edit the `cron` line in `.github/workflows/weekly-digest.yml`:

```yaml
- cron: "0 7 * * 1"   # 7:00 AM UTC every Monday
```

Use [crontab.guru](https://crontab.guru) to calculate your preferred time.

---

## Customising the digests

**To change the content focus, tone, or structure**, edit the `CS_SYSTEM_PROMPT` and `CTO_SYSTEM_PROMPT`
constants near the top of `scripts/generate_digest.py`.

**To change which topics are researched**, edit `CS_SEARCH_QUERIES` and `CTO_SEARCH_QUERIES`.

**To change the TTS voice**, change `voice="onyx"` in `generate_audio()`.
Available voices: `alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`.

**To change the sending time**, update the `cron` line in the workflow file.

**To send only one digest**, set the `digest_type` input when triggering manually, or update
the default in the workflow file.

---

## File structure

```
.github/
  workflows/
    weekly-digest.yml       ← GitHub Actions schedule & job definition
scripts/
  generate_digest.py        ← Main script: research → generate → audio → email
  requirements.txt          ← Python dependencies
documentation/
  Weekly AI digests.md      ← Original digest specification
  SETUP.md                  ← This file
```
