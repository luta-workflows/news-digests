#!/usr/bin/env python3
"""
Weekly AI Digest Generator

Runs in GitHub Actions every Monday morning.
Produces two digests (CS Leadership & CTO/Engineering), each with:
  - A short HTML email summary with top stories
  - A full structured HTML document attachment (links preserved)
  - An MP3 podcast audio file hosted on DigitalOcean Spaces

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
TTS_VOICE = "fable"            # Options: alloy, echo, fable, onyx, nova, shimmer — fable has a British accent

# ── Content quality thresholds ─────────────────────────────────────────────────
# A real digest with 5-8 fully-structured items should comfortably exceed these.
# If the model returns an empty or truncated response the run aborts before
# generating audio or sending email, avoiding junk deliveries.
MIN_DIGEST_CHARS = 3000    # minimum characters for a valid full digest
MIN_PODCAST_CHARS = 1500   # minimum characters for a valid podcast script

# ── Organisational context ─────────────────────────────────────────────────────
# Used as silent background context for the CS digest only.
# It informs how the model selects and frames content — it is NOT surfaced
# as an explicit section in the digest output.

CS_ORG_CONTEXT = """
READER CONTEXT (use this silently to inform relevance judgements — do NOT reference it explicitly in the digest):
The readers are customer support leaders across Visma — a group of 100+ B2B software companies operating
across Europe and beyond. Each company has its own support team; the group is in an active AI adoption
programme. Key priorities for the organisation in 2026 are:
  1. Ensure every Visma company is actively using AI tools in customer support by end of 2026.
  2. Reach a target where at least 50% of customer support inquiries are resolved using AI.

Use this context to:
- Favour news, case studies, and findings relevant to rolling out AI support tooling at scale across
  multiple autonomous product teams and companies within a larger group.
- Give extra weight to stories about AI adoption strategies, change management for support teams,
  measuring AI deflection rates, and lessons learned from enterprise-scale rollouts.
- Frame efficiency and adoption barriers through the lens of a decentralised group (100+ companies)
  rather than a single-company deployment.
- The audience is sophisticated and already committed to AI in support — skip basics, focus on what
  helps them move faster and smarter.

GEOGRAPHIC FOCUS:
- Visma companies are primarily European. Strongly prefer European research, statistics, case studies,
  and regulatory context (e.g. GDPR, EU AI Act) over US-centric data or examples.
- Avoid citing US-only statistics as if they represent a global norm. When only US data is available,
  note its geographic scope briefly and apply it with appropriate caution.
- The four support platforms used across Visma companies are Zendesk, HubSpot, Salesforce, and Intercom.
  Cover updates, new capabilities, and changes to these platforms thoroughly — they are directly relevant
  regardless of where those vendors are headquartered.

HUMAN-IN-THE-LOOP PHILOSOPHY:
- The digest should reflect a nuanced view: AI can and should handle the majority of support inquiries,
  but human support remains essential — particularly for complex, emotionally sensitive, or high-stakes
  cases where customers need reassurance and genuine human judgement.
- Never present "100% AI" as an unqualified goal. The best outcomes come from AI handling volume
  efficiently while freeing skilled human agents to focus on the cases that truly need them.
"""

# ── Search queries ─────────────────────────────────────────────────────────────

CS_SEARCH_QUERIES = [
    f"what customers value most in customer service expectations trends SaaS {NOW.year}",
    f"AI customer support efficiency gains success stories SaaS companies {NOW.year}",
    f"Intercom Fin Zendesk AI Salesforce Einstein HubSpot Breeze new features customer support {NOW.year}",
    f"AI agent automation customer support new capabilities opportunities {NOW.year}",
    f"AI customer support risks hallucination mitigation strategies SaaS {NOW.year}",
    f"customer support personalization self-service CSAT NPS improvement AI {NOW.year}",
    f"enterprise AI support rollout adoption deflection rate scaling multiple teams {NOW.year}",
]

CTO_SEARCH_QUERIES = [
    f"OpenAI Anthropic new model API release capabilities update {NOW.year}",
    f"Cursor AI coding tool Devin Replit AI engineering productivity gains {NOW.year}",
    f"AI agent framework architecture patterns SaaS engineering best practices {NOW.year}",
    f"LLM evaluation testing reliability production engineering patterns {NOW.year}",
    f"AI generated code security incident production failure lessons learned {NOW.year}",
    f"AI engineering tools developer productivity breakthroughs new capabilities {NOW.year}",
]

# ── System prompts ─────────────────────────────────────────────────────────────

CS_SYSTEM_PROMPT = f"""You are an expert analyst creating a weekly digest for a Customer Support Leadership team at a SaaS company. Your audience is customer support leaders — VPs of Support, Head of CX, Support Operations leads — who want to stay ahead of both the exciting opportunities and the real risks in their field.
{CS_ORG_CONTEXT}

