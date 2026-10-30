"""
email_data_pipeline.config
~~~~~~~~~~~~~~~~~~~~~~~~~~
Configuration dataclasses, regex patterns, robotic buzzword dictionaries,
workplace persona filters, and pipeline constants for fine-tuning Qwen2.5-3B-Instruct.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import re


# ---------------------------------------------------------------------------
# Robotic AI Slop / Buzzword Definitions
# ---------------------------------------------------------------------------
# Classic AI buzzwords and robotic transitional clichés that must be eliminated
# from SFT assistant responses and penalized in DPO pairs.
AI_BUZZWORDS: List[str] = [
    # Explicitly requested in prompt
    "I hope this email finds you well",
    "delve",
    "delving",
    "delves",
    "testament",
    "tapestry",
    "furthermore",
    "in conclusion",
    # Additional ubiquitous LLM clichés
    "beacon",
    "pivotal",
    "plethora",
    "embark",
    "embarking",
    "unleash",
    "elevate",
    "game-changer",
    "game changer",
    "foster",
    "fostering",
    "seamless",
    "seamlessly",
    "revolutionize",
    "it is important to remember",
    "it is important to note",
    "it's crucial to note",
    "at the end of the day",
    "navigating the landscape",
    "in today's fast-paced world",
    "in today's digital landscape",
    "as an ai",
    "as an ai language model",
    "as a large language model",
    "not only that, but",
    "let's dive into",
    "a testament to",
    "a rich tapestry",
    "underscores the importance",
    "realm of",
    "ever-evolving landscape",
]

# Case-insensitive compiled regex matching any of the AI buzzwords with word boundaries
_escaped_buzzwords = [re.escape(bw) for bw in AI_BUZZWORDS]
AI_SLOP_REGEX: re.Pattern = re.compile(
    r"\b(?:" + "|".join(_escaped_buzzwords) + r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Email Keyword Filtering Patterns (Dataset A)
# ---------------------------------------------------------------------------
# Keywords requested: "email", "subject:", "dear ", "sincerely", "best regards",
# "follow-up", "cold outreach", "reply to"
EMAIL_KEYWORDS: List[str] = [
    r"\bemail\b",
    r"\bsubject\s*:",
    r"\bdear\s+[a-zA-Z]+",
    r"\bsincerely\b",
    r"\bbest\s+regards\b",
    r"\bfollow-?up\b",
    r"\bcold\s+outreach\b",
    r"\breply\s+to\b",
    r"\bregards\b",
    r"\bcheers\b",
]

EMAIL_KEYWORDS_REGEX: re.Pattern = re.compile(
    "|".join(EMAIL_KEYWORDS),
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Workplace / Professional Persona Filtering Patterns (Dataset B)
# ---------------------------------------------------------------------------
WORKPLACE_INCLUDE_PATTERNS: List[str] = [
    r"\bprofessional\b",
    r"\bcorporate\b",
    r"\bacademic\b",
    r"\bfounder\b",
    r"\bfreelance\b",
    r"\bfreelancer\b",
    r"\bworkplace\b",
    r"\bmanager\b",
    r"\bdirector\b",
    r"\bexecutive\b",
    r"\bconsultant\b",
    r"\banalyst\b",
    r"\bengineer\b",
    r"\bdeveloper\b",
    r"\bresearcher\b",
    r"\bmarketer\b",
    r"\bmarketing\b",
    r"\baccountant\b",
    r"\blawyer\b",
    r"\battorney\b",
    r"\bdoctor\b",
    r"\bphysician\b",
    r"\bprofessor\b",
    r"\binstructor\b",
    r"\beducator\b",
    r"\bteacher\b",
    r"\bspecialist\b",
    r"\bofficer\b",
    r"\barchitect\b",
    r"\bdesigner\b",
    r"\brecruiter\b",
    r"\bhuman\s+resources\b",
    r"\bhr\b",
    r"\bproduct\s+manager\b",
    r"\bsales\b",
    r"\binvestor\b",
    r"\bentrepreneur\b",
    r"\boperations\b",
    r"\badministrator\b",
    r"\bcoordinator\b",
    r"\blead\b",
    r"\bsupervisor\b",
]

WORKPLACE_INCLUDE_REGEX: re.Pattern = re.compile(
    "|".join(WORKPLACE_INCLUDE_PATTERNS),
    re.IGNORECASE,
)

FANTASY_EXCLUDE_PATTERNS: List[str] = [
    r"\bnpc\b",
    r"\bfantasy\b",
    r"\bdragon\b",
    r"\bwizard\b",
    r"\bsorcerer\b",
    r"\bsorceress\b",
    r"\belf\b",
    r"\belven\b",
    r"\bdwarf\b",
    r"\bdwarven\b",
    r"\bgoblin\b",
    r"\borc\b",
    r"\bwarrior\b",
    r"\bknight\b",
    r"\bpaladin\b",
    r"\bking\s+of\b",
    r"\bqueen\s+of\b",
    r"\bemperor\s+of\b",
    r"\bmedieval\b",
    r"\bancient\b",
    r"\bmythical\b",
    r"\bmagical\b",
    r"\balien\b",
    r"\bcyborg\b",
    r"\bvampire\b",
    r"\bwerewolf\b",
    r"\bzombie\b",
    r"\bpirate\b",
    r"\bgladiator\b",
    r"\bassassin\b",
    r"\bsteampunk\b",
    r"\bdungeon\b",
    r"\bvideo\s+game\b",
    r"\bfictional\b",
    r"\b1[0-8]\d\d\s*(?:s|ad|bc|bce)?\b",
    r"\bbc\b",
    r"\bbce\b",
]

FANTASY_EXCLUDE_REGEX: re.Pattern = re.compile(
    "|".join(FANTASY_EXCLUDE_PATTERNS),
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Dataset C Task Filtering (Writing/Communication vs. Math/Coding)
# ---------------------------------------------------------------------------
WRITING_TASK_INCLUDE_PATTERNS: List[str] = [
    r"\bemail\b",
    r"\bletter\b",
    r"\bmわり\b",
    r"\bmemo\b",
    r"\bwrite\b",
    r"\brewrite\b",
    r"\brephrase\b",
    r"\bparaphrase\b",
    r"\btone\b",
    r"\bcommunication\b",
    r"\bprofessional\b",
    r"\bpolite\b",
    r"\bdraft\b",
    r"\bproposal\b",
    r"\bannouncement\b",
    r"\bfeedback\b",
    r"\bcritique\b",
    r"\bedit\b",
    r"\bproofread\b",
    r"\bsummarize\b",
    r"\bmessage\b",
]

WRITING_TASK_INCLUDE_REGEX: re.Pattern = re.compile(
    "|".join(WRITING_TASK_INCLUDE_PATTERNS),
    re.IGNORECASE,
)

CODE_MATH_EXCLUDE_PATTERNS: List[str] = [
    r"```(?:python|golang|cpp|c\+\+|java|rust|csharp|c#|sql|javascript|typescript|bash|sh|ruby|php|swift)",
    r"\bdef\s+[a-zA-Z_]\w*\(",
    r"\bfunction\s+[a-zA-Z_]\w*\(",
    r"\bclass\s+[a-zA-Z_]\w*[:\{]",
    r"\bleetcode\b",
    r"\bsolve\s+for\s+[xyz]\b",
    r"\bcalculate\s+the\s+(?:integral|derivative|probability|matrix|determinant)\b",
    r"\btheorem\b",
    r"\bproof\s+by\s+induction\b",
    r"\bmath(?:ematical)?\s+puzzle\b",
    r"\bsql\s+query\b",
    r"\bdebug\s+this\s+code\b",
    r"\bcompile\s+error\b",
    r"\bsegmentation\s+fault\b",
]

CODE_MATH_EXCLUDE_REGEX: re.Pattern = re.compile(
    "|".join(CODE_MATH_EXCLUDE_PATTERNS),
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Professional Email Scenarios for Synthesis (Dataset B)
# ---------------------------------------------------------------------------
EMAIL_SCENARIOS: List[Dict[str, str]] = [
    {
        "category": "salary_negotiation",
        "scenario": "Countering a promotion or job offer with market data and quantified accomplishments to request a 15% salary increase and additional equity.",
        "default_intent": "- Express gratitude for the offer and reiterate enthusiasm for the role.\n- Present market compensation benchmarks and recent quantifiable impact.\n- Propose an adjusted base salary and equity grant schedule.",
    },
    {
        "category": "project_delay",
        "scenario": "Informing cross-functional executive stakeholders about a 2-week launch delay due to third-party API dependencies and database migration testing.",
        "default_intent": "- Transparently report the revised delivery date for the milestone.\n- Detail root cause: unexpected vendor API latency and data migration tests.\n- Outline mitigation plan, risk buffers, and next status checkpoint.",
    },
    {
        "category": "cold_b2b_pitch",
        "scenario": "Outreaching to a VP of Engineering offering an automated security vulnerability scanner that reduced CI/CD pipeline audit time by 60% for comparable teams.",
        "default_intent": "- Highlight a relevant pain point in CI/CD container security compliance.\n- Share a concise 1-sentence case study with tangible metric reduction.\n- Propose a low-commitment 15-minute technical discovery call next Tuesday.",
    },
    {
        "category": "bug_escalation",
        "scenario": "Escalating a high-severity checkout service outage impacting APAC payment processing to the on-call Site Reliability Engineering lead.",
        "default_intent": "- Flag Sev-1 incident status affecting APAC Stripe/Adyen transaction flows.\n- Summarize error rates (42% failure spike) and affected customer segment.\n- Request emergency war-room link and immediate traffic re-routing.",
    },
    {
        "category": "vendor_rate_renegotiation",
        "scenario": "Renegotiating annual cloud licensing terms before automatic renewal to secure volume tier discounts based on 3x increased enterprise usage.",
        "default_intent": "- Acknowledge the upcoming contract renewal deadline.\n- Point out the 3x year-over-year consumption growth across active seats.\n- Request custom tier volume pricing and amended payment terms.",
    },
    {
        "category": "cross_team_blocker",
        "scenario": "Addressing an architectural blocker between the mobile client and backend teams regarding GraphQL schema changes prior to feature freeze.",
        "default_intent": "- Identify the blocker: breaking schema modifications on user profile queries.\n- Explain downstream regression risks for the imminent iOS app release.\n- Schedule a mandatory 20-minute alignment huddle to agree on field deprecation.",
    },
    {
        "category": "client_churn_risk",
        "scenario": "Proactively reaching out to an enterprise customer whose usage dropped by 40% following a major dashboard UI overhaul.",
        "default_intent": "- Check in warmly on their recent experience with the upgraded interface.\n- Offer a dedicated workflow walkthrough for their operations team.\n- Share direct line to product leadership to capture immediate feedback.",
    },
    {
        "category": "quarterly_budget_approval",
        "scenario": "Submitting a formal request to the Finance Director to approve a $45,000 budget allocation for GPU compute instances for fine-tuning open-source LLMs.",
        "default_intent": "- Outline proposed $45k compute allocation for local LLM fine-tuning.\n- Contrast internal model ROI against recurring proprietary API costs (projected 4.2x savings).\n- Request sign-off ahead of the Q1 procurement cutoff.",
    },
    {
        "category": "missed_deadline_postmortem",
        "scenario": "Sending an honest, constructive postmortem to leadership explaining how ambiguous product specifications caused a missed release target.",
        "default_intent": "- Take accountability for the delayed delivery of the reporting module.\n- Analyze gaps in initial scope definitions and unplanned edge cases.\n- Institute revised technical spec review checkpoints to prevent recurrence.",
    },
    {
        "category": "out_of_office_delegation",
        "scenario": "Communicating an upcoming 2-week medical/personal leave with detailed coverage matrices and escalation points for critical client emergencies.",
        "default_intent": "- Announce absence dates and expected return to office.\n- Assign specific project owners and Slack channels for active initiatives.\n- Provide emergency escalation procedure for mission-critical issues.",
    },
]


# ---------------------------------------------------------------------------
# Data Models / Schemas
# ---------------------------------------------------------------------------
@dataclass
class StyleMetadata:
    tone: str
    greeting_style: str
    sign_off_style: str
    sentence_length: str

    def to_profile_string(self) -> str:
        return (
            f"Tone: {self.tone} | "
            f"Greeting: {self.greeting_style} | "
            f"Sign-off: {self.sign_off_style} | "
            f"Sentence Structure: {self.sentence_length}"
        )


@dataclass
class SFTMessage:
    role: str
    content: str


@dataclass
class SFTRow:
    messages: List[Dict[str, str]]

    def to_dict(self) -> Dict[str, List[Dict[str, str]]]:
        return {"messages": self.messages}


@dataclass
class DPORow:
    prompt: str
    chosen: str
    rejected: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "prompt": self.prompt,
            "chosen": self.chosen,
            "rejected": self.rejected,
        }


@dataclass
class PipelineConfig:
    # Target model & tokenizer
    model_id: str = "Qwen/Qwen2.5-3B-Instruct"

    # Dataset names & subsets
    dataset_a_name: str = "argilla/FinePersonas-Synthetic-Email-Conversations"
    dataset_a_fallback: str = "argilla/FinePersonas-v0.1"
    dataset_b_name: str = "proj-persona/PersonaHub"
    dataset_b_subset: str = "persona"
    dataset_c_name: str = "argilla/distilabel-capybara-dpo-7k-binarized"

    # Output file paths
    output_dir: Path = Path("data")
    sft_train_path: Path = Path("data/sft_email_train.jsonl")
    sft_val_path: Path = Path("data/sft_email_val.jsonl")
    dpo_train_path: Path = Path("data/dpo_email_train.jsonl")
    dpo_val_path: Path = Path("data/dpo_email_val.jsonl")

    # Sample limits (Aligned with 3B-4B Model Proportions: ~12k SFT, ~5k DPO)
    max_samples_a: Optional[int] = 6000
    max_samples_b: Optional[int] = 6000
    max_samples_b_dpo: Optional[int] = 2500
    max_samples_c: Optional[int] = 2500

    # Train / Val split ratio & seed
    val_split_ratio: float = 0.10
    seed: int = 42

    # Processing batch sizes (RAM-efficient for 16GB)
    batch_size: int = 250
    writer_buffer_size: int = 500

    # Minimum character count for assistant email responses
    min_email_chars: int = 150

    # LLM Synthesis settings (Ollama / vLLM / OpenAI compatible)
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "EMPTY"
    llm_model: str = "qwen2.5:3b"
    llm_concurrency: int = 8
    llm_timeout_seconds: float = 30.0
    offline_synthesis: bool = True  # Default to deterministic offline generator if server not up

    # MinHash deduplication settings
    dedup_threshold: float = 0.85
    minhash_num_perm: int = 64
    k_shingle_size: int = 3
