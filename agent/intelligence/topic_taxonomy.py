"""Stable topic keys used for sparse, hierarchical reliability cells."""

TOPIC_ALIASES = {
    "eq": "earthquake", "seismic": "earthquake",
    "severe-storms": "weather", "weather-alert": "weather",
    "space-weather": "space-weather", "wildfires": "wildfire",
    "floods": "flood", "drought": "drought",
    "known-exploited-vulnerability": "cybersecurity",
    "software-vulnerability": "cybersecurity",
    "civil-unrest": "conflict", "humanitarian": "humanitarian",
    "disease-outbreak": "public-health", "traditional-news": "general-news",
    "social-signal": "social-signal", "economic-indicator": "economics",
    "finance": "economics", "prediction-market": "prediction-market"
}


def normalize_topic(value):
    topic = str(value or "general").strip().lower().replace("_", "-")
    return TOPIC_ALIASES.get(topic, topic or "general")[:80]
