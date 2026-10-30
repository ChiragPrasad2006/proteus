"""
email_data_pipeline.synthesis.llm_synthesizer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Batched asynchronous LLM synthesizer compatible with OpenAI-compatible APIs,
vLLM, and Ollama (http://localhost:11434/v1).
Generates user intent bullets, style metadata, authentic chosen emails,
and generic robotic rejected emails for both SFT and Phase 2 DPO alignment.
"""

import asyncio
import json
import logging
import random
import re
from typing import Any, Dict, List, Optional, Tuple
import aiohttp

from ..config import StyleMetadata, PipelineConfig
from ..filters.deslop import contains_ai_slop, clean_markdown_and_html, inject_robotic_slop
from .scenarios import get_random_scenario
from .style_extractor import extract_style_metadata

logger = logging.getLogger("email_data_pipeline.synthesis")


# ---------------------------------------------------------------------------
# Synthesis Prompt Template
# ---------------------------------------------------------------------------
SYNTHESIS_SYSTEM_PROMPT = """You are a Synthetic Dataset Generator creating training data for a Personalized AI Email Writer.
Your goal is to generate realistic, persona-aligned email training pairs in strict JSON format.

RULES FOR GENERATION:
1. Authenticity over Politeness: Real people write with varied pacing, occasional brevity, domain-specific jargon, and distinct greetings/sign-offs. Match the persona's likely age, industry, and seniority.
2. BANNED AI Clichés in chosen_email: NEVER use phrases like "I hope this email finds you well", "I am writing to inform you", "delve", "testament", "tapestry", "pivotal", "foster", "synergy", or "please do not hesitate to reach out".
3. Rejected Email (for DPO): Also generate a rejected_email version of the exact same email that sounds like a generic, overly verbose, robotic ChatGPT output.
4. Output STRICT JSON ONLY. No markdown commentary outside the JSON."""

SYNTHESIS_USER_PROMPT = """Given this <PERSONA>, generate an authentic email training triplet with both a chosen human email and a robotic rejected email:

<PERSONA>
{persona}
</PERSONA>

<SCENARIO_CONTEXT>
{scenario}
</SCENARIO_CONTEXT>

Output Strict JSON Only matching this schema:
{{
  "style_profile": {{
    "formality": "casual | semi-formal | strict-executive | blunt-technical",
    "sentence_structure": "short & punchy | detailed & analytical | warm & conversational",
    "preferred_greeting": "e.g., Hey [Name], | Hi [Name], | [Name] -",
    "preferred_signoff": "e.g., Best, | Cheers, | Thanks, | -[Initial]"
  }},
  "incoming_context": "Optional 1-2 sentence summary of the email being replied to, or 'None (New Thread)'",
  "raw_intent_bullets": [
    "Point 1 the user wants to communicate",
    "Point 2",
    "Call to action or deadline"
  ],
  "chosen_email": "Subject: [Realistic Subject Line]\\n\\n[The authentic, persona-matched email body]",
  "rejected_email": "Subject: [Overly formal AI Subject Line]\\n\\n[Robotic, cliché-ridden AI version of the same email]"
}}"""


