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
            event_id = result.get("id")

            if not event_id:
                return (
                    "Calendar event may not have been created. Google did "
                    "not return an event id."
                )

            verified = self.client.get_event(event_id)
        except RuntimeError as exc:
            return f"Calendar setup needed: {exc}"
        except Exception as exc:
            return f"Calendar event creation failed: {exc}"

        if not verified.get("id"):
            return (
                "Calendar event may not have been created. Entity could not "
                "verify the event after writing it."
            )

        link = verified.get("htmlLink") or result.get("htmlLink")
        details = self._format_details(draft, verified)

        if link:
            return f"Calendar event created: {details}. {link}"

        return f"Calendar event created: {details}."

    def _format_details(self, draft, event):
        recurrence = "recurring weekly" if draft.recurrence else "one time"
        start = draft.start.strftime("%A, %B %d at %-I:%M %p")
        event_id = event.get("id", "unknown id")

        location = ""

        if draft.location:
            location = f" at {draft.location}"

        return (
            f"{draft.summary}, {recurrence}, {start}{location}, "
            f"calendar {self.client.calendar_id}, event id {event_id}"
        )
