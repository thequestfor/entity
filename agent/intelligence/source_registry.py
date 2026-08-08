"""Licensing, provenance, and network contracts for intelligence sources."""

import re
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit


POLICY_VERSION = "source-contract-v1"
SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,99}$")
ACCESS_CLASSES = {"public", "authenticated", "private"}
AUTHORITY_CLASSES = {
    "official", "intergovernmental", "journalistic", "social",
    "aggregator", "market", "platform", "unspecified"
}
EVIDENCE_ROLES = {
    "observation", "report", "measurement", "forecast", "reference",
    "discovery", "private-context"
}


@dataclass(frozen=True)
class SourcePolicy:
    access_class: str
    authority_class: str
    evidence_role: str
    independence_family: str
    allowed_hosts: tuple[str, ...]
    license_name: str = ""
    license_url: str = ""
    attribution: str = ""
    usage_scope: str = "review-required"
    credentials_required: bool = False
    geographic_coverage: str = "unspecified"
    expected_latency: str = "unspecified"
    caveats: tuple[str, ...] = ()
    retention_days: int | None = None
    policy_version: str = POLICY_VERSION
    reviewed_at: str | None = None

    def snapshot(self):
        return asdict(self)


class ConnectorContractError(ValueError):
    pass


POLICIES = {
    "usgs_earthquakes": SourcePolicy(
        "public","official","observation","usgs-earthquakes",
        ("earthquake.usgs.gov",),"U.S. Government work",
        "https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits",
        "USGS","public-government-data",False,"global","minutes"
    ),
    "nasa_eonet": SourcePolicy(
        "public","official","discovery","nasa-eonet",
        ("eonet.gsfc.nasa.gov",),"NASA Open Data",
        "https://science.nasa.gov/open-science/open-data/","NASA EONET",
        "public-government-data",False,"global","hours",
        ("EONET aggregates event information from provider sources.",)
    ),
    "nasa_firms_wildfires": SourcePolicy(
        "authenticated","official","observation","nasa-firms",
        ("firms.modaps.eosdis.nasa.gov",),"NASA FIRMS terms",
        "https://firms.modaps.eosdis.nasa.gov/content/academy/data_api/firms_api_use.html",
        "NASA FIRMS","attribution-required",True,"global","near-real-time",
        ("Satellite fire detections are not confirmed wildfire perimeters.",)
    ),
    "gdacs": SourcePolicy(
        "public","intergovernmental","observation","gdacs",
        ("www.gdacs.org",),"GDACS terms","https://www.gdacs.org/About/terms.aspx",
        "GDACS","attribution-required",False,"global","minutes"
    ),
    "reliefweb": SourcePolicy(
        "authenticated","intergovernmental","report","reliefweb",
        ("api.reliefweb.int","reliefweb.int"),"ReliefWeb API terms",
        "https://apidoc.reliefweb.int/","ReliefWeb","attribution-required",
        True,"global","minutes",
        ("Reports retain the identity of their original reporting organization.",)
    ),
    "who_outbreaks": SourcePolicy(
        "public","intergovernmental","report","who-outbreaks",
        ("www.who.int",),"WHO terms","https://www.who.int/about/policies/publishing/copyright",
        "World Health Organization","attribution-required",False,"global","days"
    ),
    "nws_alerts": SourcePolicy(
        "public","official","observation","nws-alerts",
        ("api.weather.gov",),"U.S. Government work","https://www.weather.gov/disclaimer",
        "National Weather Service","public-government-data",False,
        "United States and territories","minutes"
    ),
    "cisa_known_exploited_vulnerabilities": SourcePolicy(
        "public","official","reference","cisa-kev",("www.cisa.gov",),
        "U.S. Government work","https://www.cisa.gov/about/website-policies",
        "CISA","public-government-data",False,"global products","days"
    ),
    "github_security_advisories": SourcePolicy(
        "public","platform","report","github-advisories",("api.github.com",),
        "GitHub API terms","https://docs.github.com/en/site-policy/github-terms/github-terms-of-service",
        "GitHub Advisory Database","terms-governed",False,"global software","minutes"
    ),
    "noaa_space_weather_alerts": SourcePolicy(
        "public","official","observation","noaa-swpc",("services.swpc.noaa.gov",),
        "U.S. Government work","https://www.noaa.gov/disclaimer",
        "NOAA Space Weather Prediction Center","public-government-data",False,"global","minutes"
    ),
    "world_bank_indicators": SourcePolicy(
        "public","intergovernmental","measurement","world-bank",("api.worldbank.org",),
        "World Bank Data Terms","https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets",
        "World Bank","attribution-required",False,"global","annual-to-quarterly"
    ),
    "fred_economic_indicators": SourcePolicy(
        "authenticated","official","measurement","fred",("api.stlouisfed.org",),
        "FRED API terms","https://fred.stlouisfed.org/docs/api/terms_of_use.html",
        "Federal Reserve Bank of St. Louis","terms-governed",True,"configured series","varies"
    ),
    "gdelt": SourcePolicy(
        "public","aggregator","discovery","gdelt",("api.gdeltproject.org",),
        "GDELT data","https://www.gdeltproject.org/","GDELT Project",
        "public-data",False,"global","minutes",
        ("Indexed reporting is not independent verification by GDELT.",)
    ),
    "telegram_public": SourcePolicy(
        "authenticated","social","report","telegram-public",("api.telegram.org","t.me"),
        "Telegram API terms","https://core.telegram.org/api/terms","Original channel",
        "terms-governed",True,"configured public channels","minutes",
        ("Public posts are claims and may be edited or deleted.",)
    ),
    "x_public": SourcePolicy(
        "authenticated","social","report","x-public",("api.x.com","api.twitter.com"),
        "X Developer Agreement","https://developer.x.com/en/developer-terms/agreement-and-policy",
        "Original account","terms-governed",True,"configured accounts and queries","minutes",
        ("Public posts are claims, not authoritative observations by default.",)
    ),
    "polymarket": SourcePolicy(
        "public","market","forecast","polymarket",("gamma-api.polymarket.com",),
        "Polymarket terms","https://polymarket.com/tos","Polymarket",
        "terms-governed",False,"listed markets","minutes",
        ("Market probabilities are forecast signals and never factual corroboration.",)
    ),
    "gmail": SourcePolicy(
        "private","platform","private-context","private-gmail",("gmail.googleapis.com","oauth2.googleapis.com"),
        "Google API terms","https://developers.google.com/terms","Private user data",
        "private-local-only",True,"user mailbox","minutes"
    ),
    "outlook_mail": SourcePolicy(
        "private","platform","private-context","private-outlook",("graph.microsoft.com","login.microsoftonline.com"),
        "Microsoft API terms","https://learn.microsoft.com/en-us/legal/microsoft-apis/terms-of-use",
        "Private user data","private-local-only",True,"user mailbox","minutes"
    )
}