class AsyncEmailSynthesizer:
    """
    Batched async client for generating personalized email training pairs.
    Supports local Ollama, vLLM, and remote OpenAI-compatible endpoints.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.base_url = config.llm_base_url.rstrip("/")
        self.endpoint = f"{self.base_url}/chat/completions"
        self.api_key = config.llm_api_key
        self.model = config.llm_model
        self.semaphore = asyncio.Semaphore(config.llm_concurrency)
        self.timeout = aiohttp.ClientTimeout(total=config.llm_timeout_seconds)
        self.offline_mode = config.offline_synthesis
        # Seeded RNG drives the offline synthesis pools (deterministic run-to-run)
        self.rng = random.Random(config.seed)

    async def check_endpoint_health(self) -> bool:
        """Pings the LLM endpoint to verify if the server is alive."""
        if self.offline_mode:
            return False

        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3.0)) as session:
                models_url = f"{self.base_url}/models"
                async with session.get(models_url, headers=headers) as resp:
                    if resp.status == 200:
                        logger.info("Successfully connected to LLM server at %s", self.base_url)
                        return True
        except Exception as e:
            logger.warning("Could not reach LLM endpoint (%s): %s. Falling back to offline synthesis engine.", self.base_url, e)
        return False

    async def synthesize_single(
        self,
        session: aiohttp.ClientSession,
        persona: str,
        scenario: Dict[str, str],
        max_retries: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """Synthesizes a single persona + scenario email pair with rate limiting and retries."""
        if self.offline_mode:
            return self._synthesize_offline(persona, scenario)

        prompt_user = SYNTHESIS_USER_PROMPT.format(
            persona=persona,
            scenario=scenario.get("scenario", ""),
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt_user},
            ],
            "temperature": 0.7,
            "max_tokens": 1200,
            "response_format": {"type": "json_object"},
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(max_retries + 1):
            try:
                async with self.semaphore:
                    async with session.post(self.endpoint, json=payload, headers=headers) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            content = data["choices"][0]["message"]["content"]
                            parsed = self._parse_and_validate(content, persona, scenario)
                            if parsed:
                                return parsed
                        elif resp.status in (429, 503):
                            await asyncio.sleep(1.5 * (2**attempt))
                        else:
                            text = await resp.text()
                            logger.debug("LLM API returned %d: %s", resp.status, text[:200])
            except Exception as e:
                logger.debug("Synthesis attempt %d failed: %s", attempt + 1, e)
                if attempt < max_retries:
                    await asyncio.sleep(1.0 * (attempt + 1))

        # Fallback if API calls failed
        return self._synthesize_offline(persona, scenario)

    def _parse_and_validate(
        self, response_text: str, persona: str, scenario: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """Parses LLM JSON response, validates authenticity, and checks for robotic clichés."""
        try:
            # Strip markdown code blocks if model wrapped it in ```json ... ```
            cleaned = re.sub(r"^```(?:json)?\s*", "", response_text.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)

            data = json.loads(cleaned)
            chosen_email = clean_markdown_and_html(data.get("chosen_email") or data.get("email_output") or "")
            rejected_email = clean_markdown_and_html(data.get("rejected_email") or "")

            # De-slop filter on chosen_email
            if contains_ai_slop(chosen_email):
                logger.debug("Rejected synthesized chosen_email containing AI buzzwords.")
                return None

            if len(chosen_email) < self.config.min_email_chars:
                return None

            # If rejected_email is missing or clean, inject robotic buzzwords
            if not rejected_email:
                rejected_email = inject_robotic_slop(chosen_email)

            style_obj = data.get("style_profile", {})
            if isinstance(style_obj, dict):
                style_str = (
                    f"Formality: {style_obj.get('formality', 'semi-formal')} | "
                    f"Sentence Structure: {style_obj.get('sentence_structure', 'short & punchy')} | "
                    f"Greeting: {style_obj.get('preferred_greeting', 'Hi [Name],')} | "
                    f"Sign-off: {style_obj.get('preferred_signoff', 'Best,')}"
                )
            else:
                style_str = str(style_obj)

            incoming_context = data.get("incoming_context") or "None (New Thread)"
            raw_bullets = data.get("raw_intent_bullets", [])
            if isinstance(raw_bullets, list):
                bullets_text = "\n".join(f"- {b.lstrip('-* ')}" for b in raw_bullets if b)
            else:
                bullets_text = str(raw_bullets)

            return {
                "persona": persona,
                "style_profile": style_str,
                "raw_style_dict": style_obj,
                "incoming_context": incoming_context,
                "user_intent_bullets": bullets_text,
                "chosen_email": chosen_email,
                "rejected_email": rejected_email,
                "email_output": chosen_email,  # Backwards compatibility
            }
        except Exception as e:
            logger.debug("Failed parsing LLM JSON: %s", e)
            return None

    def _synthesize_offline(self, persona: str, scenario: Dict[str, str]) -> Dict[str, Any]:
        """
        High-fidelity deterministic offline synthesis fallback.
        Composes varied, persona-conditioned emails from randomized pools of names,
        metrics, deadlines, greetings, and sentence variants so that generated
        content is unique (deduplicator-safe), authentic, and free of AI slop.
        """
        category = scenario.get("category", "project_update")
        scen_desc = scenario.get("scenario", "")
        prefs = self.rng.choice  # local alias for readability

        # ------------------------------------------------------------------
        # Persona voice buckets (greeting / sign-off / tone preferences)
        # ------------------------------------------------------------------
        p_lower = persona.lower()
        if any(k in p_lower for k in ("engineer", "developer", "architect", "sre", "infrastructure", "platform")):
            bucket = "technical"
        elif any(k in p_lower for k in ("executive", "director", "vp ", "vice president", "chief", "head of")):
            bucket = "executive"
        elif any(k in p_lower for k in ("professor", "researcher", "academic", "scientist", "lecturer", "teacher")):
            bucket = "academic"
        elif any(k in p_lower for k in ("founder", "entrepreneur", "startup")):
            bucket = "founder"
        elif any(k in p_lower for k in ("recruiter", "marketing", "sales", "growth", "business development")):
            bucket = "commercial"
        else:
            bucket = "professional"

        first_names = ["Alex", "Jordan", "Priya", "Marcus", "Elena", "Dave", "Sarah", "Tomas",
                       "Nadia", "Kevin", "Lena", "Omar", "Grace", "Hugo", "Mira", "Stefan",
                       "Amara", "Diego", "Ines", "Felix", "Ruth", "Dana", "Ken", "Tessa"]
        last_initials = "ABCDEFGHJKLMNPRSTVW"
        recipient = self.rng.choice(first_names)
        sender = self.rng.choice(first_names)
        while sender == recipient:
            sender = self.rng.choice(first_names)

        greeting_by_bucket = {
            "technical": [f"{recipient} -", f"Hey {recipient},", f"Hi {recipient},"],
            "executive": ["Team,", f"Hi {recipient},", f"{recipient} -"],
            "academic": [f"Dear Dr. {recipient}.,", f"Dear Prof. {recipient}:", f"Hello {recipient},"],
            "founder": [f"Hey {recipient},", f"Hi {recipient},", f"Hello {recipient},"],
            "commercial": [f"Hi {recipient},", f"Hi {recipient} -", f"Hello {recipient},"],
            "professional": [f"Hi {recipient},", f"Hello {recipient},", f"Hi {recipient} team,"],
        }
        greeting = prefs(greeting_by_bucket[bucket])

        casual_signoffs = ["Cheers,\n{n}", "Thanks,\n{n}", "Best,\n{n}", "-{i}"]
        formal_signoffs = ["Best regards,\n{n}", "Regards,\n{n}", "Sincerely,\n{n}"]
        if bucket in ("technical", "founder"):
            sign_off = prefs(casual_signoffs).format(n=self.rng.choice([sender, ""]), i=sender[0]) if self.rng.random() < 0.7 else prefs(formal_signoffs).format(n=sender)
        elif bucket == "executive":
            sign_off = prefs(formal_signoffs).format(n=self.rng.choice([sender, ""]))
        elif bucket == "academic":
            sign_off = "Sincerely,\nProf. " + sender[0] + ". " + sender
        elif bucket == "commercial":
            sign_off = prefs(casual_signoffs).format(n=sender, i=sender[0])
        else:
            sign_off = prefs(formal_signoffs).format(n=sender) if self.rng.random() < 0.8 else prefs(casual_signoffs).format(n=sender, i=sender[0])
        sign_off = "\n".join(line for line in sign_off.split("\n") if line)

        formality_by_bucket = {
            "technical": "blunt-technical",
            "executive": "strict-executive",
            "academic": "semi-formal",
            "founder": "casual",
            "commercial": "warm-conversational",
            "professional": "semi-formal",
        }
        formality = formality_by_bucket[bucket]
        sentence_structure = self.rng.choice(["short & punchy", "detailed & analytical", "warm & conversational"])
        style_profile_str = (
            f"Formality: {formality} | "
            f"Sentence Structure: {sentence_structure} | "
            f"Greeting: {greeting.rstrip(',')} | "
            f"Sign-off: {sign_off.replace(chr(10), '').strip()}"
        )

        # ------------------------------------------------------------------
        # Randomized workplace metrics
        # ------------------------------------------------------------------
        pct = self.rng.randint(12, 58)
        big_pct = self.rng.randint(25, 70)
        days = self.rng.randint(2, 14)
        minutes = self.rng.randint(10, 45)
        dollars = self.rng.randrange(170000, 215000, 5000)
        budget = self.rng.randrange(25000, 95000, 5000)
        seats = self.rng.randint(180, 900)
        options = self.rng.randrange(15000, 35000, 1000)
        months = ["January", "February", "March", "April", "May", "June", "July", "September", "October", "November"]
        month = self.rng.choice(months)
        month2 = self.rng.choice([m for m in months if m != month])
        q = self.rng.choice(["Q1", "Q2", "Q3", "Q4"])
        weekday = self.rng.choice(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
        deadline = self.rng.choice([f"EOD {weekday}", f"by 3 PM on {weekday}", f"before Friday's sync", f"by {self.rng.choice([9, 11, 12, 14, 15, 16])}:00 {self.rng.choice(['AM',''])}".strip()])
        vendors = ["Stripe", "Adyen", "Vanta", "Datadog", "Snowflake", "Auth0", "Segment", "Confluent"]
        vendor = self.rng.choice(vendors)
        vendor2 = self.rng.choice([v for v in vendors if v != vendor])
        systems = ["checkout pipeline", "billing gateway", "reporting module", "notification service", "mobile release", "search stack", "onboarding flow", "data ingestion cron"]
        system = self.rng.choice(systems)
        system2 = self.rng.choice([s for s in systems if s != system])
        sev = self.rng.choice(["1", "2"])
        n_digits = self.rng.randint(10, 45)
        day_mid = self.rng.randint(2, 28)
        leave_start = self.rng.randint(3, 24)
        leave_end = min(28, leave_start + self.rng.randint(4, 10))

        incoming_templates = {
            "salary_negotiation": [
                "The hiring manager shared the formal offer letter with base salary and equity vesting terms after the on-site loop.",
                "HR sent over the third-round offer packet and asked for a response before {deadline}.".format(deadline=deadline),
                "None (New Thread)",
            ],
            "project_delay": "Stakeholders asked whether the {system} launch planned for Friday slips now that integration testing flagged issues.".format(system=system),
            "cold_b2b_pitch": "None (New Thread)",
            "bug_escalation": "Alert triage flagged intermittent 502 gateway timeouts on the {system} over the last {minutes} minutes.".format(system=system, minutes=minutes),
            "vendor_rate_renegotiation": "The {vendor} account rep sent the auto-renewal invoice with a {pct}% uplift ahead of the {q} renewal.".format(vendor=vendor, pct=pct, q=q),
            "cross_team_blocker": "The mobile team reported unannounced breaking field deprecations in the staging GraphQL schema.",
            "client_churn_risk": "Success dashboards showed the customer's weekly sessions cratered after last month's dashboard overhaul.".format(),
            "quarterly_budget_approval": f"Finance opened the {q} procurement window and requested costed allocations before Friday's planning sync.",
            "missed_deadline_postmortem": "The {system} release missed its committed date and leadership asked for a written postmortem.".format(system=system),
            "out_of_office_delegation": f"HR requires a written note for planned absence coverage starting {month2} {leave_start}.",
        }
        incoming_raw = incoming_templates.get(category)
        if isinstance(incoming_raw, list):
            incoming_context = prefs(incoming_raw)
        elif incoming_raw:
            incoming_context = incoming_raw
        else:
            incoming_context = "None (New Thread)"
        if self.rng.random() < 0.12:
            incoming_context = "None (New Thread)"

        # ------------------------------------------------------------------
        # Category body variant pools
        # ------------------------------------------------------------------
        bodies = {

            "salary_negotiation": {
                "subjects": [
                    f"Re: Offer - compensation alignment",
                    f"Offer packet: proposed figures",
                    f"Following up: revised compensation",
                ],
                "openers": [
                    "Thank you for sending the formal offer over. I remain glad about the roadmap and the scope of what we'd be building.",
                    "Appreciated the offer call yesterday. The technical environment evaluated well in my loop.",
                    "Thanks for the detailed offer. I want to bring this to a close properly for both sides.",
                ],
                "middles": [
                    f"Against {self.rng.randint(5, 14)} recent compensation benchmarks for principal-level roles in this market, I'd like to request ${dollars:,} base plus an initial grant of {options:,} options with a four-year schedule.",
                    f"Given the distributed-systems architecture track record you hired for, the figures land below the band I'd expect. My ask: ${dollars:,} base and {options:,} equity units, vesting starting {month} {day_mid}.",
                    f"The scope described in the loop matches senior-plus market bands. With relocation covered internally, my counter is a base of ${dollars:,} and {options:,} options including an accelerated cliff on the first year.",
                ],
                "closers": [
                    "If we can land on these numbers, I'm ready to sign this week and start on the 15th.",
                    f"Should this work, send an updated letter and I'll countersign by {deadline}.",
                    f"Happy to jump on a call {weekday} morning to close this out directly.",
                ],
            },

            "project_delay": {
                "subjects": [
                    f"Schedule update: {system} launch moves to {month.replace('January','Jan')[:3]} {self.rng.randint(8, 28)}",
                    f"Slipping the {system} release by {days} business days",
                    f"Revised target for the {system} rollout",
                ],
                "openers": [
                    f"We need to move the {system} launch by {days} business days.",
                    f"Flagging early: the {system} release won't hold the committed date.",
                    f"Brief update on the {system} rollout target based on yesterday's test results.",
                ],
                "middles": [
                    f"During end-to-end integration testing we caught recurring response timeouts on the {vendor2} integration. Shipping this build without soak cycles exposes the {system2} to unacceptable downtime risk.",
                    f"Root cause traces to third-party {vendor2} API latency plus an unfinished data migration rehearsal. Current failure rate sits around {pct}% of synthetic checkout runs.",
                    f"The {vendor2} dependency added unplanned latency, and the schema rehearsal surfaced {n_digits} failing cases we want covered before go-live.",
                ],
                "closers": [
                    f"{vendor} hotfix is in sandbox; we'll run two more soak cycles over the weekend. Daily telemetry goes to the shared channel, next checkpoint {weekday} 10 AM.",
                    f"Mitigation: {vendor} hotfix deployed in sandbox, plus two soak-test rounds scheduled. I'll post progress daily and re-baseline the plan {deadline}.",
                    f"Plan: pin the {vendor2} fix, complete two soak cycles, and hold a go/no-go review {deadline}. No further scope changes until then.",
                ],
            },

            "cold_b2b_pitch": {
                "subjects": [
                    "Question re: container scan bottlenecks",
                    f"Reducing PR queue latency for platform teams",
                    "Quick idea for your CI security audits",
                ],
                "openers": [
                    "Noticed your team is scaling multi-region clusters this quarter, likely drowning in scanner queues.",
                    f"Saw the hiring posts around your {system2} audit tooling, so I'll keep this short.",
                    "You're probably shipping faster than the scanner queue on every merge. That's the pattern most platform teams report.",
                ],
                "middles": [
                    f"Teams we work with cut inline container audit times by {big_pct}% (Stripe-size checkout teams included) without blocking engineers on false positives.",
                    f"Our inline scanner trims audit time by {big_pct}% on pull-request merges; median queue wait drops below {minutes} seconds.",
                    f"A comparable team cut security-audit overhead by {big_pct}% and two release managers off the rotation entirely.",
                ],
                "closers": [
                    "Worth a ten-minute technical walkthrough next Tuesday at 2 PM? I'll bring the trace breakdown.",
                    f"If useful, I'll send the benchmark trace and grab {self.rng.choice([15, 20, 30])} minutes {weekday}.",
                    "Open to a short walkthrough with your platform leads? No deck, just the profiler output.",
                ],
            },

            "bug_escalation": {
                "subjects": [
                    f"SEV-{sev}: {system} degradation in APAC",
                    f"Escalation: payment failures spiking on {vendor}",
                    f"Sev-{sev} incident - immediate reroute needed",
                ],
                "openers": [
                    f"Escalating a Sev-{sev} incident hitting {vendor} payment endpoints.",
                    f"Raising severity: transaction failures on {vendor} rails are climbing fast.",
                    f"Opening a Sev-{sev} for the {system} after the {vendor} alerts fired.",
                ],
                "middles": [
                    f"Over the last {minutes} minutes, alerts show a {big_pct}% failure spike on checkout transactions for regional card issuers. Upstream, {vendor} acknowledged latency degradation on their edge clusters.",
                    f"{vendor2} health metrics confirm degradation in the region: error rate on the {system} crossed {pct}% and card-auth latency tripled.",
                    f"Failures concentrated on {vendor2} card rails over the past {minutes} minutes; retries are amplifying the error rate to {pct}%.",
                ],
                "closers": [
                    f"Emergency bridge is live at warroom-{self.rng.choice(['apac','emea','latam'])}. Please join now so we can reroute traffic to the secondary provider.",
                    f"I've opened a war room at bridge-{self.rng.randint(1000,9999)}. Need core on-call hands immediately to flip traffic to the failover region.",
                    f"Bridge: link.internal/warroom{self.rng.randint(10,99)}. Request immediate session so we can reroute live traffic.",
                ],
            },

            "vendor_rate_renegotiation": {
                "subjects": [
                    f"Renewal: volume tier review for {vendor}",
                    f"{q} renewal - pricing alignment request",
                    f"Re: {vendor} renewal invoice and seat tiers",
                ],
                "openers": [
                    f"Reviewing the {q} renewal notice from {vendor} before it auto-executes.",
                    f"Ahead of the {q} auto-renewal, thanks for the invoice - I want to reconcile it early.",
                    f"Tackling the {vendor} renewal invoice that landed with the {pct}% uplift.",
                ],
                "middles": [
                    f"Our active seats grew roughly {big_pct}% ({n_digits}K to {seats}) year over year, which should move us into the volume tier, not a premium spot.",
                    f"Consumption across {n_digits},000 events daily tripled since the last term sheet, yet the quote applies a flat {pct}% uplift instead of tier pricing.",
                    f"With {seats} active seats and {big_pct}% growth since last term, the per-seat math went the wrong direction on your standard bands.",
                ],
                "closers": [
                    f"Can you apply the volume tier and hold net-60 payment terms for the {q} term? Happy to review the amended order form {deadline}.",
                    f"Requesting a stitched renewal: tier discount plus {q} term alignment, amortized monthly. Let's chat {weekday}?",
                    "Could we schedule pricing review by end of week? Target outcome: volume tier plus the amended payment terms we discussed.",
                ],
            },

            "cross_team_blocker": {
                "subjects": [
                    f"Blocker: breaking {system2} schema change before freeze",
                    f"Need alignment on profile-query deprecation today",
                    f"Blocked: field deprecation in {system2} API",
                ],
                "openers": [
                    "We've got an architecture blocker between mobile and the API layer that needs decisions today.",
                    f"The unannounced field deprecation in {system2} is blocking mobile QA.",
                    f"Flagging a blocker ahead of the release freeze on {month.replace('January','Jan')[:3]} {day_mid}.",
                ],
                "middles": [
                    f"The schema change deprecated profile-query fields mobile still consumes; the current staging build fails {pct}% of regression runs without a migration step.",
                    f"Consumer apps break on the deprecated fields, and the freeze lands {month2.replace('January','Jan')[:3]} {day_mid}. We need the vendor contract aligned before QA starts.",
                    f"Deprecating those fields without a shim breaks the profile screens outright: staging regressions already sit at {pct}%.",
                ],
                "closers": [
                    f"Proposing a 20-minute alignment huddle {deadline} to agree on the shim plus deprecation window. Can you confirm attendance?",
                    f"Can we lock a 20-minute huddle {deadline}? Decision needed: shim approach and deprecation timeline.",
                    f"Auto-invite going out for {deadline}; needs API and mobile reps with authority to pick the shim path.",
                ],
            },

            "client_churn_risk": {
                "subjects": [
                    "Checking in after the dashboard update",
                    "Quick follow-up on your team's experience",
                    "Support touchpoint: usage review + walkthrough offer",
                ],
                "openers": [
                    "Wanted to check in directly after last month's dashboard overhaul.",
                    "I noticed activity dipped since the interface upgrade and wanted to reach out personally.",
                    "Follow-up from our success team: the new dashboard may have disrupted a few of your reporting workflows.",
                ],
                "middles": [
                    f"Usage dropped about {pct}% against your historical baseline, which usually signals friction in a core workflow rather than lost interest.",
                    f"Your team's sessions fell by roughly {pct}% over the last few weeks - often a sign the upgrade buried a daily routine somewhere.",
                    f"Weekly sessions are down {pct}% versus the pre-upgrade baseline, which usually points to one or two broken habits, not sentiment.",
                ],
                "closers": [
                    f"Can I grab {self.rng.choice([30, 45])} minutes {weekday} for a walkthrough of the updated report flows? I'll also connect product leadership for direct feedback.",
                    f"Offer: a focused walkthrough for your ops team plus a direct line to product for the friction, {weekday} work?",
                    "If it helps, we'll set up a two-session walkthrough and loop our product lead into the second call.",
                ],
            },

            "quarterly_budget_approval": {
                "subjects": [
                    f"{q} procurement: compute allocation request",
                    f"Sign-off needed: ${budget:,} GPU compute for {q}",
                    f"Budget request: training infrastructure for {q}",
                ],
                "openers": [
                    f"Submitting the compute allocation request ahead of the {q} procurement cutoff.",
                    f"Requesting sign-off on the training-infrastructure line for {q}.",
                    f"To keep the {q} training schedule, I need Finance's approval on the attached allocation.",
                ],
                "middles": [
                    f"The ask is a ${budget:,} GPU compute allocation covering model fine-tuning work.",
                    f"Line item: ${budget:,} covering GPU compute for the first training cycle, with a hard stop at the {q} cutoff.",
                    f"Requested allocation: ${budget:,} for dedicated instances through {month2.replace('January','Jan')[:3]} {day_mid}.",
                ],
                "closers": [
                    "Each cycle on internal instances costs roughly a quarter of the recurring API spend and none of it leaves the perimeter.",
                    f"Internal runs project {self.rng.randint(3,6)}.{self.rng.randint(1,9)}x cost savings versus current proprietary API usage, with a second benefit: data stays local.",
                    "The same budget covers two internal cycles, which is under half our recurring external spend for one.",
                    f"Please confirm sign-off before the {q} cutoff so procurement can reserve the instances.",
                ],
            },

            "missed_deadline_postmortem": {
                "subjects": [
                    f"Postmortem: {system} release missed its date",
                    f"Root-cause note: {month.replace('January','Jan')[:3]} {day_mid} release slip",
                    f"Blameless postmortem on the {system} delivery",
                ],
                "openers": [
                    f"Sharing the written postmortem on the {system} release slip.",
                    f"Owning this up front: the {system} commitment we made did not hold.",
                    "Sending the delivery review we promised after the slipped release.",
                ],
                "middles": [
                    f"The gap traces to ambiguous spec language around edge cases: billing proration rules read two ways, and both got built sequentially before QA caught it.",
                    f"Ballpark: specifications left room for interpretation on proration edge cases, the two builds diverged, and QA surfaced it late in the cycle.",
                    f"Two divergent interpretations of the proration spec shipped in parallel - the differences surfaced only during QA, weeks after implementation started.",
                ],
                "closers": [
                    f"Change going forward: a written spec-review checkpoint with sign-off from both owning teams before implementation starts, effective {q} planning.",
                    f"We've instituted spec review gates: both teams sign off before build kicks off, starting with the {q} cycle.",
                    "New process: spec review sign-off from both owning teams is now a hard gate before implementation. First cycle rolls out next {q} planning.".format(q=q),
                ],
            },

            "out_of_office_delegation": {
                "subjects": [
                    f"Out of office {month2.replace('January','Jan')[:3]} {leave_start} - {leave_end - leave_start} days, coverage plan attached",
                    f"Planned leave {month2.replace('January','Jan')[:3]} {leave_start} through {month2.replace('January','Jan')[:3]} {leave_end}: coverage details",
                    "Leave coverage matrix and escalation route",
                ],
                "openers": [
                    f"Flagging planned leave from {month2} {leave_start} through {month2.replace('January','Jan')[:3]} {leave_end} for medical/personal reasons.",
                    f"Heads-up on planned absence: {month2} {leave_start} to {month2.replace('January','Jan')[:3]} {leave_end}.",
                    f"Sharing coverage details ahead of my leave from {month2} {leave_start}.",
                ],
                "middles": [
                    f"Ownership: {self.rng.choice(['Priya','Dave','Sarah','Marcus','Lena'])} covers the {system} workstream, {self.rng.choice(['Tomas','Grace','Kevin','Ruth'])} picks up on-call rotation.",
                    f"The {system} initiative moves to {self.rng.choice(['Priya','Dave','Sarah','Marcus','Lena'])} and the on-call rotation hands to {self.rng.choice(['Tomas','Grace','Kevin','Ruth'])} for the window.",
                        f"{self.rng.choice(['Priya','Dave','Sarah','Marcus','Lena'])} owns the {system} deliverables in my absence; {self.rng.choice(['Tomas','Grace','Kevin','Ruth'])} takes the pager until I return.",
                ],
                "closers": [
                    f"Escalation path: business-critical issues route through {self.rng.choice(['Priya','Dave','Sarah','Marcus'])} -> {self.rng.choice(['Grace','Kevin'])} -> my direct number. Routine items queue in the tracker.",
                    f"For emergencies during the window: {self.rng.choice(['Priya','Dave','Sarah','Marcus'])} first point of contact, with escalation to {self.rng.choice(['Grace','Kevin'])} afterwards. Checkerboard coverage map attached.",
                    f"Critical escalations: {self.rng.choice(['Priya','Dave','Sarah','Marcus'])} is primary and {self.rng.choice(['Grace','Kevin'])} secondary. Routine updates will wait until I'm back in office.",
                ],
            },
        }

        pools = bodies.get(
            category,
            {
                "subjects": [f"Update on {category.replace('_', ' ')}", f"Notes on {category.replace('_', ' ')} plan"],
                "openers": ["Sharing a status update from my side before the planning cycle kicks off.", "Following up with details on the scope deliverables we discussed."],
                "middles": [
                    f"I reviewed the scope deliverables and confirmed engineering capacity for the next sprint across the {system} workstream.",
                    f"Current staffing covers the {system} deliverables, with contingency baked in around the {vendor2} dependency.",
                ],
                "closers": [
                    f"Please review the attached spec and flag blocking concerns {deadline}; we'll proceed as proposed otherwise.",
                    f"Flag blocking concerns by {deadline}, otherwise we'll run with this plan as written.",
                ],
            },
        )

        subject = prefs(pools["subjects"])
        opener = prefs(pools["openers"])
        middle = prefs(pools["middles"])
        closer = prefs(pools["closers"])

        chosen_email = (
            f"Subject: {subject}\n\n"
            f"{greeting}\n\n"
            f"{opener}\n\n"
            f"{middle}\n\n"
            f"{closer}\n\n"
            f"{sign_off}"
        )

        # ------------------------------------------------------------------
        # User intent bullets (randomized so prompts are deduplicator-unique)
        # ------------------------------------------------------------------
        intent_bullets = self._offline_intent_bullets(
            category, pct, big_pct, dollars, options, budget, days, self.rng.randint(2, 28), month, month2, q, weekday, deadline, vendor, vendor2, system, system2
        )

        rejected_email = inject_robotic_slop(chosen_email)

        return {
            "persona": persona,
            "style_profile": style_profile_str,
            "raw_style_dict": {
                "formality": formality,
                "sentence_structure": sentence_structure,
                "preferred_greeting": greeting,
                "preferred_signoff": sign_off.replace(chr(10), "").strip(),
            },
            "incoming_context": incoming_context,
            "user_intent_bullets": intent_bullets,
            "chosen_email": chosen_email,
            "rejected_email": rejected_email,
            "email_output": chosen_email,
        }

    def _offline_intent_bullets(
        self,
        category: str,
        pct: int,
        big_pct: int,
        dollars: int,
        options: int,
        budget: int,
        days: int,
        day_num: int,
        month: str,
        month2: str,
        q: str,
        weekday: str,
        deadline: str,
        vendor: str,
        vendor2: str,
        system: str,
        system2: str,
    ) -> str:
        """Builds three varied intent bullets per category so interface prompts stay unique."""
        pools: Dict[str, List[List[str]]] = {
            "salary_negotiation": [
                [f"Open by expressing {self.rng.choice(['genuine','clear','stated'])} appreciation for the offer and renewed enthusiasm for the role",
                 "Thank the hiring manager and confirm strong interest in the team's roadmap",
                 "Lead with a warm acknowledgment of the offer process and the team's time"],
                [f"Present recent market compensation benchmarks supporting a base salary of ${dollars:,}",
                 f"Reference principal-level market data justifying a ${dollars:,} base",
                 f"Anchor the discussion in external benchmark bands of ${dollars - 5000:,} to ${dollars + 10000:,}"],
                [f"Request confirmation on the adjusted figures with a target signing window of {month} {day_num}",
                 f"Ask for updated paperwork with a signature target of {month} {day_num}",
                 f"Close by seeking alignment on figures and a {weekday} start-date confirmation"],
            ],
            "project_delay": [
                [f"Transparently report the revised delivery date of {month} {day_num} for the milestone",
                 f"State the new go-live window of {month} {day_num}, plus buffer in days",
                 f"Announce the moved milestone and the {days}-business-day delta against the old date"],
                [f"Detail root cause: {vendor2} API latency plus incomplete data migration rehearsal",
                 f"Explain the {vendor2} dependency latency and the unfinished migration rehearsal driving the slip",
                 f"Attribute the shift to third-party {vendor2} latency with documented error rates"],
                [f"Outline mitigation: soak-test cycles, {vendor} hotfix verification, and a {weekday} go/no-go checkpoint",
                 f"Describe the fix plan and request sign-off at the {weekday} checkpoint",
                 f"Propose the mitigation schedule and lock a go/no-go review for {deadline}"],
            ],
            "cold_b2b_pitch": [
                ["Highlight the recurring pain: container security scans slowing the merge queue",
                 "Open with a one-line pain point about scan queues stalling pull requests",
                 "Name the bottleneck: inline audit wait time on every merge"],
                [f"Share a one-sentence case study of {big_pct}% audit-time reduction for a comparable team",
                 f"Cite the {big_pct}% median reduction achieved by similar engineering teams",
                 f"Give a single concrete metric: {big_pct}% faster audit cycles at teams of similar scale"],
                [f"Propose a low-commitment {self.rng.choice([10, 15, 20])}-minute technical discovery call on {weekday}",
                 "Suggest a short technical walkthrough without a sales deck",
                 f"Ask for one {self.rng.choice([15, 20, 30])}-minute slot {weekday} to show the profiler trace"],
            ],
            "bug_escalation": [
                [f"Flag Sev-{self.rng.choice([1, 2])} incident status affecting regional transaction flows",
                 "Declare incident severity and impacted payment rails up front",
                 f"Announce the Sev-{self.rng.choice([1, 2])} status and affected card issuer segment"],
                [f"Summarize the {big_pct}% transaction failure spike and its customer segment",
                 f"Quantify the error-rate spike ({big_pct}%) over the last {days * 2} minutes",
                 f"Report failure telemetry and the affected customer cohort explicitly"],
                ["Request an emergency war-room bridge and immediate traffic rerouting to the failover region",
                 "Ask for immediate on-call participation to flip traffic to secondary",
                 "Request the emergency bridge and authorization to reroute live traffic"],
            ],
            "vendor_rate_renegotiation": [
                [f"Acknowledge the {q} contract renewal deadline ahead of automatic execution",
                 f"Reference the {q} auto-renewal window and the notice clock",
                 "Confirm awareness of the renewal date and the intent to renegotiate"],
                [f"Point out the ~{big_pct}% year-over-year consumption growth across active seats",
                 f"Highlight seat-count growth of {big_pct}% including the event-volume multiplier",
                 f"Show the y/y usage graph: {big_pct}% more consumption on unchanged pricing"],
                [f"Request volume-tier pricing and amended payment terms before {deadline}",
                 f"Ask for tiered pricing, net-60 terms, and a stitched multi-year option by {deadline}",
                 "Request a return to volume-tier bands plus the amended payment schedule"],
            ],
            "cross_team_blocker": [
                [f"Identify the blocker: breaking schema modifications on {system2} queries",
                 f"State the blocker explicitly: deprecated fields consumed by profile screens",
                 f"Name the blocker: the {system2} contract change without a migration shim"],
                [f"Explain downstream regression risk for the {month} release freeze",
                 f"Quantify staging regression impact ({pct}% failing) ahead of the freeze",
                 f"Spell out the blast radius on QA timelines and the per-release freeze"],
                [f"Schedule a mandatory 20-minute alignment huddle by {deadline}",
                 f"Book the cross-team huddle to agree the shim approach before {deadline}",
                 f"Request a 20-minute decision sync no later than {deadline}"],
            ],
            "client_churn_risk": [
                ["Check in warmly on the customer's recent experience with the upgraded interface",
                 "Reach out personally and frame the follow-up as service, not a pitch",
                 "Open with acknowledgment of the disruptive dashboard change"],
                [f"Note the observed {pct}% usage drop and offer a hypothesis about friction",
                 f"Reference the {pct}% session decline and ask where the friction landed",
                 f"Share the usage baseline shift ({pct}%) transparently and invite reaction"],
                [f"Offer a dedicated workflow walkthrough for the operations team on {weekday}",
                 "Propose hands-on walkthrough sessions with their ops leads",
                 f"Suggest a working session {weekday} to restore daily routines quickly"],
            ],
            "quarterly_budget_approval": [
                [f"Outline the proposed ${budget:,} compute allocation for model fine-tuning",
                 f"Present the ${budget:,} line item and its training-cycle scope",
                 f"Break down the ${budget:,} request by compute hours and instance reservations"],
                [f"Contrast internal model ROI against recurring proprietary API costs (projected {self.rng.randint(3,6)}x savings)",
                 "Note the multi-cycle cost advantage of internal runs versus external APIs",
                 f"Highlight projected {self.rng.randint(3,6)}x savings and the data-locality benefit"],
                [f"Request sign-off ahead of the {q} procurement cutoff",
                 f"Ask for Finance's confirmation before the {q} cutoff date",
                 f"Seek the approval stamp within the {q} procurement window"],
            ],
            "missed_deadline_postmortem": [
                [f"Take accountability for the delayed delivery of the {system} module",
                 "State ownership of the miss plainly in the opening line",
                 f"Accept responsibility for the {month2} slip without deflecting"],
                [f"Analyze gaps in initial scope definitions and unintended edge-case divergence",
                 f"Trace the root cause: ambiguous specifications plus the duplicated edge-case builds",
                 f"Explain the specification ambiguity and its downstream rework"],
                [f"Institute revised spec review checkpoints before the {q} build cycle",
                 "Propose the gate process to prevent recurrence, with named owners",
                 f"Commit to the new review-gate process starting {q} planning"],
            ],
            "out_of_office_delegation": [
                [f"Announce absence dates from {month2} {day_num} and expected return date",
                 f"State the leave window {month2} {day_num} through the return date clearly",
                 f"Confirm the planned leave period with the exact return-to-office date"],
                [f"Assign specific project owners ({system} handoff) and channels for active threads",
                 f"Name the coverage owners per workstream plus the working channels",
                 f"List workstream coverage: the {system} owner and the on-call rotation holder"],
                ["Provide the escalation procedure for mission-critical issues during the window",
                 "Define the emergency escalation chain and response expectations",
                 "Spell out the critical-issue escalation path with named backups"],
            ],
        }

        category_bullets = pools.get(
            category,
            [
                ["State the core status of the current initiative plainly",
                 "Open with the current status and the key constraint",
                 "Set context in one sentence without padding"],
                ["Provide the relevant supporting detail and dependencies",
                 "Surface the two or three facts the decision hinges on",
                 "Include the numbers and dependencies that matter here"],
                [f"Request follow-up or confirmation by {deadline}",
                 "Close with the concrete next action and its owner",
                 f"Ask for confirmation on the next step and the {weekday} timing"],
            ],
        )
        bullets = []
        for slot in category_bullets:
            bullets.append(self.rng.choice(slot))
        return "\n".join(f"- {b}" for b in bullets)

        p_lower = persona.lower()
        if "engineer" in p_lower or "developer" in p_lower or "architect" in p_lower or "sre" in p_lower:
            formality = "blunt-technical"
            sentence_structure = "short & punchy"
            greeting = "Alex -"
            sign_off = "-Dave"
            name = "Dave"
        elif "executive" in p_lower or "director" in p_lower or "vp" in p_lower or "chief" in p_lower:
            formality = "strict-executive"
            sentence_structure = "short & punchy"
            greeting = "Team,"
            sign_off = "Regards,\nMarcus"
            name = "Marcus"
        elif "academic" in p_lower or "professor" in p_lower or "researcher" in p_lower:
            formality = "semi-formal"
            sentence_structure = "detailed & analytical"
            greeting = "Dear Dr. Miller,"
            sign_off = "Sincerely,\nDr. Aris Thorne"
            name = "Dr. Thorne"
        elif "founder" in p_lower or "entrepreneur" in p_lower:
            formality = "casual"
            sentence_structure = "short & punchy"
            greeting = "Hey Sarah,"
            sign_off = "Cheers,\nSam"
            name = "Sam"
        else:
            formality = "semi-formal"
            sentence_structure = "warm & conversational"
            greeting = "Hi Jordan,"
            sign_off = "Best regards,\nAlex"
            name = "Alex"

        style_profile_str = (
            f"Formality: {formality} | "
            f"Sentence Structure: {sentence_structure} | "
            f"Greeting: {greeting.rstrip(',')} | "
            f"Sign-off: {sign_off.replace(chr(10), '').strip()}"
        )

        incoming_context_map = {
            "salary_negotiation": "The hiring manager extended a formal offer letter with standard base salary and equity vesting terms.",
            "project_delay": "Stakeholders sent a calendar check-in asking if Friday's scheduled production release remains on track.",
            "cold_b2b_pitch": "None (New Thread)",
            "bug_escalation": "Alert triage team flagged intermittent 502 gateway timeouts on checkout service.",
            "vendor_rate_renegotiation": "The SaaS vendor sent an upcoming automatic renewal invoice with a 15% price increase.",
            "cross_team_blocker": "Frontend team reported unannounced breaking field deprecations in the staging GraphQL schema.",
        }
        incoming_context = incoming_context_map.get(category, "None (New Thread)")

        chosen_templates = {
            "salary_negotiation": (
                "Subject: Re: Offer Package - Next Steps\n\n"
                f"{greeting}\n\n"
                "Thank you for sending over the formal offer. I'm excited about the roadmap and what we can build together.\n\n"
                "Given market benchmarks for Staff-level roles in this domain and the distributed systems architecture experience I'll be bringing to the team, "
                "I'd like to request $185,000 base salary and an initial grant of 25,000 options.\n\n"
                "If we can align on these figures, I am ready to sign immediately and begin on the 15th.\n\n"
                f"{sign_off}"
            ),
            "project_delay": (
                "Subject: Schedule update: Shifting release target to Nov 14\n\n"
                f"{greeting}\n\n"
                "We need to push the target launch date by two weeks to November 14th.\n\n"
                "During end-to-end integration tests yesterday, we caught recurring response timeouts in the third-party billing gateway. "
                "Deploying this build without thorough soak-testing exposes the checkout pipeline to unacceptable downtime risk.\n\n"
                "The vendor has deployed a hotfix in sandbox, and we will run two additional soak cycles over the weekend. I'll share daily test telemetry on Slack.\n\n"
                f"{sign_off}"
            ),
            "cold_b2b_pitch": (
                "Subject: Quick question re: Kubernetes scan bottlenecks\n\n"
                f"{greeting}\n\n"
                "I saw your team is actively scaling multi-region EKS clusters this quarter.\n\n"
                "Most infrastructure leads we work with struggle with container vulnerability scans adding 15+ minutes to every pull request merge queue. "
                "We built an inline scanner that cuts audit times by 65% for Stripe and Datadog engineering teams without blocking engineers on false positives.\n\n"
                "Open to a 10-minute technical walkthrough next Tuesday at 2 PM to see if this solves your merge queue latency?\n\n"
                f"{sign_off}"
            ),
            "bug_escalation": (
                "Subject: SEV-1: APAC payment checkout degradation\n\n"
                f"{greeting}\n\n"
                "Escalating a critical Sev-1 incident impacting our Tokyo payment endpoints.\n\n"
                "Over the last 25 minutes, Datadog alerts detected a 38% failure spike on checkout transactions for JCB and UnionPay cards. "
                "Upstream gateway acknowledged latency degradation on their regional clusters.\n\n"
                "I opened an emergency response bridge at link.internal/warroom-apac. Please jump in immediately so we can re-route active traffic to our secondary provider.\n\n"
                f"{sign_off}"
            ),
        }

        chosen_email = chosen_templates.get(
            category,
            (
                f"Subject: Update on {category.replace('_', ' ').title()}\n\n"
                f"{greeting}\n\n"
                f"Following up on our discussion regarding {category.replace('_', ' ')}. "
                "I reviewed the scope deliverables and confirmed our engineering capacity for next sprint.\n\n"
                "Please review the attached project spec and flag any blocking concerns by 3 PM tomorrow. "
                "We'll proceed with this architecture unless revisions are requested.\n\n"
                f"{sign_off}"
            ),
        )

        rejected_templates = {
            "salary_negotiation": (
                "Subject: In Reference to the Employment Compensation Proposal\n\n"
                "Dear Hiring Committee,\n\n"
                "I hope this email finds you well in today's fast-paced corporate landscape.\n\n"
                "I am writing to express my deepest gratitude for the generous employment offer. As we delve into the multifaceted dimensions of this collaboration, "
                "it is important to remember that compensation stands as a profound testament to mutual synergy.\n\n"
                "Furthermore, navigating the contemporary economic ecosystem requires a holistic approach. Therefore, I would like to propose a pivotal adjustment to the compensation package.\n\n"
                "In conclusion, please do not hesitate to reach out if you have any questions. I look forward to fostering a fruitful partnership.\n\n"
                "Best regards,\nCandidate"
            ),
            "project_delay": (
                "Subject: Important Update Regarding the Delivery Schedule\n\n"
                "Dear Valued Stakeholders,\n\n"
                "I hope this email finds you well on this productive afternoon.\n\n"
                "I am writing to inform you of a pivotal shift in our projected timeline. As we delve into the intricate tapestry of our software delivery lifecycle, "
                "rigorous quality assurance remains a testament to our core values.\n\n"
                "Furthermore, navigating unforeseen third-party vendor complexities necessitates a strategic postponement to foster long-term platform stability.\n\n"
                "In conclusion, please do not hesitate to reach out should you require any additional synergy. Thank you for your continued patience.\n\n"
                "Warm regards,\nProject Management Office"
            ),
        }

        rejected_email = rejected_templates.get(
            category,
            inject_robotic_slop(chosen_email)
        )

        return {
            "persona": persona,
            "style_profile": style_profile_str,
            "raw_style_dict": {
                "formality": formality,
                "sentence_structure": sentence_structure,
                "preferred_greeting": greeting,
                "preferred_signoff": sign_off.replace(chr(10), "").strip(),
            },
            "incoming_context": incoming_context,
            "user_intent_bullets": intent_bullets,
            "chosen_email": chosen_email,
            "rejected_email": rejected_email,
            "email_output": chosen_email,
        }

    async def generate_batch(
        self,
        pairs: List[Tuple[str, Dict[str, str]]],
    ) -> List[Dict[str, Any]]:
        """
        Executes batched async generation across persona-scenario pairs.
        Uses connection pooling and handles partial failures gracefully.
        """
        results: List[Dict[str, Any]] = []

        if self.offline_mode:
            for persona, scenario in pairs:
                item = self._synthesize_offline(persona, scenario)
                results.append(item)
            return results

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            tasks = [
                self.synthesize_single(session, persona, scenario)
                for persona, scenario in pairs
            ]
            batch_outputs = await asyncio.gather(*tasks, return_exceptions=True)

            for item in batch_outputs:
                if isinstance(item, dict):
                    results.append(item)
                elif isinstance(item, Exception):
                    logger.debug("Async worker exception: %s", item)

        return results
