#!/usr/bin/env python3
"""
Weekly AI Digest Generator

Runs in GitHub Actions every Monday morning.
Produces two digests (CS Leadership & CTO/Engineering), each with:
  - A short HTML email summary with top stories
  - A full structured HTML document attachment (links preserved)
  - An MP3 podcast audio file hosted on GitHub Releases

News research uses Tavily Search API (real-time web search, last 7 days).
Content generation, podcast scripting, and TTS use OpenAI.
"""

import os
import json
import time
import smtplib
import requests
import markdown2
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from openai import OpenAI

openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
TAVILY_API_KEY = os.environ["TAVILY_API_KEY"]

NOW = datetime.utcnow()
WEEK_DATE = NOW.strftime("%Y-%m-%d")
WEEK_DISPLAY = NOW.strftime("%B %d, %Y")

# ── Model configuration ────────────────────────────────────────────────────────
# Digest generation is the highest-value step — use the best available model.
# Summary extraction and podcast scripting are formulaic — mini is sufficient.
# Change these constants to update models without touching the rest of the code.

MODEL_DIGEST = "gpt-5.2"       # Full structured digest (synthesis + analysis)
MODEL_AUXILIARY = "gpt-5-mini" # JSON extraction, podcast script (structured/formulaic)
MODEL_TTS = "tts-1-hd"         # OpenAI TTS; "tts-1" is faster/cheaper if quality is fine
TTS_VOICE = "onyx"             # Options: alloy, echo, fable, onyx, nova, shimmer

# ── Search queries ─────────────────────────────────────────────────────────────

CS_SEARCH_QUERIES = [
    f"AI customer service failures incidents SaaS companies {NOW.year}",
    f"AI support automation rollback negative customer experience outcomes {NOW.year}",
    f"Intercom Fin Zendesk AI Salesforce Einstein HubSpot Breeze AI new features {NOW.year}",
    f"AI hallucination customer-facing consequences enterprise {NOW.year}",
    f"AI customer success retention churn risk real world case study {NOW.year}",
]

CTO_SEARCH_QUERIES = [
    f"OpenAI Anthropic new model API release update {NOW.year}",
    f"Cursor AI coding tool Devin Replit AI engineering update {NOW.year}",
    f"AI generated code security incident production failure engineering {NOW.year}",
    f"LLM evaluation testing reliability production engineering patterns {NOW.year}",
    f"AI agent framework architecture patterns SaaS engineering {NOW.year}",
]

# ── System prompts ─────────────────────────────────────────────────────────────

CS_SYSTEM_PROMPT = f"""You are an expert analyst creating a weekly AI news digest for a Customer Success Director at a large SaaS company.

PRIORITY ORDER: Customer-facing risk first > SaaS case studies > vendor updates.

For EACH news item, include ALL of the following (use Markdown headers and bullets):
1. **Headline-style title + company/vendor** (H3)
2. **What happened** – 1–2 concise bullets
3. **Customer-Facing Risk Assessment**
   - What could go wrong
   - Severity: High / Med / Low
   - Likelihood: High / Med / Low
4. **Mitigations / Controls (Playbook Style)**
   - Guardrails
   - Human-in-the-loop mechanisms
   - Monitoring signals
   - Escalation triggers
5. **What we can learn** – practical takeaway
6. **Why it matters for Customer Success** – note impact on CX / Cost-to-serve / Retention / Expansion / Compliance
7. **Where it applies** – Support / Onboarding / Renewals / QBRs / VoC / Escalation
8. **Who is affected** – Customers / CSMs / Support / Product / Engineering
9. **Impact Score** – High / Med / Low
10. **Confidence Level** – High / Med / Low

Order items by potential negative customer impact (highest first).

REQUIRED ADDITIONAL SECTIONS:
### Signals to Watch
3–5 leading indicators that customer-facing AI risk may be increasing.

### What To Do Next Week
3–5 concrete, actionable steps.

### Vendor Capability Snapshot
Short summary of notable CS-relevant vendor capabilities released this week, with hyperlinks.

TONE: Analytical, risk-aware, operationally grounded, action-oriented. No hype. No vendor marketing language.
FORMAT: Well-structured Markdown. Embed hyperlinks to sources inline using [text](url) format. Do not invent URLs — only use URLs from the research provided.
"""

