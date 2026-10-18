"""Pure helpers shared by live review evidence (review_context) and agent mode: role families, complaint topics.

Copied from experiments/staged_context (experiment.ROLE_FAMILIES, predictability.TOPICS) so production code does not
import research modules. Keep the two in sync if either changes.
"""

from __future__ import annotations

import math
import re
import unicodedata
import warnings

ROLE_FAMILIES = [
    ("executive_owner", r"\b(ceo|coo|cfo|cto|cio|cmo|founder|co-?founder|owner|president|partner|principal|chief|"
                        r"managing director|managing member|general manager|executive director|entrepreneur|board member)\b"),
    ("project_program_mgmt", r"\b(project|program|programme|pmo|scrum|agile|delivery|portfolio|producer)\b"),
    ("product_mgmt", r"\bproduct (manager|owner|lead|director|management)\b"),
    ("healthcare_wellness", r"\b(therapist|psycholog\w*|counselor|coach|doctor|nurse|health|clinical|medical|"
                            r"physician|dentist|pharmac\w*|psychotherapist)\b"),
    ("software_it_engineering", r"\b(developer|developper|engineer|engineering|software|devops|it\b|programmer|architect|"
                                r"technical|tech|qa|data|web|systems?|network|cto)\b"),
    ("marketing_creative_content", r"\b(marketing|marketer|content|social media|brand|seo|designer|design|creative|"
                                   r"writer|editor|copywriter|communications?|pr\b|media|video|art|artist|photographer|author|illustrator|"
                                   r"creator|presenter|ppc)\b"),
    ("sales_customer", r"\b(sales|account|customer|client|business development|success|support|realtor|"
                       r"real estate)\b"),
    ("operations_admin", r"\b(operations?|admin|administrator|administrative|assistant|coordinator|office|"
                         r"secretary|logistics|supply)\b"),
    ("finance_hr_legal", r"\b(finance|financial|accountant|accounting|controller|hr|human resources|recruit|"
                         r"talent|people|legal|attorney|lawyer|paralegal|compliance|human resources?|rh|recruiter|bookkeeper|billing)\b"),
    ("education_research_analysis", r"\b(teacher|professor|student|research|researcher|lecturer|educator|instructor|"
                                    r"academic|scientist|phd|analyst|trainer)\b"),
    ("consultant_freelance", r"\b(consultant|consulting|freelance|freelancer|self-employed|contractor|advisor)\b"),
    ("general_team_mgmt", r"\b(manager|director|lead|leader|head|supervisor|vp|vice president|gerente|"
                          r"responsable|directeur|directora?)\b"),
]

TOPICS = {  # keyword topics in the cons text; a review "mentions" a topic if any pattern matches
    "complaint_pricing": r"\b(price|pricing|pricey|expensive|cost(ly|s)?|subscription|afford\w*|paid plan|upgrade)\b",
    "complaint_learning_curve": r"\b(learning curve|complicated|complex|overwhelm\w*|confus\w*|not intuitive|hard to (learn|use|navigate)|takes time to learn)\b",
    "complaint_mobile": r"\b(mobile|app on (my )?phone|ios|android|iphone)\b",
    "complaint_integrations": r"\b(integrat\w*|sync\w*|api)\b",
    "complaint_performance": r"\b(slow\w*|lag\w*|crash\w*|load(ing)? time|freez\w*|glitch\w*|bug\w*)\b",
    "complaint_support": r"\b(customer (service|support)|support team|support (is|was)|response time|tickets?)\b",
    "complaint_notifications": r"\b(notification\w*|emails? (are|too)|spam\w*)\b",
    "complaint_reporting": r"\b(report\w*|dashboard\w*|analytics)\b",
    "complaint_customization": r"\b(customi[sz]\w*|flexib\w*|limited|limitation\w*)\b",
}

warnings.filterwarnings("ignore", message="This pattern is interpreted")


def norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"\s+", " ", s).strip()


def clean(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()


def role_family(title: str | None) -> str:
    t = norm_text(title if isinstance(title, str) else "")
    if not t or t in {"n/a", "na", "none", "-", "unknown"}:
        return "unknown"
    for fam, pat in ROLE_FAMILIES:
        if re.search(pat, t):
            return fam
    return "unknown"
