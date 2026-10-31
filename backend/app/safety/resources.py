"""Static, human-reviewed crisis resources shown by the server.

These cards are authored here, not by a model, so their content never
depends on generation. Every number was checked against the organization's
own site on 2026-10-31 (see docs/SAFETY.md for sources and caveats).
Re-verify quarterly; bump ``RESOURCES_VERSION`` on any change.

Ordering rule: emergency services and 24/7 general crisis lines always come
before community-specific services, several of which are referral or
limited-hours lines rather than crisis lines.
"""

from typing import Optional

RESOURCES_VERSION = "2026-10-31"

# --- General crisis lines by region -----------------------------------------

_GENERAL = {
    "US": [
        {"name": "988 Suicide & Crisis Lifeline", "description": "Call or text, 24/7. Spanish available.",
         "phone": "988", "sms": "988", "chat_url": "https://chat.988lifeline.org/",
         "url": "https://988lifeline.org/", "region": "United States", "hours": "24/7"},
        {"name": "Crisis Text Line", "description": "Text HOME to 741741, 24/7.",
         "sms": "741741", "sms_body": "HOME", "url": "https://www.crisistextline.org/",
         "region": "United States", "hours": "24/7"},
    ],
    "CA": [
        {"name": "9-8-8 Suicide Crisis Helpline", "description": "Call or text, 24/7.",
         "phone": "988", "sms": "988", "url": "https://988.ca/", "region": "Canada", "hours": "24/7"},
    ],
    "UK": [
        {"name": "Samaritans", "description": "Free to call, 24/7.", "phone": "116 123",
         "url": "https://www.samaritans.org/", "region": "UK & Ireland", "hours": "24/7"},
        {"name": "Shout (Crisis Text Line UK)", "description": "Text SHOUT to 85258, 24/7.",
         "sms": "85258", "sms_body": "SHOUT", "url": "https://giveusashout.org/",
         "region": "United Kingdom", "hours": "24/7"},
    ],
    "IE": [
        {"name": "Samaritans", "description": "Free to call, 24/7.", "phone": "116 123",
         "url": "https://www.samaritans.org/", "region": "Ireland", "hours": "24/7"},
        {"name": "Crisis Text Line Ireland", "description": "Text HELLO to 50808, 24/7.",
         "sms": "50808", "sms_body": "HELLO", "url": "https://www.crisistextline.org/",
         "region": "Ireland", "hours": "24/7"},
    ],
    "IL": [
        {"name": "ERAN — Emotional First Aid", "description": "Call 1201 (24/7) or WhatsApp. Service mainly in Hebrew.",
         "phone": "1201", "whatsapp": "+972528451201", "url": "https://en.eran.org.il/",
         "region": "Israel", "hours": "Phone 24/7; chat 08:00–02:00"},
        {"name": "Sahar", "description": "Anonymous online emotional support chat.",
         "chat_url": "https://sahar.org.il/", "whatsapp": "+972559571399", "url": "https://sahar.org.il/",
         "region": "Israel", "hours": "Sun–Thu 16:00–03:00; Fri/Sat eves 18:00–00:00"},
    ],
    "INTL": [
        {"name": "Find A Helpline", "description": "Free, confidential crisis lines in your country, by phone, text, or chat.",
         "url": "https://findahelpline.com/", "region": "Worldwide"},
        {"name": "Befrienders Worldwide", "description": "Emotional support centres around the world.",
         "url": "https://befrienders.org/", "region": "Worldwide"},
    ],
    "AU": [
        {"name": "Lifeline Australia", "description": "Call 13 11 14 or text, 24/7.",
         "phone": "13 11 14", "sms": "0477131114", "url": "https://www.lifeline.org.au/",
         "region": "Australia", "hours": "24/7"},
    ],
}

# --- Jewish community support (shown after general lines) -------------------