AUDIENCE FOCUS: SaaS customer support leadership. Frame everything through the lens of day-to-day support operations, team efficiency, and the customer experience delivered by support teams. This is NOT a general "Customer Success" digest — it is specifically about customer support.

BALANCE REQUIREMENT: This digest must be genuinely balanced. Lead with what is exciting and possible, not with what is scary. Opportunities and new capabilities should receive equal or greater emphasis than risks. Risks must be concrete, actionable, and paired with clear mitigations — not presented as doom-and-gloom.

STRUCTURE PHILOSOPHY:
1. Start with what customers need and value (the goal)
2. Then cover what AI and new tooling can do to meet those needs (the opportunity)
3. Finally cover the risks that come with those tools, with pragmatic mitigations (the guardrails)

For EACH news item, include ALL of the following (use Markdown headers and bullets):
1. **Headline-style title + company/vendor** (H3)
2. **What happened** – 1–2 concise bullets
3. **Opportunity & Customer Experience Upside**
   - What efficiency gain or CX improvement does this enable?
   - Realistic benefit for a SaaS support team (faster resolution, higher CSAT, reduced ticket volume, etc.)
4. **Risk Assessment** *(only if a genuine risk exists — skip or minimise if not relevant)*
   - What could go wrong in a support context
   - Severity: High / Med / Low  |  Likelihood: High / Med / Low
5. **Recommended Actions**
   - Quick win to capture the opportunity
   - Guardrail or monitoring to manage any risk
6. **Where it applies** – Tier-1 Support / Escalations / Self-Service / Onboarding / Voice-of-Customer / QBRs
7. **Who should act** – Support Ops / Team Leads / CX Engineers / Product
8. **Impact Score** – High / Med / Low
9. **Confidence Level** – High / Med / Low

Order items so that the most exciting and highest-upside opportunities appear first. Risk-heavy items without a clear upside go last.

REQUIRED ADDITIONAL SECTIONS (in this order):

### What Customers Value Right Now
3–5 concrete findings or trends about what customers expect and appreciate in great support — drawn from any research, surveys, or case studies in the provided content. Focus on actionable insights a support leader can use immediately.

### AI Opportunities Spotlight
The top 3–5 most impactful AI-powered improvements available *today* for SaaS support teams: new tools, new capabilities, or proven use cases that can meaningfully improve efficiency or customer experience.

### Key Risks & Mitigation Playbook
A concise consolidated view of the most important risks identified this week, paired with specific mitigations. Keep this proportionate — if it was a quiet week for risks, say so.

### What To Do Next Week
3–5 concrete, prioritised actions for a support leader — at least two should be opportunity-capturing, not just risk-mitigation.

### Vendor Capability Snapshot
Short summary of notable support-platform releases and updates this week (Intercom, Zendesk, Salesforce, HubSpot, Freshdesk, etc.), with hyperlinks.

TONE: Forward-looking, constructive, and energising alongside being rigorous and action-oriented. Match the enthusiasm of the opportunities with the pragmatism of the risks. No hype, but no unnecessary alarm either. Write as a trusted advisor who believes AI can genuinely improve support — while being honest about the pitfalls.
FORMAT: Well-structured Markdown. Embed hyperlinks to sources inline using [text](url) format. Do not invent URLs — only use URLs from the research provided.
"""

CTO_SYSTEM_PROMPT = f"""You are an expert analyst creating a weekly AI news digest for a SaaS CTO and hands-on software engineer.

BALANCE REQUIREMENT: This digest must be genuinely balanced between opportunities and risks. Lead with what is genuinely exciting and useful — new capabilities, productivity gains, architectural patterns that work well in practice. Risks and quality notes are important but should be proportionate: flag them clearly when they matter, but do not let caution dominate a week where the headline story is a real breakthrough.

PRIORITY ORDER: High-impact new capabilities > real engineering learnings and patterns > risks and quality notes.

For EACH news item, include ALL of the following (use Markdown headers and bullets):
1. **Headline-style title + vendor/project** (H3)
2. **What changed** – 1–2 concise bullets
3. **Engineering Upside**
   - What does this genuinely enable that wasn't practical before?
   - Concrete productivity gain, capability unlock, or architectural simplification
4. **Engineering Implications**
   - Architecture impact
   - Cost implications
   - Latency / performance
