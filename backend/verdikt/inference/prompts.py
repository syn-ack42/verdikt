"""Prompt templates for all inference classes.

Templates use {{VARIABLE_NAME}} placeholders (double curly braces, uppercase).
Call render(template, KEY=value, ...) to substitute.
Call load_prompts(auth_session) to get the active set (DB overrides defaults).
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Default prompt templates
# ---------------------------------------------------------------------------

# ---- LLMJudge ----

JUDGE_SCORE_RUBRIC = (
    "Score guide (predict the score THIS USER would give — not an objective quality rating):\n"
    "  1 = strongly dislikes — clearly contradicts their stated preferences\n"
    "  2 = dislikes — misses what they value; generic, forgettable, or unremarkable\n"
    "  3 = mixed — has some qualities they value and some they don't; a genuine trade-off\n"
    "  4 = likes — clearly shows qualities they value\n"
    "  5 = strongly likes — exemplifies exactly what they want\n"
    "Use the full range. Do NOT inflate scores: content that is merely inoffensive "
    "or unremarkable scores 2, not 3 or 4. The typical score shown per dimension is "
    "the user's historical average — use it as a calibration anchor."
)

JUDGE_TEXT_PROMPT = (
    "You are predicting how a person with specific taste preferences would rate a passage.\n\n"
    "{{SCORE_RUBRIC}}\n\n"
    "Their overall preferences:\n{{OVERALL_SUMMARY}}\n\n"
    "Per-dimension preferences (typical score = their historical average for calibration):\n{{DIM_LINES}}\n\n"
    "Passage to evaluate:\n{{CONTENT}}\n\n"
    "Respond with a JSON object only (no prose, no markdown):\n{{RESPONSE_SCHEMA}}"
)

JUDGE_IMAGE_PROMPT = (
    "You are predicting how a person with specific taste preferences would rate an image.\n\n"
    "{{SCORE_RUBRIC}}\n\n"
    "Their overall preferences:\n{{OVERALL_SUMMARY}}\n\n"
    "Per-dimension preferences (typical score = their historical average for calibration):\n{{DIM_LINES}}\n\n"
    "Evaluate the attached image.\n\n"
    "Respond with a JSON object only (no prose, no markdown):\n{{RESPONSE_SCHEMA}}"
)

# ---- ProfileCrystalliser ----

CRYSTALLISER_DIMENSION_PROMPT = (
    "A user has rated {{DOMAIN}} on the dimension '{{DIM_NAME}}': {{DIM_DESCRIPTION}}.\n\n"
    "{{EXAMPLES}}"
    "{{CONTRAST_INSTRUCTION}}\n\n"
    "Write 2–4 sentences that describe the specific properties of {{DOMAIN}} that drive "
    "a high vs low score on '{{DIM_NAME}}' for this user. "
    "Be concrete: name the actual visual qualities, subjects, styles, techniques, or content "
    "characteristics you observe — not just that the user 'prefers high-scoring' examples, "
    "which would be a tautology. "
    'Respond with a JSON object: {"summary": "<your summary here>"}'
)

CRYSTALLISER_OVERALL_PROMPT = (
    "A user's preferences have been analysed across {{DIM_COUNT}} dimensions:\n\n"
    "{{DIMENSIONS_LIST}}\n\n"
    "Write a 3–5 sentence synthesis of this user's overall preferences. "
    "Focus on the concrete visual or content qualities that characterise what they enjoy — "
    "drawing out patterns that cut across multiple dimensions where they exist. "
    "Avoid restating each dimension in turn; synthesise into a coherent picture of their taste. "
    '{"summary": "<your summary here>"}'
)

# ---- DimensionDiscoverer ----

DISCOVERER_QUALITIES_PROMPT = (
    "A user {{LABEL}} this {{MEDIUM}}.{{REASON_BLOCK}}"
    "{{CONTENT_BLOCK}}\n\n"
    "Describe the 2–3 most characteristic qualities of this {{MEDIUM}} that likely "
    "drove the user's reaction. Consider all relevant dimensions: aesthetic and visual "
    "qualities (style, composition, tone, mood), structural qualities (pacing, structure, "
    "density), and the type of content or subject matter itself (e.g. action, intimacy, "
    "technical detail, humour, a particular subject or setting) — any of these can be a "
    "genuine driver of preference. Be specific and concrete.\n"
    'Respond with JSON only: {"qualities": "<your 2-3 sentence description>"}'
)

DISCOVERER_DIMENSIONS_PROMPT = (
    "You are helping a user discover what they care about in {{DOMAIN}}. "
    "Below are quality-descriptions of samples they reacted to strongly, "
    "labelled by how much they liked or disliked each sample.\n\n"
    "LIKED samples:\n{{LIKED_BLOCK}}\n\n"
    "DISLIKED samples:\n{{DISLIKED_BLOCK}}"
    "{{EXISTING_BLOCK}}\n\n"
    "Based on the contrast between liked and disliked qualities, identify 3–6 rating "
    "dimensions that capture what matters most to this user.\n\n"
    "For each proposed dimension:\n"
    "  - name: short label (2–4 words)\n"
    "  - description: one sentence describing what a HIGH score means\n"
    "  - weight: importance to this user "
    "(0.5=weak signal, 1.0=normal, 1.5–2.0=consistently decisive)\n"
    "  - is_new: true unless it clearly maps to an existing dimension by name\n"
    "  - existing_name: the existing dimension name it replaces (or null)\n\n"
    "Also list any existing dimensions whose qualities NEVER appeared in either liked "
    "or disliked descriptions as irrelevant_existing.\n\n"
    'Respond with JSON only:\n'
    '{"proposed_dimensions": [{"name":"...","description":"...","weight":1.0,"is_new":true,"existing_name":null}], '
    '"irrelevant_existing": [], '
    '"analysis_notes": null}'
)

# ---------------------------------------------------------------------------
# Registry: maps settings key → default template
# ---------------------------------------------------------------------------

PROMPT_KEYS: dict[str, str] = {
    "prompt.judge.score_rubric":         JUDGE_SCORE_RUBRIC,
    "prompt.judge.text":                 JUDGE_TEXT_PROMPT,
    "prompt.judge.image":                JUDGE_IMAGE_PROMPT,
    "prompt.crystalliser.dimension":     CRYSTALLISER_DIMENSION_PROMPT,
    "prompt.crystalliser.overall":       CRYSTALLISER_OVERALL_PROMPT,
    "prompt.discoverer.qualities":       DISCOVERER_QUALITIES_PROMPT,
    "prompt.discoverer.dimensions":      DISCOVERER_DIMENSIONS_PROMPT,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{\{([A-Z_]+)\}\}")


def render(template: str, **kwargs: str) -> str:
    """Replace {{KEY}} placeholders with provided values."""
    def _replace(m: re.Match) -> str:
        return kwargs.get(m.group(1), m.group(0))
    return _PLACEHOLDER_RE.sub(_replace, template)


def load_prompts(auth_session) -> dict[str, str]:
    """Return the active prompt set: defaults overridden by any DB-stored values."""
    from verdikt.storage.auth_orm import SiteSettingsRow
    result = dict(PROMPT_KEYS)
    for key in PROMPT_KEYS:
        row = auth_session.get(SiteSettingsRow, key)
        if row and row.value:
            result[key] = row.value
    return result