CTO_SYSTEM_PROMPT = f"""You are an expert analyst creating a weekly AI news digest for a SaaS CTO and hands-on software engineer.

PRIORITY ORDER: Vendor updates > real engineering learnings > proven usage trends.

For EACH news item, include ALL of the following (use Markdown headers and bullets):
1. **Headline-style title + vendor/project** (H3)
2. **What changed** – 1–2 concise bullets
3. **Engineering Implications**
   - Architecture impact
   - Cost implications
   - Latency / performance
   - Reliability considerations
   - Security / compliance impact
4. **Proven Usage Trend / Pattern** – how engineering teams are using it in practice
5. **Risk / Quality Note** – failure modes, gotchas, where it breaks
6. **Quick Experiment Idea** – a small, practical test for a SaaS engineering org
7. **Impact Score** – High / Med / Low
8. **Confidence Level** – High / Med / Low

Order items by potential impact on engineering work (highest first).

REQUIRED ADDITIONAL SECTIONS:
### Recommended Experiments
3–5 concrete experiments that can be implemented immediately.

### Quality Checklist for Agent-Built Features
Short, actionable checklist: evaluation criteria, automated regression tests, structured output validation, monitoring/alerting, human override paths, logging and traceability.

### Tooling Watchlist
Brief list of notable releases, updates, or tools worth tracking this week, with hyperlinks.

TONE: Engineering-first, reality-based, skeptical of hype, focused on tradeoffs. No vendor marketing language.
FORMAT: Well-structured Markdown. Embed hyperlinks to sources inline using [text](url) format. Do not invent URLs — only use URLs from the research provided.
"""

# ── Email HTML template ────────────────────────────────────────────────────────