5. **Risk / Quality Note** *(only if a genuine concern exists — skip if the story is straightforwardly positive)*
   - Failure modes, gotchas, where it breaks
   - Severity: High / Med / Low
6. **Quick Experiment Idea** – a small, practical test worth running this week
7. **Impact Score** – High / Med / Low
8. **Confidence Level** – High / Med / Low

Order items by overall engineering value: highest genuine upside first. Risk-only stories go last.

REQUIRED ADDITIONAL SECTIONS (in this order):

### What's Worth Your Attention This Week
2–3 sentences on the single most significant development across all the week's news — the thing a busy engineer absolutely should not miss.

### Recommended Experiments
3–5 concrete, low-effort experiments that can be kicked off immediately to validate or take advantage of this week's developments.

### Key Risks & Mitigations
Concise consolidated view of the most important risks or quality concerns from this week, with specific mitigations. Keep this proportionate — if it was a quiet week for risks, say so briefly.

### Tooling Watchlist
Brief list of notable releases, updates, or tools worth tracking this week, with hyperlinks.

TONE: Engineering-first and reality-based — genuinely enthusiastic about real breakthroughs, appropriately skeptical of hype, focused on tradeoffs. Match the energy to the week: if something is a genuine leap forward, say so clearly. No vendor marketing language, but also no reflexive cynicism.
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
      Your weekly briefing on what customers value, AI opportunities for support teams, and key risks to watch.
      Below are the top stories — the full structured digest with all sources and detail is attached as an HTML document.
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

def validate_content_length(content: str | None, step: str, min_chars: int) -> str:
    """
    Assert that generated content meets the minimum length threshold.
    Raises RuntimeError if the content is empty, None, or suspiciously short,
    which stops the pipeline before any downstream steps (audio, email) run.
    """
    if not content or not content.strip():
        raise RuntimeError(
            f"[ABORT] {step}: model returned empty content. "
            "Check API key, model name, and rate limits."
        )
    actual = len(content.strip())
    if actual < min_chars:
        preview = content.strip()[:200].replace("\n", " ")
        raise RuntimeError(
            f"[ABORT] {step}: content too short ({actual} chars, minimum {min_chars}). "
            f"Model response preview: {preview!r}"
        )
    print(f"    ✓ Content length OK: {actual:,} chars")
    return content


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
                    "topic": "news",               # target news sources; adds published_date metadata
                    "time_range": "week",          # only the past 7 days
                    "include_answer": True,        # Tavily's own AI summary of results
                    "include_raw_content": False,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            has_answer = bool(data.get("answer"))
            block_lines = [f"## Search: {query}\n"]

            # Tavily's synthesised answer for this query
            if has_answer:
                block_lines.append(f"**Summary:** {data['answer']}\n")

            # Individual search results
            for r in results:
                title = r.get("title", "Untitled")
                url = r.get("url", "")
                content = r.get("content", "").strip()
                score = r.get("score", 0)
                published_date = r.get("published_date", "")
                block_lines.append(f"### [{title}]({url})")
                date_str = f" | Published: {published_date}" if published_date else ""
                block_lines.append(f"Relevance score: {score:.2f}{date_str}")
                block_lines.append(content)
                block_lines.append("")

            block_text = "\n".join(block_lines)
            all_results.append(block_text)

            print(
                f"      → {len(results)} result(s), "
                f"answer={'yes' if has_answer else 'no'}, "
                f"{len(block_text):,} chars"
            )

        except Exception as e:
            print(f"    Warning: Tavily search failed for query {i+1}: {e}")
            all_results.append(f"[Search failed for: {query} — {e}]")

        if i < len(queries) - 1:
            time.sleep(0.5)  # light throttle between queries

    return "\n\n---\n\n".join(all_results)


def generate_full_digest(digest_type: str, research: str) -> str:
    """Generate the full structured digest in Markdown."""
    system = CS_SYSTEM_PROMPT if digest_type == "cs" else CTO_SYSTEM_PROMPT
    label = "Customer Support Leadership" if digest_type == "cs" else "Software Engineering / CTO"

    print(f"    Generating full digest with {MODEL_DIGEST}...")
    print(f"    Research input: {len(research):,} chars sent to model")
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
    )
    choice = response.choices[0]
    content = choice.message.content
    finish_reason = choice.finish_reason
    usage = response.usage
    print(
        f"    OpenAI response — finish_reason: {finish_reason!r}, "
        f"content type: {type(content).__name__}, "
        f"content length: {len(content) if content else 0} chars"
    )
    if usage:
        print(
            f"    Token usage — prompt: {usage.prompt_tokens}, "
            f"completion: {usage.completion_tokens}, "
            f"total: {usage.total_tokens}"
        )
    if finish_reason == "length":
        print(
            f"    WARNING: finish_reason='length' — model hit max_completion_tokens. "
            "If content is empty this is a reasoning model consuming all tokens internally. "
            "Increase max_completion_tokens further if this happens again."
        )
    if content:
        print(f"    Content preview: {content.strip()[:200].replace(chr(10), ' ')!r}")
    else:
        print(f"    WARNING: content is {content!r} — model may use reasoning tokens only")
    validate_content_length(content, "Full digest generation", MIN_DIGEST_CHARS)
    return content