_JEWISH_TRAUMA = {
    "US": [
        {"name": "Chai Lifeline Crisis Intervention", "description": "Jewish community crisis and trauma response.",
         "phone": "855-327-4747", "url": "https://www.chailifeline.org/crisis", "region": "United States", "hours": "24 hours"},
        {"name": "Relief Resources", "description": "Referrals to vetted mental-health professionals (not a crisis line).",
         "phone": "718-431-9501", "url": "https://www.reliefhelp.org/", "region": "International"},
        {"name": "Jewish Family Services near you", "description": "Find your local Jewish human-service agency.",
         "url": "https://www.networkjhsa.org/agency-locator/", "region": "US & Canada"},
    ],
    "CA": [
        {"name": "Jewish Family Services near you", "description": "Find your local Jewish human-service agency.",
         "url": "https://www.networkjhsa.org/agency-locator/", "region": "US & Canada"},
    ],
    "UK": [
        {"name": "Jami", "description": "UK Jewish mental-health charity. In crisis, text \"Jami\" to 85258 (24/7).",
         "phone": "020 8458 2223", "sms": "85258", "sms_body": "Jami", "url": "https://jamiuk.org/", "region": "United Kingdom"},
    ],
    "IL": [
        {"name": "NATAL — Israel Trauma and Resiliency Center", "description": "War and terror trauma support, including after October 7.",
         "phone": "*3362", "url": "https://www.natal.org.il/en/", "region": "Israel", "hours": "24/7"},
        {"name": "Israel Trauma Coalition", "description": "Resilience centers and trauma hotlines across Israel.",
         "url": "https://www.israeltraumacoalition.org/", "region": "Israel"},
    ],
}

_ABUSE = {
    "US": [
        {"name": "National Domestic Violence Hotline", "description": "Call or text, 24/7.",
         "phone": "800-799-7233", "sms": "88788", "sms_body": "START", "url": "https://www.thehotline.org/",
         "region": "United States", "hours": "24/7"},
        {"name": "Shalom Task Force", "description": "Confidential hotline for domestic abuse in the Jewish community (call, text, or WhatsApp).",
         "phone": "888-883-2323", "url": "https://www.shalomtaskforce.org/hotline", "region": "United States",
         "hours": "Mon–Thu 9am–10pm, Fri & Sun 9am–12pm ET"},
        {"name": "Amudim", "description": "Support for abuse and addiction in the Jewish community.",
         "phone": "646-517-0222", "url": "https://amudim.org/", "region": "US & Israel"},
    ],
    "UK": [
        {"name": "National Domestic Abuse Helpline", "description": "Free, 24/7.", "phone": "0808 2000 247",
         "url": "https://www.nationaldahelpline.org.uk/", "region": "United Kingdom", "hours": "24/7"},
        {"name": "Jewish Women's Aid", "description": "Domestic abuse and sexual violence support for Jewish women and girls.",
         "phone": "0808 801 0500", "chat_url": "https://www.jwa.org.uk/webchat", "url": "https://www.jwa.org.uk/",
         "region": "United Kingdom", "hours": "Mon–Thu 9:30am–9:30pm"},
    ],
    "IL": [
        {"name": "Amudim Israel", "description": "Support for abuse and addiction.", "phone": "02-374-0175",
         "url": "https://amudim.org/", "region": "Israel"},
    ],
}

_YOUTH = {
    "US": [
        {"name": "The Trevor Project", "description": "For LGBTQ+ young people. Call, text START to 678-678, or chat, 24/7.",
         "phone": "1-866-488-7386", "sms": "678678", "sms_body": "START", "url": "https://www.thetrevorproject.org/get-help/",
         "region": "United States", "hours": "24/7"},
        {"name": "Teen Line", "description": "Teens talking with trained teens. Text TEEN to 839863.",
         "phone": "800-852-8336", "sms": "839863", "sms_body": "TEEN", "url": "https://didihirsch.org/teenline/",
         "region": "United States", "hours": "Calls 6–10pm PT"},
    ],
    "CA": [
        {"name": "Kids Help Phone", "description": "Call, or text CONNECT to 686868, 24/7.",
         "phone": "1-800-668-6868", "sms": "686868", "sms_body": "CONNECT", "url": "https://kidshelpphone.ca/",
         "region": "Canada", "hours": "24/7"},
    ],
}

