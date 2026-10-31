"""Deterministic crisis floor: pattern checks that need no model.

This layer exists so that a user disclosing suicidal intent, self-harm, or
abuse **always** sees human crisis resources, even if every model call
fails, times out, or misjudges the message.

Two tiers:

* ``first_person`` -- the person appears to be talking about themselves
  ("I want to die", "he hits me"). Forces the crisis/abuse protocol.
* ``topic`` -- the subject comes up without a first-person signal
  ("what does halacha say about suicide?"). The classifier decides; if the
  classifier is unavailable the turn gets a gentle support card.

Recall matters more than precision here: a false positive costs a resource
card on a scholarly question; a false negative can cost a life. Patterns
are reviewed by a human before changes ship (see backend/evals/).
"""

import re
import unicodedata
from dataclasses import dataclass, field

_ZERO_WIDTH = re.compile("[​-‏‪-‮⁠-⁤﻿]")
# Hebrew points and cantillation (nikud/te'amim) so pointed text matches.
_HEBREW_MARKS = re.compile("[֑-ׇ]")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = _ZERO_WIDTH.sub("", text)
    text = _HEBREW_MARKS.sub("", text)
    text = text.lower().replace("’", "'").replace("`", "'")
    return re.sub(r"\s+", " ", text)


def _rx(*patterns: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)


# --- Self-harm / suicide ---------------------------------------------------

SELF_HARM_FIRST_PERSON = _rx(
    r"\b(i|i'm|im|i am)\b.{0,40}\b(want|wanna|going|gonna|plan(?:ning)?|ready|thinking about|thought about|tempted)\b.{0,15}\b(to )?(die|kill myself|end (it|my life|things)|be dead|disappear forever|not (be )?(here|alive|exist))",
    r"\bkill(ing)? my ?self\b", r"\bkms\b", r"\bunalive (my ?self|me)\b",
    r"\bend(ing)? my (own )?life\b", r"\btake my (own )?life\b", r"\bsuicidal\b",
    r"\b(commit|committing) suicide\b",
    r"\b(don't|dont|do not|no longer) want to (live|be alive|wake up|exist|be here|be around|go on)( anymore)?\b",
    r"\b(don't|dont|do not) want to be (on this earth|in this world)\b",
    r"\bno (reason|point) (to|in) (live|living|going on)\b",
    r"\b(wish|wishing) i (was|were) dead\b", r"\bbetter off (dead|without me)\b",
    r"\b(hurt|hurting|harm|harming|cut|cutting|burn|burning) my ?self\b",
    r"\bself[- ]harm(ing)?\b.{0,20}\b(again|tonight|today|relapse)\b",
    r"\b(overdose|od) on\b", r"\bwrote (a|my) (suicide|goodbye) note\b",
    r"\bcan't go on\b", r"\bcant go on\b", r"\bgoodbye (forever|cruel world)\b",
    r"\b(i|i'm|im|i am|i've|ive|i have|i keep|i've been)\b.{0,30}\b(think|thinking|thought|considering|obsessing)\b.{0,10}\b(about|of)\b.{0,10}\b(suicide|killing myself|ending (it|my life|things)|dying|not being alive)\b",
    r"\bend(ing)? it all\b", r"\b(want|wanna|going) to die\b",
    # Hebrew
    r"אני רוצה למות", r"(רוצה|חושב|חושבת|הולך|הולכת|מתכנן|מתכננת) להתאבד", r"אני (אתאבד|מתאבד|מתאבדת)", r"לשים קץ לחיי",
    r"אין לי (בשביל מה|למה) לחיות", r"לפגוע בעצמי", r"לא רוצה לחיות", r"אני לא רוצה להיות פה",
    # Yeshivish / transliterated
    r"\bi want to be niftar\b",
)

SELF_HARM_TOPIC = _rx(
    r"\bsuicid(e|al)\b", r"\bself[- ]harm\b", r"\bkill (him|her|them)?self\b",
    r"\boverdos(e|ing)\b", r"\bהתאבדות\b", r"\bאיבוד לדעת\b", r"\bmeabed atzmo le ?da'?at\b",
)

# --- Abuse / domestic violence ---------------------------------------------

ABUSE_FIRST_PERSON = _rx(
    r"\b(my )?(husband|wife|boyfriend|girlfriend|partner|father|dad|mother|mom|stepfather|stepdad|brother|uncle|rebbe|rabbi|teacher|madrich|counselor|boss)\b.{0,40}\b(hits|hit|beats|beat|chokes|choked|slaps|slapped|kicks|kicked|rapes|raped|molest(s|ed)|touch(es|ed) me|abus(es|ed) me|threaten(s|ed) (to )?(kill|hurt) me|won't let me (leave|go|see))",
    r"\b(he|she|they)\b.{0,10}\b(hits|beats|chokes|rapes|raped|molested|touched me)\b",
    r"\b(i'm|im|i am) (being )?(abused|beaten|raped|molested|trafficked)\b",
    r"\b(i'm|im|i am) (scared|afraid|terrified) (of|to go home)\b",
    r"\b(sexually|physically|emotionally) abus(ed|ing) me\b",
    r"\b(did|does|do|doing|done) (things|stuff|something|bad things)( bad)? to me\b", r"\bno one (would|will) (ever )?believe me\b",
    r"\bget\b.{0,15}\b(refus|withhold|won't give)", r"\b(won't|wont|refuses to) give me a get\b", r"\bagunah\b",
    r"\b(threaten(s|ed)?|said|says|screams?|scream(ed|ing)?|yell(s|ed)?)\b.{0,15}\b(he|she|they)('ll| will| would| is going to| was going to)? (kill|hurt|beat) me\b",
    # Hebrew
    r"מרביץ לי", r"מכה אותי", r"נגע בי", r"פוגע בי", r"מאיים להרוג אותי", r"אני מפחדת ממנו", r"אני מפחד ממנו",
)

# --- Harm to others ----------------------------------------------------------

HARM_OTHERS_FIRST_PERSON = _rx(
    r"\b(i|i'm|im|i am)\b.{0,30}\b(going|gonna|want|wanna|plan(?:ning)?)( to)? (kill|hurt|shoot|stab|attack|bomb)\b(?! ?my ?self)(?! me\b)",
    r"\bhow (do i|to|can i) (kill|poison|hurt) (my|a|the|someone)\b",
)


@dataclass
class LexiconResult:
    self_harm: str = ""        # "", "topic", "first_person"
    abuse: str = ""            # "", "first_person"
    harm_to_others: str = ""   # "", "first_person"
    matched: list[str] = field(default_factory=list)

    @property
    def forces_crisis(self) -> bool:
        return self.self_harm == "first_person"

    @property
    def forces_abuse_protocol(self) -> bool:
        return self.abuse == "first_person"

    @property
    def any(self) -> bool:
        return bool(self.self_harm or self.abuse or self.harm_to_others)


def scan(message: str) -> LexiconResult:
    """Scan one user message. Pure function; sub-millisecond."""
    text = normalize(message)
    result = LexiconResult()
    m = SELF_HARM_FIRST_PERSON.search(text)
    if m:
        result.self_harm = "first_person"
        result.matched.append(m.group(0))
    elif SELF_HARM_TOPIC.search(text):
        result.self_harm = "topic"
    m = ABUSE_FIRST_PERSON.search(text)
    if m:
        result.abuse = "first_person"
        result.matched.append(m.group(0))
    m = HARM_OTHERS_FIRST_PERSON.search(text)
    if m:
        result.harm_to_others = "first_person"
        result.matched.append(m.group(0))
    return result
