from agent.calendar import GoogleCalendarClient


class CalendarActuator:
    action_type = "calendar"

    def __init__(self, client=None):
        self.client = client or GoogleCalendarClient()

    def can_handle(self, action):
        return action.type == self.action_type

    def execute(self, action):
        operation = action.payload.get("operation")

        if operation != "create_event":
            return "Calendar operation not supported."

        draft = action.payload.get("draft")

        if draft is None:
            return "Calendar event was not understood."

        try:
            result = self.client.insert_event(draft)
        except RuntimeError as exc:
            return f"Calendar setup needed: {exc}"

        link = result.get("htmlLink")

        if link:
            return f"Calendar event created: {draft.summary}. {link}"

        return f"Calendar event created: {draft.summary}."