EMAIL_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
         background: #f0f2f5; padding: 24px 16px; }}
  .wrapper {{ max-width: 660px; margin: 0 auto; }}
  .header {{ background: {header_bg}; color: #fff; padding: 28px 32px; border-radius: 10px 10px 0 0; }}
  .header-eyebrow {{ font-size: 11px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase;
                     opacity: 0.7; margin-bottom: 8px; }}
  .header h1 {{ font-size: 20px; font-weight: 700; line-height: 1.3; }}
  .header-meta {{ font-size: 13px; opacity: 0.75; margin-top: 6px; }}
  .body {{ background: #ffffff; padding: 28px 32px; }}
  .intro {{ font-size: 14px; color: #4a5568; line-height: 1.6; margin-bottom: 24px; }}
  .section-label {{ font-size: 11px; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase;
                    color: {accent}; margin-bottom: 14px; }}
  .story-card {{ border: 1px solid #e8ecf0; border-left: 4px solid {accent}; border-radius: 0 8px 8px 0;
                 padding: 14px 18px; margin-bottom: 12px; }}
  .story-card h3 {{ font-size: 14px; font-weight: 700; color: #1a202c; margin-bottom: 6px; line-height: 1.4; }}
  .story-card p {{ font-size: 13px; color: #4a5568; line-height: 1.55; }}
  .divider {{ border: none; border-top: 1px solid #e8ecf0; margin: 24px 0; }}
  .cta-section {{ background: #f7f9fc; border-radius: 8px; padding: 20px 24px; }}
  .cta-label {{ font-size: 13px; color: #4a5568; margin-bottom: 14px; line-height: 1.5; }}
  .btn {{ display: inline-block; padding: 11px 22px; border-radius: 6px; font-size: 14px;
          font-weight: 600; text-decoration: none; margin-right: 10px; margin-bottom: 8px; }}
  .btn-primary {{ background: {accent}; color: #ffffff; }}
  .btn-secondary {{ background: #ffffff; color: {accent}; border: 2px solid {accent}; }}
  .footer {{ background: #f7f9fc; border-top: 1px solid #e8ecf0; padding: 16px 32px;
             border-radius: 0 0 10px 10px; font-size: 12px; color: #a0aec0; line-height: 1.5; }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <div class="header-eyebrow">Weekly AI Digest</div>
    <h1>{title}</h1>
    <div class="header-meta">Week of {week_display} &nbsp;·&nbsp; {story_count} stories this week</div>
  </div>

  <div class="body">
    <p class="intro">
      Your weekly briefing on AI developments that matter. Below are the top stories —
      the full structured digest with all sources and detail is attached as an HTML document.
    </p>

    <div class="section-label">Top Stories This Week</div>
    {story_cards_html}

    <hr class="divider">

    <div class="cta-section">
      <p class="cta-label">
        <strong>Full digest attached</strong> as <code>{attachment_name}</code> — open it in your browser
        to read all items with full detail, playbooks, and clickable source links.<br><br>
        Prefer to listen? The podcast-style audio version covers the top stories in ~10 minutes.
      </p>
      <a href="{audio_url}" class="btn btn-primary">&#9654;&nbsp; Listen to Podcast Version</a>
      <a href="{audio_url}" class="btn btn-secondary">&#8681;&nbsp; Download MP3</a>
    </div>
  </div>

  <div class="footer">
    This digest is auto-generated every Monday via GitHub Actions using OpenAI.<br>
    Sources are embedded as hyperlinks in the attached HTML document.
  </div>
</div>
</body>
</html>"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def chunk_text_for_tts(text: str, max_chars: int = 4000) -> list[str]:
    """Split text at sentence boundaries to fit TTS API limit."""
    paragraphs = text.split("\n")
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) + 1 > max_chars:
            if current.strip():
                chunks.append(current.strip())
            current = para + "\n"
        else:
            current += para + "\n"
    if current.strip():
        chunks.append(current.strip())
    return chunks or [text[:max_chars]]


def research_news(queries: list[str]) -> str:
    """
    Gather recent news using the Tavily Search API.
    Restricts results to the past 7 days so all content is current.
    Returns a formatted string of search results with titles, URLs, and content snippets
    ready to be passed to GPT-4o for digest generation.
    """
    all_results: list[str] = []

    for i, query in enumerate(queries):
        print(f"    [{i+1}/{len(queries)}] Tavily search: {query[:70]}...")
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": TAVILY_API_KEY,
                    "query": query,
                    "search_depth": "advanced",   # deeper crawl, more relevant results
                    "max_results": 6,
                    "days": 7,                     # only the past 7 days
                    "include_answer": True,        # Tavily's own AI summary of results
                    "include_raw_content": False,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            block_lines = [f"## Search: {query}\n"]

            # Tavily's synthesised answer for this query
            if data.get("answer"):
                block_lines.append(f"**Summary:** {data['answer']}\n")

            # Individual search results
            for r in data.get("results", []):
                title = r.get("title", "Untitled")
                url = r.get("url", "")
                content = r.get("content", "").strip()
                score = r.get("score", 0)
                block_lines.append(f"### [{title}]({url})")
                block_lines.append(f"Relevance score: {score:.2f}")
                block_lines.append(content)
                block_lines.append("")

            all_results.append("\n".join(block_lines))

        except Exception as e:
            print(f"    Warning: Tavily search failed for query {i+1}: {e}")
            all_results.append(f"[Search failed for: {query} — {e}]")

        if i < len(queries) - 1:
            time.sleep(0.5)  # light throttle between queries

    return "\n\n---\n\n".join(all_results)


def generate_full_digest(digest_type: str, research: str) -> str:
    """Generate the full structured digest in Markdown."""
    system = CS_SYSTEM_PROMPT if digest_type == "cs" else CTO_SYSTEM_PROMPT
    label = "Customer Success Leadership" if digest_type == "cs" else "Software Engineering / CTO"

    print(f"    Generating full digest with {MODEL_DIGEST}...")
    response = openai_client.chat.completions.create(
        model=MODEL_DIGEST,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": (
                f"Create the complete Weekly AI Digest for {label} covering the week of {WEEK_DISPLAY}.\n\n"
                f"Here is the web research gathered for this week:\n\n{research}\n\n"
                "Generate a complete, well-structured digest following the required format exactly. "
                "Include all required sections and all required fields per news item. "
                "Use real company names, real products, and real incidents from the research above. "
                "Embed source URLs as inline Markdown hyperlinks [text](url). "
                "Aim for 5–8 news items ordered by impact."
            )},
        ],
        max_completion_tokens=4096,
    )
    return response.choices[0].message.content


def generate_short_summary(full_digest: str, digest_type: str) -> list[dict]:
    """Extract the top 5 items as structured JSON for the email body."""
    label = "Customer Success Leadership" if digest_type == "cs" else "Software Engineering / CTO"
    print(f"    Generating short email summary with {MODEL_AUXILIARY}...")
    response = openai_client.chat.completions.create(
        model=MODEL_AUXILIARY,
        messages=[
            {
                "role": "system",
                "content": (
                    "You extract the top 5 most important stories from a digest and return them as JSON. "
                    "Return only a valid JSON array, no markdown code fences."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"From this {label} AI digest, extract the top 5 most impactful stories.\n"
                    "Return a JSON array of objects with exactly these keys:\n"
                    '  "title": short punchy headline (max 12 words)\n'
                    '  "summary": 1-2 sentences describing the key takeaway and why it matters\n\n'
                    f"Digest (first 6000 chars):\n{full_digest[:6000]}"
                ),
            },
        ],
    )
    raw = response.choices[0].message.content.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except Exception:
        return [{"title": "Weekly AI Digest Ready", "summary": "See the attached document for this week's full digest with all stories and sources."}]


def generate_podcast_script(full_digest: str, digest_type: str) -> str:
    """Generate a conversational podcast script for TTS narration (~10 min / ~1500 words)."""
    label = "Customer Success Leadership" if digest_type == "cs" else "Software Engineering and CTO"
    print(f"    Generating podcast script with {MODEL_AUXILIARY}...")
    response = openai_client.chat.completions.create(
        model=MODEL_AUXILIARY,
        messages=[
            {
                "role": "system",
                "content": (
                    "You convert structured weekly digests into engaging, conversational podcast scripts "
                    "optimised for text-to-speech narration. Write as if a knowledgeable analyst is briefing "
                    "a busy executive. No bullet symbols, no markdown — pure flowing spoken prose."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Convert this {label} AI digest into a podcast script (target: ~1500 words, ~10 min spoken).\n\n"
                    f"Opening line: \"Welcome to your Weekly AI Digest for {label}. "
                    f"I'm covering the week of {WEEK_DISPLAY}. Let's get into it.\"\n\n"
                    "Cover the top 5 to 6 most important items with enough context and practical takeaways "
                    "that the listener can act on what they've heard. Mention company names and concrete details.\n\n"
                    f"Closing line: \"That's your weekly briefing. The full digest with all sources is in your inbox "
                    f"as an attached document. Have a productive week.\"\n\n"
                    f"Digest:\n{full_digest}"
                ),
            },
        ],
        max_completion_tokens=2200,
    )
    return response.choices[0].message.content


def generate_audio(podcast_script: str) -> bytes:
    """Generate TTS audio (MP3), chunking the script to respect API limits."""
    chunks = chunk_text_for_tts(podcast_script, max_chars=4000)
    print(f"    Generating audio: {len(chunks)} TTS chunk(s)...")
    audio_data = b""
    for i, chunk in enumerate(chunks):
        print(f"      Chunk {i+1}/{len(chunks)} ({len(chunk)} chars)")
        response = openai_client.audio.speech.create(
            model=MODEL_TTS,
            voice=TTS_VOICE,
            input=chunk,
            response_format="mp3",
        )
        audio_data += response.content
    return audio_data


def markdown_to_html(md_text: str, title: str) -> str:
    """Convert Markdown digest to a fully styled, self-contained HTML document."""
    body_html = markdown2.markdown(
        md_text,
        extras=["tables", "fenced-code-blocks", "header-ids", "strike", "target-blank-links"],
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    max-width: 860px; margin: 0 auto; padding: 48px 32px; color: #1a202c; line-height: 1.7;
    font-size: 15px;
  }}
  h1 {{ font-size: 26px; color: #1a202c; border-bottom: 3px solid #3b82f6; padding-bottom: 14px;
        margin-bottom: 6px; }}
  h2 {{ font-size: 20px; color: #2d3748; margin-top: 40px; padding-bottom: 6px;
        border-bottom: 1px solid #e2e8f0; }}
  h3 {{ font-size: 16px; color: #2d3748; margin-top: 28px; margin-bottom: 8px; }}
  h4 {{ font-size: 14px; color: #4a5568; margin-top: 16px; }}
  a {{ color: #3b82f6; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  ul, ol {{ padding-left: 22px; }}
  li {{ margin-bottom: 5px; }}
  p {{ margin-bottom: 12px; }}
  blockquote {{
    border-left: 4px solid #3b82f6; margin: 16px 0; padding: 10px 18px;
    background: #eff6ff; color: #1e3a5f; border-radius: 0 6px 6px 0;
  }}
  table {{ border-collapse: collapse; width: 100%; margin: 18px 0; font-size: 14px; }}
  th, td {{ border: 1px solid #e2e8f0; padding: 9px 14px; text-align: left; }}
  th {{ background: #f7fafc; font-weight: 600; }}
  tr:nth-child(even) {{ background: #fafbfc; }}
  code {{ background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 13px;
          font-family: 'SF Mono', 'Fira Code', monospace; }}
  pre code {{ display: block; padding: 14px; overflow-x: auto; line-height: 1.5; }}
  hr {{ border: none; border-top: 1px solid #e2e8f0; margin: 32px 0; }}
  .meta {{ color: #718096; font-size: 13px; margin-bottom: 32px; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="meta">Generated {WEEK_DISPLAY} &nbsp;·&nbsp; Weekly AI Digest</p>
{body_html}
</body>
</html>"""


# ── GitHub Release helpers ─────────────────────────────────────────────────────

def get_or_create_github_release(week_date: str, github_token: str, repo: str) -> tuple[int, str]:
    """Return (release_id, upload_url_base), creating the release if needed."""
    tag = f"digest-{week_date}"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    resp = requests.get(
        f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
        headers=headers,
        timeout=30,
    )
    if resp.ok:
        data = resp.json()
        return data["id"], data["upload_url"].split("{")[0]

    resp = requests.post(
        f"https://api.github.com/repos/{repo}/releases",
        headers=headers,
        json={
            "tag_name": tag,
            "name": f"Weekly AI Digest – Week of {WEEK_DISPLAY}",
            "body": (
                f"Auto-generated weekly AI digests for the week of {WEEK_DISPLAY}.\n\n"
                "This release contains the podcast-style audio files for both digests."
            ),
            "prerelease": False,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["id"], data["upload_url"].split("{")[0]


def upload_release_asset(
    release_id: int,
    upload_url_base: str,
    filename: str,
    content: bytes,
    github_token: str,
) -> str:
    """Upload a file to a GitHub Release. Returns the browser download URL."""
    headers = {
        "Authorization": f"token {github_token}",
        "Content-Type": "audio/mpeg",
    }
    resp = requests.post(
        f"{upload_url_base}?name={filename}",
        headers=headers,
        data=content,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["browser_download_url"]


# ── Email builder ──────────────────────────────────────────────────────────────

def build_story_cards_html(items: list[dict], accent: str) -> str:
    cards = []
    for item in items[:5]:
        title = item.get("title", "")
        summary = item.get("summary", "")
        cards.append(
            f'<div class="story-card">'
            f"<h3>{title}</h3>"
            f"<p>{summary}</p>"
            f"</div>"
        )
    return "\n".join(cards)


def send_email(
    digest_type: str,
    short_items: list[dict],
    full_digest_html: str,
    audio_url: str,
    gmail_user: str,
    gmail_password: str,
    recipient: str,
) -> None:
    if digest_type == "cs":
        title = "Customer Success Leadership"
        header_bg = "#1e3a5f"
        accent = "#2563eb"
    else:
        title = "Engineering & CTO"
        header_bg = "#14532d"
        accent = "#16a34a"

    full_title = f"Weekly AI Digest – {title}"
    subject = f"{full_title} | Week of {WEEK_DISPLAY}"
    attachment_name = f"AI-Digest-{'CS' if digest_type == 'cs' else 'CTO'}-{WEEK_DATE}.html"

    story_cards_html = build_story_cards_html(short_items, accent)

    body_html = EMAIL_HTML_TEMPLATE.format(
        title=title,
        week_display=WEEK_DISPLAY,
        story_count=len(short_items),
        header_bg=header_bg,
        accent=accent,
        story_cards_html=story_cards_html,
        audio_url=audio_url,
        attachment_name=attachment_name,
    )

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = f"AI Digest <{gmail_user}>"
    msg["To"] = recipient

    msg.attach(MIMEText(body_html, "html", "utf-8"))

    attachment_part = MIMEApplication(
        full_digest_html.encode("utf-8"),
        Name=attachment_name,
    )
    attachment_part["Content-Disposition"] = f'attachment; filename="{attachment_name}"'
    msg.attach(attachment_part)

    print(f"    Sending email to {recipient}...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, recipient, msg.as_string())
    print(f"    Email sent: {subject}")


# ── Main orchestration ─────────────────────────────────────────────────────────

def run_digest(
    digest_type: str,
    github_token: str,
    github_repo: str,
    gmail_user: str,
    gmail_password: str,
    recipient: str,
    release_id: int,
    upload_url_base: str,
) -> None:
    label = "CS Leadership" if digest_type == "cs" else "CTO/Engineering"
    print(f"\n{'=' * 55}")
    print(f"  Generating {label} Digest")
    print(f"{'=' * 55}")

    print("\n[1/7] Researching news via web search...")
    queries = CS_SEARCH_QUERIES if digest_type == "cs" else CTO_SEARCH_QUERIES
    research = research_news(queries)

    print("\n[2/7] Generating full structured digest...")
    full_digest_md = generate_full_digest(digest_type, research)

    print("\n[3/7] Extracting top stories for email summary...")
    short_items = generate_short_summary(full_digest_md, digest_type)

    print("\n[4/7] Writing podcast script...")
    podcast_script = generate_podcast_script(full_digest_md, digest_type)

    print("\n[5/7] Generating TTS audio...")
    audio_bytes = generate_audio(podcast_script)

    print("\n[6/7] Uploading audio to GitHub Release...")
    audio_filename = f"digest-{'cs' if digest_type == 'cs' else 'cto'}-{WEEK_DATE}.mp3"
    audio_url = upload_release_asset(release_id, upload_url_base, audio_filename, audio_bytes, github_token)
    print(f"    Audio URL: {audio_url}")

    print("\n[7/7] Preparing HTML document and sending email...")
    if digest_type == "cs":
        doc_title = f"Weekly AI Digest – Customer Success Leadership | {WEEK_DISPLAY}"
    else:
        doc_title = f"Weekly AI Digest – Engineering & CTO | {WEEK_DISPLAY}"
    full_digest_html = markdown_to_html(full_digest_md, doc_title)

    send_email(
        digest_type=digest_type,
        short_items=short_items,
        full_digest_html=full_digest_html,
        audio_url=audio_url,
        gmail_user=gmail_user,
        gmail_password=gmail_password,
        recipient=recipient,
    )

    print(f"\n  ✓ {label} digest complete.")


def main() -> None:
    github_token = os.environ["GH_TOKEN"]
    github_repo = os.environ["GITHUB_REPOSITORY"]
    gmail_user = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["RECIPIENT_EMAIL"]
    digest_type = os.environ.get("DIGEST_TYPE", "both").lower()

    print(f"\nWeekly AI Digest Generator")
    print(f"Week of: {WEEK_DISPLAY}")
    print(f"Digest(s): {digest_type}")
    print(f"Repo: {github_repo}")

    # Create one GitHub Release per week, shared by both digest audio files
    print("\nCreating / fetching GitHub Release for this week...")
    release_id, upload_url_base = get_or_create_github_release(WEEK_DATE, github_token, github_repo)
    print(f"  Release ID: {release_id}")

    kwargs = dict(
        github_token=github_token,
        github_repo=github_repo,
        gmail_user=gmail_user,
        gmail_password=gmail_password,
        recipient=recipient,
        release_id=release_id,
        upload_url_base=upload_url_base,
    )

    if digest_type in ("both", "cs"):
        run_digest("cs", **kwargs)

    if digest_type in ("both", "cto"):
        run_digest("cto", **kwargs)

    print("\n\nAll digests generated and sent successfully.")


if __name__ == "__main__":
    main()