KIND_DEFAULTS = {
    "news": ("public","journalistic","report","publisher"),
    "test": ("public","unspecified","report","test-fixture"),
    "public_api": ("public","unspecified","report","unspecified"),
}


def policy_for(connector):
    explicit = getattr(connector, "source_policy", None)
    if isinstance(explicit, SourcePolicy):
        return explicit
    if connector.source_id in POLICIES:
        return POLICIES[connector.source_id]
    access, authority, role, family = KIND_DEFAULTS.get(
        str(getattr(connector, "kind", "public_api")),
        ("public","unspecified","report",str(connector.source_id))
    )
    host = (urlsplit(str(getattr(connector, "base_url", ""))).hostname or "").lower()
    return SourcePolicy(
        access,authority,role,f"{family}:{connector.source_id}",
        (host,) if host else (),caveats=("Policy requires human review before redistribution.",)
    )


def validate_connector_contract(connector, policy=None):
    violations = []
    source_id = str(getattr(connector, "source_id", ""))
    if not SOURCE_ID.fullmatch(source_id):
        violations.append("source_id must be stable lowercase ASCII")
    for name in ("name","kind","base_url","poll_seconds","credibility","enabled"):
        if not hasattr(connector, name):
            violations.append(f"missing connector attribute: {name}")
    if not callable(getattr(connector, "poll", None)):
        violations.append("connector must implement poll(cursor)")
    policy = policy or policy_for(connector)
    if policy.access_class not in ACCESS_CLASSES:
        violations.append("invalid access_class")
    if policy.authority_class not in AUTHORITY_CLASSES:
        violations.append("invalid authority_class")
    if policy.evidence_role not in EVIDENCE_ROLES:
        violations.append("invalid evidence_role")
    base_url = str(getattr(connector, "base_url", ""))
    if base_url:
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" and not (parsed.hostname or "").endswith(".test"):
            violations.append("remote source base_url must use HTTPS")
        if parsed.username or parsed.password:
            violations.append("credentials must not be embedded in base_url")
        if policy.allowed_hosts and not _host_allowed(parsed.hostname, policy.allowed_hosts):
            violations.append("base_url host is outside the source allowlist")
    if violations:
        raise ConnectorContractError(f"{source_id or 'unknown'}: " + "; ".join(violations))
    return policy


def validate_connector_url(connector, url):
    policy = validate_connector_contract(connector)
    parsed = urlsplit(str(url))
    if parsed.scheme != "https" and not (parsed.hostname or "").endswith(".test"):
        raise ConnectorContractError("connector request URL must use HTTPS")
    if parsed.username or parsed.password:
        raise ConnectorContractError("connector request URL contains credentials")
    if policy.allowed_hosts and not _host_allowed(parsed.hostname, policy.allowed_hosts):
        raise ConnectorContractError(
            f"{connector.source_id}: request host is outside the source allowlist"
        )
    return str(url)


def _host_allowed(host, allowed_hosts):
    host = str(host or "").lower().rstrip(".")
    return any(
        host == allowed.lower().rstrip(".")
        or host.endswith("." + allowed.lower().rstrip("."))
        for allowed in allowed_hosts
    )
