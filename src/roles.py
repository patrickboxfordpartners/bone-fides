"""Role bucketing: raw role text -> filter bucket.

Canonical implementation. The two API twins (ui/server.py,
vercel-app/api/search.py) carry inline copies because the deployed
functions must stay dependency-free; tests/test_role_bucket.py locks all
copies together. Keep them in sync.
"""
import re

_ROLE_CHEF = {"chef", "chefs", "cook", "cooks", "culinary", "cuisine", "kitchen", "pizzaiolo", "commis"}
_ROLE_EXEC = {"executive", "exec", "corporate"}
_ROLE_PASTRY = {"pastry", "baker", "bakery", "baking", "chocolatier", "dessert", "chocolate"}
_ROLE_SOUS = {"sous"}
_ROLE_OWNER = {"owner", "owners", "founder", "founders", "founding", "proprietor", "proprietors",
               "restaurateur", "restaurateurs", "partner", "partners", "operator", "operators"}
_ROLE_BAR = {"bartender", "barman", "barback", "bar"}

BUCKETS = ("chef", "executive chef", "pastry", "sous", "owner", "bartender", "other")


def role_bucket(role):
    """Raw role text -> dossier filter bucket. Token-based synonym fold, same
    discipline as norm_venue: case-fold and split on separators, never guess
    from substrings (a "bar manager" is not a "bar" and a "chocolate martini"
    must not make anyone a pastry chef). Domain beats seniority — an
    "executive pastry chef" is pastry, an "executive sous chef" is sous;
    ownership reads as chef first ("chef-owner" cooks). Anything else stays
    other (managers, sommeliers, junk rows)."""
    s = re.sub(r"[^a-z0-9&\s'-]", " ", (role or "").lower())
    toks = set(re.split(r"[\s/&,'\-]+", s)) - {""}
    if not toks:
        return "other"
    if toks & _ROLE_SOUS:
        return "sous"
    if toks & _ROLE_PASTRY:
        return "pastry"
    if (toks & _ROLE_EXEC) and (toks & _ROLE_CHEF):
        return "executive chef"
    if toks & _ROLE_CHEF:
        return "chef"
    if toks & _ROLE_BAR:
        return "bartender"
    if toks & _ROLE_OWNER:
        return "owner"
    return "other"