def generate_short_summary(full_digest: str, digest_type: str) -> list[dict]:
    """Extract the top 5 items as structured JSON for the email body."""
    label = "Customer Support Leadership" if digest_type == "cs" else "Software Engineering / CTO"
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
    label = "Customer Support Leadership" if digest_type == "cs" else "Software Engineering and CTO"
    print(f"    Generating podcast script with {MODEL_AUXILIARY}...")
    print(f"    Digest input: {len(full_digest):,} chars sent to model")

    if digest_type == "cs":
        system_persona = (
            "You convert structured weekly digests into engaging, conversational podcast scripts "
            "optimised for text-to-speech narration. Write as if a knowledgeable, enthusiastic colleague "
            "is briefing a busy customer support leader over coffee — warm, clear, and energising. "
            "Tone: constructive and forward-looking. Lead with opportunities and exciting developments. "
            "When covering risks, be factual and solution-oriented — never alarmist or dramatic. "
            "No bullet symbols, no markdown — pure flowing spoken prose."
        )
        opening_line = (
            f"Welcome to your Weekly Customer Support AI Digest. "
            f"I'm covering the week of {WEEK_DISPLAY}. There's a lot of exciting stuff this week, so let's dive in."
        )
        narrative_flow = (
            "1. Start with what customers are telling us they value right now — set the context for why this week's news matters.\n"
            "2. Cover the top AI opportunities and new capabilities for support teams — be enthusiastic and concrete about what's possible.\n"
            "3. Address the key risks and mitigations — be honest and practical, but keep it proportionate and solution-focused.\n"
            "4. Close with the top 2–3 actions for support leaders this week ahead."
        )
    else:
        system_persona = (
            "You convert structured weekly digests into engaging, conversational podcast scripts "
            "optimised for text-to-speech narration. Write as if a sharp, pragmatic engineering colleague "
            "is briefing a busy CTO or senior engineer over coffee — direct, technically grounded, and energising. "
            "Tone: reality-based and enthusiastic about genuine breakthroughs, appropriately skeptical of hype. "
            "Lead with the most impactful new capabilities and engineering patterns. "
            "When covering risks, be concrete and solution-oriented — never alarmist. "
            "No bullet symbols, no markdown — pure flowing spoken prose."
        )
        opening_line = (
            f"Welcome to your Weekly Engineering and AI Digest. "
            f"I'm covering the week of {WEEK_DISPLAY}. There's a lot worth unpacking this week, so let's get into it."
        )
        narrative_flow = (
            "1. Start with the single most significant development this week — the thing a busy engineer should not miss.\n"
            "2. Cover the top new capabilities, tools, and architectural patterns — be concrete about what they enable.\n"
            "3. Address the key risks and quality concerns — be honest and practical, proportionate to the week.\n"
            "4. Close with the top 2–3 experiments or actions worth kicking off this week."
        )

    response = openai_client.chat.completions.create(
        model=MODEL_AUXILIARY,
        messages=[
            {
                "role": "system",
                "content": system_persona,
            },
            {
                "role": "user",
                "content": (
                    f"Convert this {label} digest into a podcast script (target: ~1500 words, ~10 min spoken).\n\n"
                    f"Opening line: \"{opening_line}\"\n\n"
                    "Follow this narrative flow:\n"
                    f"{narrative_flow}\n\n"
                    "Cover 5 to 6 of the most important items. Mention company names and concrete details. "
                    "Keep the energy positive and forward-looking throughout.\n\n"
                    f"Closing line: \"That's your weekly briefing. The full digest with all sources and detail is "
                    f"in your inbox as an attached document. Have a great week — there's a lot to work with.\"\n\n"
                    f"Digest:\n{full_digest}"
                ),
            },
        ],
    )
    choice = response.choices[0]
    content = choice.message.content
    print(
        f"    OpenAI response — finish_reason: {choice.finish_reason!r}, "
        f"content length: {len(content) if content else 0} chars"
    )
    if content:
        print(f"    Content preview: {content.strip()[:150].replace(chr(10), ' ')!r}")
    else:
        print(f"    WARNING: content is {content!r}")
    validate_content_length(content, "Podcast script generation", MIN_PODCAST_CHARS)
    return content


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