_EMERGENCY = {
    "INTL": "your local emergency number",
    "US": "911", "CA": "911", "UK": "999", "IE": "112", "IL": "101 (ambulance) / 100 (police)", "AU": "000",
}

_TZ_REGION = (
    ("Asia/Jerusalem", "IL"), ("Asia/Tel_Aviv", "IL"),
    ("Europe/London", "UK"), ("Europe/Belfast", "UK"), ("Europe/Dublin", "IE"),
    ("Australia/", "AU"),
    ("America/Toronto", "CA"), ("America/Vancouver", "CA"), ("America/Montreal", "CA"),
    ("America/Edmonton", "CA"), ("America/Winnipeg", "CA"), ("America/Halifax", "CA"),
    ("America/Regina", "CA"), ("America/St_Johns", "CA"),
    ("America/Moncton", "CA"), ("America/Whitehorse", "CA"), ("America/Yellowknife", "CA"), ("Canada/", "CA"),
    # United States zones only; other America/* zones (e.g. Sao_Paulo) are international.
    ("America/New_York", "US"), ("America/Chicago", "US"), ("America/Denver", "US"),
    ("America/Los_Angeles", "US"), ("America/Phoenix", "US"), ("America/Anchorage", "US"),
    ("America/Detroit", "US"), ("America/Indiana/", "US"), ("America/Kentucky/", "US"),
    ("America/North_Dakota/", "US"), ("America/Boise", "US"), ("America/Juneau", "US"),
    ("America/Sitka", "US"), ("America/Nome", "US"), ("America/Adak", "US"),
    ("America/Menominee", "US"), ("America/Yakutat", "US"), ("America/Metlakatla", "US"),
    ("America/Puerto_Rico", "US"), ("Pacific/Honolulu", "US"), ("US/", "US"),
)


def region_for(client_tz: Optional[str], accept_language: Optional[str] = None) -> str:
    tz = (client_tz or "").strip()
    for prefix, region in _TZ_REGION:
        if tz.startswith(prefix):
            return region
    lang = (accept_language or "").lower()
    if lang.startswith("he"):
        return "IL"
    if lang.startswith("en-gb"):
        return "UK"
    if lang.startswith(("en-ca", "fr-ca")):
        return "CA"
    if lang.startswith("en-au"):
        return "AU"
    if tz:
        return "INTL"  # a known zone outside the covered regions: never show US-only numbers
    if not lang or lang.startswith(("en-us", "en,", "en;")) or lang == "en":
        return "US"
    return "INTL"


TITLES = {
    "crisis": "You don't have to face this alone",
    "abuse": "Your safety matters",
    "support": "Support is available",
}


def build_card(level: str, region: str, youth: bool = False) -> dict:
    """Assemble the card for one turn. ``level`` ∈ crisis | abuse | support."""
    region = region if region in _GENERAL else "US"
    emergency = _EMERGENCY.get(region, "your local emergency number")
    resources: list[dict] = []
    if level == "abuse":
        resources += _ABUSE.get(region, [])
        resources += _GENERAL[region]
    else:
        resources += _GENERAL[region]
        if youth:
            resources += _YOUTH.get(region, [])
        resources += _JEWISH_TRAUMA.get(region, [])
    if region not in ("US", "INTL") and level == "crisis":
        # Visitors abroad still see the US line (many users are American).
        resources += [r for r in _GENERAL["US"][:1] if r not in resources]
    if region != "INTL":
        resources += [r for r in _GENERAL["INTL"][:1] if r not in resources]
    message = {
        "crisis": f"If you might act on thoughts of ending your life or are in immediate danger, call {emergency} now. "
                  "Talking to someone trained can help, right now, any time.",
        "abuse": f"If you are in danger right now, call {emergency}. What is happening to you is not your fault, "
                 "and confidential help is available, including people who understand the Jewish community.",
        "support": "If things feel heavy, people are ready to listen.",
    }[level]
    return {
        "level": level,
        "title": TITLES[level],
        "message": message,
        "emergency_number": emergency,
        "region": region,
        "resources": resources,
        "version": RESOURCES_VERSION,
    }
