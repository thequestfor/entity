def think(text):
    text = text.lower().strip()

    if "hello" in text:
        return "WELCOME_HOME"

    if "good morning" in text:
        return "GOOD_MORNING"

    if "monitor" in text or "watch" in text:
        return "MONITORING"

    if "system" in text or "online" in text:
        return "SYSTEMS_ONLINE"

    return "IDENTIFY"