# ── DigitalOcean Spaces helpers ────────────────────────────────────────────────

def upload_to_spaces(
    content: bytes,
    filename: str,
    spaces_key: str,
    spaces_secret: str,
    spaces_region: str,
    spaces_bucket: str,
    folder: str = "blog-public-content",
) -> str:
    """Upload audio bytes to DigitalOcean Spaces. Returns the public CDN URL."""
    import boto3
    from botocore.client import Config

    client = boto3.client(
        "s3",
        region_name=spaces_region,
        endpoint_url=f"https://{spaces_region}.digitaloceanspaces.com",
        aws_access_key_id=spaces_key,
        aws_secret_access_key=spaces_secret,
        config=Config(signature_version="s3v4"),
    )
    object_key = f"{folder}/{filename}"
    client.put_object(
        Bucket=spaces_bucket,
        Key=object_key,
        Body=content,
        ContentType="audio/mpeg",
        ACL="public-read",
    )
    return f"https://{spaces_bucket}.{spaces_region}.digitaloceanspaces.com/{object_key}"


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
        title = "Customer Support Leadership"
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
    gmail_user: str,
    gmail_password: str,
    recipient: str,
    spaces_key: str,
    spaces_secret: str,
    spaces_region: str,
    spaces_bucket: str,
) -> None:
    label = "CS Leadership" if digest_type == "cs" else "CTO/Engineering"
    print(f"\n{'=' * 55}")
    print(f"  Generating {label} Digest")
    print(f"{'=' * 55}")

    print("\n[1/7] Researching news via web search...")
    queries = CS_SEARCH_QUERIES if digest_type == "cs" else CTO_SEARCH_QUERIES
    research = research_news(queries)
    print(f"    Research gathered: {len(research):,} chars")

    print("\n[2/7] Generating full structured digest...")
    # validate_content_length is called inside generate_full_digest — will raise on failure.
    full_digest_md = generate_full_digest(digest_type, research)

    print("\n[3/7] Extracting top stories for email summary...")
    short_items = generate_short_summary(full_digest_md, digest_type)
    print(f"    Extracted {len(short_items)} story item(s)")

    print("\n[4/7] Writing podcast script...")
    # validate_content_length is called inside generate_podcast_script — will raise on failure.
    podcast_script = generate_podcast_script(full_digest_md, digest_type)

    print("\n[5/7] Generating TTS audio...")
    audio_bytes = generate_audio(podcast_script)

    print("\n[6/7] Uploading audio to DigitalOcean Spaces...")
    audio_filename = f"digest-{'cs' if digest_type == 'cs' else 'cto'}-{WEEK_DATE}.mp3"
    audio_url = upload_to_spaces(
        audio_bytes, audio_filename,
        spaces_key, spaces_secret, spaces_region, spaces_bucket,
    )
    print(f"    Audio URL: {audio_url}")

    print("\n[7/7] Preparing HTML document and sending email...")
    if digest_type == "cs":
        doc_title = f"Weekly AI Digest – Customer Support Leadership | {WEEK_DISPLAY}"
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
    gmail_user = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["RECIPIENT_EMAIL"]
    digest_type = os.environ.get("DIGEST_TYPE", "both").lower()
    spaces_key = os.environ["DO_SPACES_KEY"]
    spaces_secret = os.environ["DO_SPACES_SECRET"]
    spaces_region = os.environ["DO_SPACES_REGION"]
    spaces_bucket = os.environ["DO_SPACES_BUCKET"]

    print(f"\nWeekly AI Digest Generator")
    print(f"Week of: {WEEK_DISPLAY}")
    print(f"Digest(s): {digest_type}")

    kwargs = dict(
        gmail_user=gmail_user,
        gmail_password=gmail_password,
        recipient=recipient,
        spaces_key=spaces_key,
        spaces_secret=spaces_secret,
        spaces_region=spaces_region,
        spaces_bucket=spaces_bucket,
    )

    if digest_type in ("both", "cs"):
        run_digest("cs", **kwargs)

    if digest_type in ("both", "cto"):
        run_digest("cto", **kwargs)

    print("\n\nAll digests generated and sent successfully.")


if __name__ == "__main__":
    main()
