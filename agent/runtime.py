import os
import re
import time
from datetime import datetime, timedelta

from agent.actuators import (
    CalendarActuator,
    DiagnosticsActuator,
    NotifyActuator,
    SpeechActuator
)
from agent.attention import ImportancePolicy
from agent.awareness import AwarenessLoop
from agent.behavior import BehaviorFeedbackPolicy
from agent.briefing import TodayBriefing
from agent.calendar import CalendarIntentExtractor
from agent.confirmations import ConfirmationStore
from agent.event_bus import EventBus
from agent.events import Action
from agent.health import StartupHealthCheck
from agent.learning import LearningPolicy
from agent.memory.research import ResearchMemoryIngestor
from agent.math_tools import ArithmeticHandler
from agent.observers import (
    AudioObserver,
    AutonomyObserver,
    CalendarObserver,
    NtfyObserver,
    SchedulerObserver
)
from agent.policy import Policy
from agent.planner import AgentPlanner
from agent.presence import PresenceState
from agent.reflection import PeriodicReflection
from agent.reminders import ReminderIntentExtractor
from agent.research import ResearchTool
from agent.routes import RoutePlanner
from agent.weather import WeatherTool


class EntityRuntime:
    def __init__(
        self,
        brain=None,
        awareness=None,
        audio_observer=None,
        scheduler_observer=None,
        importance_policy=None,
        calendar_extractor=None,
        reminder_extractor=None,
        arithmetic_handler=None,
        route_planner=None,
        weather_tool=None,
        startup_health=None,
        today_briefing=None,
        presence=None,
        learning_policy=None,
        research_tool=None,
        research_memory_ingestor=None,
        behavior_feedback_policy=None,
        planner=None,
        confirmation_store=None,
        reflection=None,
        observers=None,
        actuators=None,
        policy=None
    ):
        self.brain = brain or self._default_brain()
        self.awareness = awareness or AwarenessLoop(
            on_interrupt=self.publish_event
        )
        self.event_bus = EventBus()
        self.scheduler_observer = (
            scheduler_observer or SchedulerObserver()
        )
        self.task_store = self.scheduler_observer.store
        self.importance_policy = importance_policy or ImportancePolicy()
        self.calendar_extractor = calendar_extractor or CalendarIntentExtractor()
        self.reminder_extractor = reminder_extractor or ReminderIntentExtractor()
        self.arithmetic_handler = arithmetic_handler or ArithmeticHandler()
        self.route_planner = route_planner or RoutePlanner()
        self.weather_tool = weather_tool or WeatherTool()
        self.startup_health = startup_health or StartupHealthCheck()
        self.today_briefing = today_briefing or TodayBriefing()
        self.presence = presence or PresenceState()
        self.learning_policy = learning_policy or LearningPolicy()
        self.research_tool = research_tool or ResearchTool()
        self.research_memory_ingestor = (
            research_memory_ingestor or ResearchMemoryIngestor()
        )
        self.behavior_feedback_policy = (
            behavior_feedback_policy or BehaviorFeedbackPolicy()
        )
        self.planner = planner or AgentPlanner()
        self.confirmation_store = (
            confirmation_store or ConfirmationStore(
                ttl_seconds=self._confirmation_ttl_seconds()
            )
        )
        self.reflection = reflection or PeriodicReflection(
            store=self.task_store
        )
        self.last_research_result = None
        self.recent_actions = []
        self.recent_responses = []
        if observers is None:
            observers = [
                self.scheduler_observer,
                AutonomyObserver(
                    store=self.task_store,
                    health_check=self.startup_health,
                    confirmation_store=self.confirmation_store,
                    reflection=self.reflection
                ),
                CalendarObserver(),
                NtfyObserver(),
                audio_observer or AudioObserver()
            ]

        if actuators is None:
            actuators = [
                CalendarActuator(),
                DiagnosticsActuator(),
                NotifyActuator(),
                SpeechActuator()
            ]

        self.observers = observers
        self.actuators = actuators
        self.policy = policy or Policy()

    def run(self):
        self.start()

        try:
            while True:
                event = self.event_bus.next_event()

                if event:
                    self.handle_event(event)

                self.event_bus.task_done()

        finally:
            self.stop()

    def start(self):
        self.awareness.start()

        for observer in self.observers:
            observer.start(self.event_bus)

        self.execute(
            Action(
                type="speak",
                payload={
                    "text": "Systems online"
                }
            )
        )
        self._run_startup_health_check()

    def stop(self):
        self.awareness.stop()

        for observer in self.observers:
            observer.stop()

    def publish_event(self, event):
        self.event_bus.publish(event)

    def handle_event(self, event):
        self._record_event(event)
        self._learn_from_event(event)

        if event.type == "user_speech":
            return self.handle_text_input(event, channel="voice")

        if event.type == "remote_message":
            return self.handle_text_input(event, channel="remote")

        if event.type == "reminder":
            return self.handle_reminder(event)

        if event.type == "calendar_event_upcoming":
            return self.handle_calendar_event_upcoming(event)

        if event.type in {"autonomy_check", "autonomous_goal"}:
            return self.handle_autonomous_goal(event)

        if event.message:
            return self.handle_observed_event(event)

        return None

    def _default_brain(self):
        from agent.brain import Brain

        return Brain()

    def handle_user_speech(self, event):
        return self.handle_text_input(event, channel="voice")

    def handle_text_input(self, event, channel="voice"):
        command = event.payload.get("text", "")

        if not command:
            return None

        if channel == "remote":
            print("Remote:", command)
        else:
            print("Heard:", command)

        self.presence.update(
            interaction_channel=channel,
            seen=(channel == "voice")
        )

        self.awareness.record_input(command)

        runtime_response = self._handle_runtime_command(
            command,
            source=channel
        )

        if runtime_response:
            self.awareness.record_response(runtime_response)
            self._record_response(runtime_response, source=channel)
            self._reply(runtime_response, channel)
            print(runtime_response)
            return runtime_response

        response_stream = self.brain.respond_stream(
            command,
            self.awareness.snapshot(),
            on_escalation=lambda message: self._reply(message, channel)
        )

        if channel == "remote":
            response = "".join(response_stream)
            self._reply(response, channel)
        else:
            action = Action(
                type="speak",
                payload={
                    "stream": response_stream
                }
            )

            response = self.execute(action)

        self.awareness.record_response(response)
        self._record_response(response, source=channel)

        print(response)

        return response

    def handle_reminder(self, event):
        message = event.message

        if not message:
            return None

        decision = self.importance_policy.evaluate(
            event,
            awareness_state=self.awareness.snapshot()
        )

        return self._deliver_alert(
            message,
            title="Entity reminder",
            priority="high",
            force_notify=True
        )

    def handle_calendar_event_upcoming(self, event):
        message = event.message

        try:
            route_message = self.route_planner.departure_advice(event.payload)
        except Exception as exc:
            print("Route planning failed:", exc)
            route_message = None

        if route_message:
            message = route_message

        if not message:
            return None

        self._deliver_alert(
            message,
            title="Entity departure alert",
            priority="high"
        )

        return message

    def handle_autonomous_goal(self, event):
        message = event.message

        goal = event.payload.get("goal") or {}
        goal_name = goal.get("name", "unknown")

        if goal_name == "prepare_today_briefing":
            message = self.today_briefing.build()
        elif goal_name == "review_failed_tool":
            message = self._autonomous_failed_tool_review(message)
        elif goal_name == "suggest_memory_review":
            message = self._autonomous_memory_review_suggestion(message)
        elif goal_name == "periodic_reflection":
            return self._run_periodic_reflection()
        elif not message:
            return None

        if bool(goal.get("store_reflection")) and message:
            self.task_store.add_memory(
                kind="reflection",
                content=message,
                source="autonomy",
                importance=min(10, max(1, event.priority)),
                metadata={
                    "goal": goal_name,
                    "reason": goal.get("reason", "")
                }
            )

        return self._deliver_autonomous_goal_message(
            message,
            title="Entity autonomous goal",
            priority="urgent" if event.priority >= 8 else "high",
            notify=event.priority >= 8 or bool(goal.get("notify")),
            speak=bool(goal.get("speak"))
        )

    def _run_periodic_reflection(self):
        result = self.reflection.reflect()

        if not result:
            return "Periodic reflection completed without storing a new memory."

        return f"Periodic reflection stored: {result['content']}"

    def _autonomous_failed_tool_review(self, fallback_message):
        decisions = self.task_store.recent_planner_decisions(limit=10)
        failed = [
            item
            for item in decisions
            if item.get("outcome") in {"fallback_used", "canceled", "failed"}
        ]

        if not failed:
            return fallback_message or "No recent failed tool decision found."

        decision = failed[0]
        response = decision.get("response") or "No response recorded."

        return (
            "Recent tool review: "
            f"intent {decision.get('intent', 'unknown')} ended as "
            f"{decision.get('outcome', 'unknown')}. "
            f"Last response: {response}"
        )

    def _autonomous_memory_review_suggestion(self, fallback_message):
        memories = self.task_store.list_memories(limit=5)

        if not memories:
            return fallback_message or "No memories are ready for review."

        top = memories[0]

        return (
            "Memory review suggestion: "
            f"{top['kind']} from {top['source']} says {top['content']}"
        )

    def _deliver_autonomous_goal_message(
        self,
        text,
        title="Entity autonomous goal",
        priority="high",
        notify=False,
        speak=False
    ):
        delivered = None

        if speak and self.presence.should_speak():
            delivered = self.execute(
                Action(
                    type="speak",
                    payload={
                        "text": text
                    }
                )
            )

        if notify:
            delivered = self.execute(
                Action(
                    type="notify",
                    payload={
                        "title": title,
                        "text": text,
                        "priority": priority
                    }
                )
            )

        return delivered or text

    def handle_observed_event(self, event):
        decision = self.importance_policy.evaluate(
            event,
            awareness_state=self.awareness.snapshot()
        )

        if decision.should_notify:
            return self._deliver_alert(
                event.message,
                title="Entity alert",
                priority="high"
            )

        if decision.decision in {"act", "ask"}:
            return self.execute(
                Action(
                    type="speak",
                    payload={
                        "text": event.message
                    }
                )
            )

        return None

    def _alert_if_no_language_model(self):
        decision = self.importance_policy.model_health_decision()

        if not decision.should_notify:
            return None

        message = decision.reason
        self._deliver_alert(
            message,
            title="Entity system alert",
            priority="urgent",
            force_notify=True
        )

        return message

    def _record_event(self, event):
        try:
            self.task_store.add_event(event)
        except Exception as exc:
            print("Failed to record event:", exc)

    def _learn_from_event(self, event):
        try:
            self.learning_policy.observe_event(
                event,
                awareness_state=self.awareness.snapshot(),
                presence_state=self.presence.snapshot()
            )
        except Exception as exc:
            print("Learning from event failed:", exc)

    def _reply(self, text, channel):
        if not text:
            return None

        if channel == "remote":
            return self.execute(
                Action(
                    type="notify",
                    payload={
                        "title": "Entity",
                        "text": text
                    }
                )
            )

        return self.execute(
            Action(
                type="speak",
                payload={
                    "text": text
                }
            )
        )

    def _deliver_alert(
        self,
        text,
        title="Entity alert",
        priority="high",
        force_notify=False
    ):
        if not text:
            return None

        delivered = None
        should_speak = self.presence.should_speak()
        should_notify = (
            force_notify
            or self.presence.should_notify()
            or not should_speak
        )

        if should_speak:
            delivered = self.execute(
                Action(
                    type="speak",
                    payload={
                        "text": text
                    }
                )
            )

        if should_notify:
            delivered = self.execute(
                Action(
                    type="notify",
                    payload={
                        "title": title,
                        "text": text,
                        "priority": priority
                    }
                )
            )

        return delivered or text

    def _handle_runtime_command(self, command, source="voice"):
        active_work_response = self._handle_active_work_command(command)

        if active_work_response:
            return active_work_response

        audit_response = self._handle_decision_audit_command(command)

        if audit_response:
            return audit_response

        confirmation_response = self._handle_confirmation_command(
            command,
            source=source
        )

        if confirmation_response:
            return confirmation_response

        planned_response = self._handle_planned_command(
            command,
            source=source
        )

        if planned_response:
            return planned_response

        fallback_response = self._handle_runtime_command_fallback(
            command,
            source=source
        )

        if fallback_response:
            self._record_fallback_decision(
                command,
                source=source,
                response=fallback_response
            )

        return fallback_response

    def _handle_runtime_command_fallback(self, command, source="voice"):
        if self._is_diagnostics_command(command):
            return self._run_diagnostics()

        voice_response = self._handle_voice_command(command)

        if voice_response:
            return voice_response

        presence_response = self._handle_presence_command(command)

        if presence_response:
            return presence_response

        feedback_response = self._handle_behavior_feedback_command(
            command,
            source=source
        )

        if feedback_response:
            return feedback_response

        math_response = self.arithmetic_handler.answer(command)

        if math_response:
            return math_response

        briefing_response = self._handle_briefing_command(command)

        if briefing_response:
            return briefing_response

        weather_response = self._handle_weather_command(command)

        if weather_response:
            return weather_response

        research_memory_response = self._handle_research_memory_command(
            command,
            source=source
        )

        if research_memory_response:
            return research_memory_response

        research_response = self._handle_research_command(command)

        if research_response:
            return research_response

        calendar_response = self._handle_calendar_command(
            command,
            channel=source
        )

        if calendar_response:
            return calendar_response

        return self._create_reminder_from_command(command, source=source)

    def _handle_planned_command(self, command, source="voice"):
        plan = self.planner.plan(
            command,
            awareness_state=self.awareness.snapshot(),
            presence_state=self.presence.snapshot(),
            capability_context=self._planner_capability_context(),
            recent_actions=self.recent_actions,
            recent_responses=self.recent_responses,
            recent_decisions=self.task_store.recent_planner_decisions(
                limit=5
            ),
            on_escalation=lambda message: self._reply(message, source)
        )

        if not plan:
            return None

        responses = []
        needs_confirmation = self._plan_needs_confirmation(plan)
        decision_id = self._record_plan_decision(
            plan,
            command,
            source=source,
            confirmation_required=needs_confirmation
        )

        if needs_confirmation:
            pending = self.confirmation_store.create(
                plan,
                original_text=command,
                source=source,
                decision_id=decision_id
            )
            prompt = self._confirmation_prompt(plan, pending)
            self.task_store.update_planner_decision(
                decision_id,
                outcome="pending_confirmation",
                response=prompt,
                metadata={
                    "pending_confirmation_id": pending["id"]
                }
            )
            return prompt

        step_results = []
        for step in plan.steps:
            response = self._execute_plan_step(
                step,
                command,
                source=source
            )
            step_results.append(
                {
                    "tool": step.tool,
                    "result": response
                }
            )

            if response:
                responses.append(response)
                self._notify_significant_plan_step(
                    step,
                    command,
                    response,
                    source=source
                )

        if responses:
            final_response = " ".join(responses)
        else:
            final_response = plan.response or None

        self.task_store.update_planner_decision(
            decision_id,
            outcome="executed",
            response=final_response or "",
            metadata={
                "step_results": step_results
            }
        )

        return final_response

    def _planner_capability_context(self):
        return {
            "tools": self._planner_tools(),
            "actuators": [
                {
                    "name": actuator.__class__.__name__,
                    "action_type": getattr(actuator, "action_type", None),
                    "available": self._component_available(actuator)
                }
                for actuator in self.actuators
            ],
            "observers": [
                {
                    "name": observer.__class__.__name__,
                    "available": self._component_available(observer)
                }
                for observer in self.observers
            ]
        }

    def _planner_tools(self):
        return [
            {
                "name": "answer",
                "description": "Reply with text only when no tool is needed."
            },
            {
                "name": "ask",
                "description": "Ask a follow-up question when required details are missing."
            },
            {
                "name": "diagnostics",
                "description": "Run health checks for configured Entity services."
            },
            {
                "name": "set_presence",
                "description": "Update Ben's location or availability."
            },
            {
                "name": "set_voice",
                "description": "Switch TTS voice; args.voice must be kokoro or sam."
            },
            {
                "name": "arithmetic",
                "description": "Calculate a simple arithmetic expression exactly."
            },
            {
                "name": "briefing",
                "description": "Build today's schedule and status briefing."
            },
            {
                "name": "weather",
                "description": (
                    "Look up current weather and today's forecast. "
                    "args.location is optional when a default location is "
                    "configured. args.question should preserve what the user "
                    "wants to know, such as whether to bring a jacket."
                )
            },
            {
                "name": "notify",
                "description": "Send args.text through the notification channel."
            },
            {
                "name": "research",
                "description": (
                    "Search the internet. args.query is the query. Set "
                    "args.notify true when the user wants the result sent "
                    "after completion."
                )
            },
            {
                "name": "research_and_remember",
                "description": (
                    "Search the internet and store sourced useful facts. Set "
                    "args.notify true when the user wants the result sent "
                    "after completion."
                )
            },
            {
                "name": "remember_last_research",
                "description": "Store the most recent research result."
            },
            {
                "name": "create_calendar_event",
                "description": "Schedule a Google Calendar event from the user's text."
            },
            {
                "name": "create_reminder",
                "description": "Create a reminder from the user's text."
            },
            {
                "name": "store_memory",
                "description": "Store explicit memory with args.kind and args.content."
            },
            {
                "name": "behavior_feedback",
                "description": "Learn explicit feedback about Entity's behavior."
            }
        ]

    def _component_available(self, component):
        available = getattr(component, "available", None)

        if not callable(available):
            return None

        try:
            return bool(available())
        except Exception:
            return False

    def _notify_significant_plan_step(
        self,
        step,
        command,
        response,
        source="voice"
    ):
        if not self._should_notify_significant_actions(source, response):
            return None

        significant_tools = {
            "set_presence": "presence updated",
            "set_voice": "voice changed",
            "research_and_remember": "research memory stored",
            "remember_last_research": "research memory stored",
            "store_memory": "memory stored",
            "behavior_feedback": "behavior feedback learned"
        }
        label = significant_tools.get(step.tool)

        if not label:
            return None

        return self._send_notification(
            f"Entity {label}. Request: {command}. Result: {response}",
            title="Entity action completed",
            priority="default"
        )

    def _notify_significant_action(
        self,
        label,
        command,
        response,
        source="voice",
        priority="default"
    ):
        if not self._should_notify_significant_actions(source, response):
            return None

        return self._send_notification(
            f"Entity {label}. Request: {command}. Result: {response}",
            title="Entity action completed",
            priority=priority
        )

    def _should_notify_significant_actions(self, source, response):
        if source == "remote":
            return False

        if not response:
            return False

        return self._env_bool(
            "ENTITY_NOTIFY_SIGNIFICANT_ACTIONS",
            default=True
        )

    def _env_bool(self, name, default=False):
        raw = os.getenv(name)

        if raw is None:
            return default

        return raw.lower().strip() in {
            "1",
            "true",
            "yes",
            "on"
        }

    def _handle_confirmation_command(self, command, source="voice"):
        normalized = command.lower().strip()
        pending = self.confirmation_store.current()

        if not pending:
            return None

        if normalized in {
            "yes",
            "yeah",
            "yep",
            "confirm",
            "confirmed",
            "do it",
            "go ahead",
            "proceed"
        }:
            return self._confirm_pending_plan(pending, source=source)

        if normalized in {
            "no",
            "nope",
            "cancel",
            "never mind",
            "nevermind",
            "stop"
        }:
            self.confirmation_store.clear()
            decision_id = pending.get("decision_id")

            if decision_id:
                self.task_store.update_planner_decision(
                    decision_id,
                    outcome="canceled",
                    response="Canceled the pending action."
                )

            return "Canceled the pending action."

        change = self._confirmation_change_text(command)

        if change:
            original = pending.get("original_text", "")
            decision_id = pending.get("decision_id")
            self.confirmation_store.clear()

            if decision_id:
                self.task_store.update_planner_decision(
                    decision_id,
                    outcome="revised",
                    response=f"Change requested: {change}",
                    metadata={
                        "change_request": change
                    }
                )

            revised = f"{original}. Change request: {change}"
            return self._handle_planned_command(revised, source=source)

        return None

    def _confirm_pending_plan(self, pending, source="voice"):
        from agent.planner import AgentPlan

        plan = AgentPlan.from_dict(pending.get("plan") or {})
        original_text = pending.get("original_text", "")
        decision_id = pending.get("decision_id")
        self.confirmation_store.clear()
        responses = []
        step_results = []

        for step in plan.steps:
            response = self._execute_plan_step(
                step,
                original_text,
                source=source
            )
            step_results.append(
                {
                    "tool": step.tool,
                    "result": response
                }
            )

            if response:
                responses.append(response)
                self._notify_significant_plan_step(
                    step,
                    original_text,
                    response,
                    source=source
                )

        if responses:
            final_response = " ".join(responses)
        else:
            final_response = "Confirmed."

        if decision_id:
            self.task_store.update_planner_decision(
                decision_id,
                outcome="confirmed_executed",
                response=final_response,
                metadata={
                    "step_results": step_results
                }
            )

        return final_response

    def _handle_decision_audit_command(self, command):
        normalized = command.lower().strip()

        if normalized not in {
            "why did you do that",
            "what did you just decide",
            "show last decision",
            "last decision",
            "planner audit",
            "decision audit"
        }:
            return None

        decision = self.task_store.last_planner_decision()

        if not decision:
            return "No planner decisions have been recorded yet."

        return self._format_planner_decision(decision)

    def _format_planner_decision(self, decision):
        tools = [
            item.get("tool", "unknown")
            for item in decision.get("tools", [])
            if isinstance(item, dict)
        ]
        tool_text = ", ".join(tools) if tools else "none"
        reason = decision.get("reason") or "No reason recorded."

        return (
            f"Last decision: intent {decision['intent']}, "
            f"confidence {decision['confidence']:.2f}, "
            f"tools {tool_text}, outcome {decision['outcome']}. "
            f"Reason: {reason}"
        )

    def _confirmation_change_text(self, command):
        patterns = [
            r"^\s*change it to\s+(.+)$",
            r"^\s*change that to\s+(.+)$",
            r"^\s*instead\s+(.+)$",
            r"^\s*make it\s+(.+)$"
        ]

        for pattern in patterns:
            match = re.search(pattern, command, re.IGNORECASE)

            if match:
                return match.group(1).strip()

        return ""

    def _plan_needs_confirmation(self, plan):
        if any(step.requires_confirmation for step in plan.steps):
            return True

        confirmable_tools = {
            "set_presence",
            "set_voice",
            "research_and_remember",
            "remember_last_research",
            "notify",
            "create_calendar_event",
            "create_reminder",
            "store_memory",
            "behavior_feedback"
        }

        if plan.confidence < 0.65:
            return any(
                step.tool in confirmable_tools
                for step in plan.steps
            )

        return False

    def _confirmation_prompt(self, plan, pending):
        summary = plan.response or self._plan_summary(plan)

        if not summary:
            summary = "I have an action ready that needs confirmation."

        seconds = max(1, pending["expires_at"] - time.time())
        minutes = max(1, int((seconds + 59) // 60))

        return (
            f"{summary} Confirm? You can say yes, no, or change it. "
            f"This expires in about {minutes} minutes."
        )

    def _plan_summary(self, plan):
        tools = [
            step.tool.replace("_", " ")
            for step in plan.steps
        ]

        if not tools:
            return ""

        return "I plan to " + ", then ".join(tools) + "."

    def _record_plan_decision(
        self,
        plan,
        command,
        source="voice",
        confirmation_required=False
    ):
        return self.task_store.add_planner_decision(
            input_text=command,
            channel=source,
            intent=plan.intent,
            confidence=plan.confidence,
            tools=[
                {
                    "tool": step.tool,
                    "args": step.args,
                    "requires_confirmation": step.requires_confirmation
                }
                for step in plan.steps
            ],
            reason=plan.reason,
            confirmation_required=confirmation_required,
            outcome="planned",
            response=plan.response
        )

    def _record_fallback_decision(self, command, source="voice", response=""):
        return self.task_store.add_planner_decision(
            input_text=command,
            channel=source,
            intent="fallback",
            confidence=0,
            tools=[],
            reason="Planner unavailable or did not return a usable plan.",
            confirmation_required=False,
            outcome="fallback_used",
            response=response
        )

    def _execute_plan_step(self, step, command, source="voice"):
        tool = step.tool
        args = step.args or {}

        if tool in {"answer", "ask"}:
            return args.get("text") or args.get("question") or ""

        self._set_active_work(tool, command, source=source)

        try:
            if tool == "diagnostics":
                return self._run_diagnostics()

            if tool == "set_presence":
                return self._apply_presence_args(args)

            if tool == "set_voice":
                voice = str(args.get("voice", "")).lower().strip()

                if voice not in {"kokoro", "sam"}:
                    return self._handle_voice_command(command)

                from tts.manager import set_voice

                set_voice(voice)
                return f"Voice set to {voice}."

            if tool == "arithmetic":
                return self.arithmetic_handler.answer(command)

            if tool == "briefing":
                return self.today_briefing.build()

            if tool == "weather":
                return self._run_weather(
                    location=str(args.get("location", "")).strip(),
                    question=str(args.get("question", command)).strip()
                    or command
                )

            if tool == "notify":
                text = str(args.get("text", "")).strip()

                if not text:
                    return "I need text to send as a notification."

                return self._send_notification(
                    text,
                    title=str(args.get("title", "Entity")).strip() or "Entity",
                    priority=str(args.get("priority", "default")).strip()
                    or "default"
                )

            if tool == "research":
                query = args.get("query") or self._research_query(command) or command
                return self._run_research(
                    query,
                    source=source,
                    notify_completion=bool(args.get("notify"))
                )

            if tool == "research_and_remember":
                query = (
                    args.get("query")
                    or self._research_and_remember_query(command)
                    or self._research_query(command)
                    or command
                )
                return self._run_research(
                    query,
                    remember=True,
                    source=source,
                    notify_completion=bool(args.get("notify"))
                )

            if tool == "remember_last_research":
                if not self.last_research_result:
                    return "I do not have a recent research result to remember."

                return self._ingest_research_result(
                    self.last_research_result,
                    requested_by=source
                )

            if tool == "create_calendar_event":
                return self._handle_calendar_command(command, channel=source)

            if tool == "create_reminder":
                return self._create_reminder_from_command(command, source=source)

            if tool == "store_memory":
                return self._store_explicit_memory(command, args, source=source)

            if tool == "behavior_feedback":
                return self._handle_behavior_feedback_command(
                    command,
                    source=source
                )

            return None
        finally:
            self._finish_active_work()

    def _handle_active_work_command(self, command):
        normalized = command.lower().strip()

        status_phrases = {
            "what are you doing",
            "what are you working on",
            "what are you currently doing",
            "what are you doing right now",
            "are you doing anything",
            "current task",
            "current work",
            "status of current task",
            "what is your current task"
        }

        if (
            normalized not in status_phrases
            and "what are you working on" not in normalized
            and "what are you doing" not in normalized
            and "current task" not in normalized
        ):
            return None

        pending = self.confirmation_store.current()

        if pending:
            plan = pending.get("plan") or {}
            response = plan.get("response") or "I have an action waiting for confirmation."
            return f"I am waiting for your confirmation. {response}"

        active = self.task_store.get_state("active_work")

        if active:
            tool = str(active.get("tool", "work")).replace("_", " ")
            text = active.get("input_text", "")
            return f"I am currently using {tool} for: {text}"

        last = self.task_store.get_state("last_completed_work")

        if last:
            tool = str(last.get("tool", "work")).replace("_", " ")
            text = last.get("input_text", "")
            return f"I am not actively working on anything. I most recently used {tool} for: {text}"

        return "I am not actively working on anything right now."

    def _set_active_work(self, tool, command, source="voice"):
        self.task_store.set_state(
            "active_work",
            {
                "tool": tool,
                "input_text": command,
                "source": source,
                "started_at": datetime.now().isoformat()
            }
        )

    def _finish_active_work(self):
        active = self.task_store.get_state("active_work")

        if active:
            active["finished_at"] = datetime.now().isoformat()
            self.task_store.set_state("last_completed_work", active)

        self.task_store.set_state("active_work", None)

    def _run_diagnostics(self):
        return self.execute(
            Action(
                type="diagnostics",
                payload={
                    "runtime": self
                }
            )
        )

    def _apply_presence_args(self, args):
        updates = {}
        location = str(args.get("location", "")).strip()
        availability = str(args.get("availability", "")).strip()

        if location in {"home", "away", "unknown"}:
            updates["location"] = location

        if availability in {
            "available",
            "busy",
            "sleeping",
            "do_not_disturb",
            "unknown"
        }:
            updates["availability"] = availability

        if not updates:
            return None

        self.presence.update(**updates)
        return self.presence.status_text()

    def _run_research(
        self,
        query,
        remember=False,
        source="user",
        notify_completion=False
    ):
        owns_active_work = not self.task_store.get_state("active_work")

        if owns_active_work:
            tool = "research_and_remember" if remember else "research"
            self._set_active_work(tool, query, source=source)

        try:
            try:
                result = self.research_tool.search(query)
            except Exception as exc:
                return f"Internet research failed: {exc}"

            self.last_research_result = result
            response = result.format_response()

            if not remember:
                if notify_completion:
                    return self._notify_research_complete(query, response)

                return response

            memory_response = self._ingest_research_result(
                result,
                requested_by=source
            )
            final_response = f"{response} {memory_response}"

            if notify_completion:
                return self._notify_research_complete(query, final_response)

            return final_response
        finally:
            if owns_active_work:
                self._finish_active_work()

    def _run_weather(self, location="", question=""):
        return self.weather_tool.lookup(
            location=location,
            question=question
        )

    def _create_reminder_from_command(self, command, source="voice"):
        reminder = self.reminder_extractor.extract(
            command,
            awareness_state=self.awareness.snapshot(),
            on_escalation=lambda message: self._reply(message, source)
        )

        if not reminder:
            return None

        task_id = self.task_store.add_task(
            title=reminder.message,
            message=reminder.message,
            due_at=reminder.due_at,
            kind="reminder",
            priority=reminder.priority,
            source=source
        )

        self.scheduler_observer.add_reminder_at(
            reminder.due_at,
            reminder.message,
            priority=reminder.priority,
            task_id=task_id
        )

        response = f"Reminder set: {reminder.message}."
        self._notify_significant_action(
            "set a reminder",
            command,
            response,
            source=source
        )
        return response

    def _store_explicit_memory(self, command, args, source="user"):
        content = str(args.get("content", "")).strip()

        if not content:
            content = re.sub(
                r"^\s*remember\s+(that\s+)?",
                "",
                command,
                flags=re.IGNORECASE
            ).strip()

        if not content:
            return "I could not find what to remember."

        kind = str(args.get("kind", "fact")).strip() or "fact"
        importance = args.get("importance", 5)

        try:
            importance = int(importance)
        except (TypeError, ValueError):
            importance = 5

        self.task_store.add_memory(
            kind=kind,
            content=content,
            source=source,
            importance=min(10, max(1, importance)),
            metadata={
                "source_text": command,
                "stored_by": "planner"
            }
        )

        return f"Remembered: {content}"

    def _confirmation_ttl_seconds(self):
        try:
            return max(
                30,
                int(os.getenv("ENTITY_CONFIRMATION_TTL_SECONDS", "600"))
            )
        except ValueError:
            return 600

    def _run_startup_health_check(self):
        message = self.startup_health.alert_message()

        if not message:
            return None

        self._deliver_alert(
            message,
            title="Entity startup diagnostic",
            priority="urgent",
            force_notify=True
        )

        return message

    def _handle_briefing_command(self, command):
        normalized = command.lower().strip()

        if not (
            "today briefing" in normalized
            or "daily briefing" in normalized
            or "morning briefing" in normalized
            or "brief me" in normalized
            or "what's my day" in normalized
            or "what is my day" in normalized
        ):
            return None

        return self.today_briefing.build()

    def _handle_weather_command(self, command):
        location = self._weather_location(command)

        if location is None:
            return None

        return self._run_weather(
            location=location,
            question=command
        )

    def _weather_location(self, command):
        normalized = command.lower().strip()

        if not any(
            phrase in normalized
            for phrase in (
                "weather",
                "forecast",
                "temperature",
                "rain",
                "umbrella",
                "jacket outside",
                "cold outside",
                "hot outside"
            )
        ):
            return None

        patterns = [
            r"\bweather\s+(?:in|at|for)\s+(.+)$",
            r"\bforecast\s+(?:in|at|for)\s+(.+)$",
            r"\btemperature\s+(?:in|at|for)\s+(.+)$"
        ]

        for pattern in patterns:
            match = re.search(pattern, command, re.IGNORECASE)

            if match:
                return self._clean_weather_location(match.group(1))

        return ""

    def _clean_weather_location(self, location):
        cleaned = location.strip()
        cleaned = re.sub(
            r"\s+(?:today|right now|currently|this morning|this afternoon|tonight)\s*$",
            "",
            cleaned,
            flags=re.IGNORECASE
        ).strip()
        return cleaned

    def _handle_research_command(self, command):
        query = self._research_query(command)

        if not query:
            return None

        return self._run_research(
            query,
            notify_completion=self._should_notify_completion(command)
        )

    def _handle_research_memory_command(self, command, source="user"):
        normalized = command.lower().strip()

        if normalized in {
            "remember what you found",
            "remember that research",
            "save that research",
            "store that research"
        }:
            if not self.last_research_result:
                return "I do not have a recent research result to remember."

            return self._ingest_research_result(
                self.last_research_result,
                requested_by=source
            )

        query = self._research_and_remember_query(command)

        if not query:
            return None

        return self._run_research(
            query,
            remember=True,
            source=source,
            notify_completion=self._should_notify_completion(command)
        )

    def _notify_research_complete(self, query, text):
        delivered = self._send_notification(
            text,
            title=f"Entity research: {query}",
            priority="default"
        )

        if delivered:
            return f"I researched {query} and sent what I learned to ntfy."

        return (
            f"I researched {query}, but I could not send the ntfy "
            f"notification. {text}"
        )

    def _send_notification(self, text, title="Entity", priority="default"):
        delivered = self.execute(
            Action(
                type="notify",
                payload={
                    "title": title,
                    "text": text,
                    "priority": priority
                }
            )
        )

        if delivered:
            return delivered

        return None

    def _should_notify_completion(self, command):
        normalized = command.lower()

        notification_phrases = (
            "notify me",
            "send me",
            "text me",
            "ntfy",
            "push",
            "alert me",
            "let me know",
            "inform me",
            "tell me when",
            "when you're done",
            "when you are done",
            "once you're done",
            "once you are done"
        )

        return any(
            phrase in normalized
            for phrase in notification_phrases
        )

    def _ingest_research_result(self, result, requested_by="user"):
        try:
            stored_ids = self.research_memory_ingestor.ingest(
                result,
                requested_by=requested_by
            )
        except Exception as exc:
            return f"Research memory ingestion failed: {exc}"

        if not stored_ids:
            return "No new sourced memories were stored from that research."

        count = len(stored_ids)
        noun = "memory" if count == 1 else "memories"

        return f"Stored {count} sourced research {noun}."

    def _research_and_remember_query(self, command):
        patterns = [
            r"^\s*research and remember\s+(.+)$",
            r"^\s*look up and remember\s+(.+)$",
            r"^\s*search and remember\s+(.+)$",
            r"^\s*find and remember\s+(.+)$",
            r"^\s*learn about and remember\s+(.+)$",
            r"^\s*study and remember\s+(.+)$",
            r"^\s*research\s+(.+?)\s+and remember(?: it| this)?\s*$",
            r"^\s*look up\s+(.+?)\s+and remember(?: it| this)?\s*$",
            r"^\s*search(?: the internet| online| web)? for\s+(.+?)\s+and remember(?: it| this)?\s*$",
            r"^\s*learn about\s+(.+?)\s+and remember(?: it| this)?\s*$",
            r"^\s*study\s+(.+?)\s+and remember(?: it| this)?\s*$"
        ]

        for pattern in patterns:
            match = re.search(pattern, command, re.IGNORECASE)

            if match:
                return self._clean_research_query(match.group(1))

        return ""

    def _research_query(self, command):
        patterns = [
            r"^\s*research\s+(.+)$",
            r"^\s*look up\s+(.+)$",
            r"^\s*search(?: the internet| online| web)? for\s+(.+)$",
            r"^\s*find(?: online)?\s+(.+)$",
            r"^\s*learn about\s+(.+)$",
            r"^\s*study\s+(.+)$"
        ]

        for pattern in patterns:
            match = re.search(pattern, command, re.IGNORECASE)

            if match:
                return self._clean_research_query(match.group(1))

        return ""

    def _clean_research_query(self, query):
        cleaned = query.strip()
        cleanup_patterns = [
            r"\s+and\s+(?:then\s+)?(?:notify|inform|tell|text|send|alert)\s+me\b.*$",
            r"\s+and\s+(?:then\s+)?(?:let me know)\b.*$",
            r"\s+(?:when|once)\s+you(?:'re| are)\s+done\b.*$",
            r"\s+on\s+ntfy\b.*$",
            r"\s+through\s+ntfy\b.*$",
            r"\s+via\s+ntfy\b.*$"
        ]

        for pattern in cleanup_patterns:
            cleaned = re.sub(
                pattern,
                "",
                cleaned,
                flags=re.IGNORECASE
            ).strip()

        return cleaned

    def _handle_presence_command(self, command):
        normalized = command.lower().strip()

        updates = [
            (
                ("i'm home", "i am home", "i'm back", "i am back"),
                {"location": "home", "availability": "available"},
                "Presence updated: home and available."
            ),
            (
                ("i'm leaving", "i am leaving", "i'm away", "i am away"),
                {"location": "away"},
                "Presence updated: away."
            ),
            (
                ("i'm going to sleep", "i am going to sleep", "i'm asleep"),
                {"availability": "sleeping"},
                "Presence updated: sleeping."
            ),
            (
                ("i'm awake", "i am awake"),
                {"availability": "available"},
                "Presence updated: available."
            ),
            (
                ("don't disturb me", "do not disturb", "dnd"),
                {"availability": "do_not_disturb"},
                "Presence updated: do not disturb."
            ),
            (
                ("i'm busy", "i am busy"),
                {"availability": "busy"},
                "Presence updated: busy."
            ),
            (
                ("i'm available", "i am available"),
                {"availability": "available"},
                "Presence updated: available."
            )
        ]

        if (
            "presence status" in normalized
            or "where am i" in normalized
            or "am i available" in normalized
        ):
            return self.presence.status_text()

        for phrases, payload, response in updates:
            if any(phrase in normalized for phrase in phrases):
                self.presence.update(**payload)
                return response

        return None

    def _handle_behavior_feedback_command(self, command, source="user"):
        return self.behavior_feedback_policy.handle_feedback(
            command,
            recent_actions=self.recent_actions,
            recent_responses=self.recent_responses,
            source=source
        )

    def _handle_calendar_command(self, command, channel="voice"):
        draft = self.calendar_extractor.extract(
            command,
            awareness_state=self.awareness.snapshot(),
            on_escalation=lambda message: self._reply(message, channel)
        )

        if draft is None:
            return None

        response = self.execute(
            Action(
                type="calendar",
                payload={
                    "operation": "create_event",
                    "draft": draft
                }
            )
        )
        self._notify_significant_action(
            "created a calendar event",
            command,
            response,
            source=channel
        )
        return response

    def _parse_reminder(self, command):
        relative = self._parse_relative_reminder(command)

        if relative:
            return relative

        absolute = self._parse_absolute_reminder(command)

        if absolute:
            return absolute

        return None

    def _parse_relative_reminder(self, command):
        pattern = re.compile(
            r"\bremind me in (\d+)\s+"
            r"(seconds|second|minutes|minute|hours|hour)"
            r"(?:\s+to\s+(.+))?",
            re.IGNORECASE
        )
        match = pattern.search(command)

        if not match:
            return None

        amount = int(match.group(1))
        unit = match.group(2).lower()
        message = (match.group(3) or "Reminder").strip()

        multiplier = 1

        if unit.startswith("minute"):
            multiplier = 60
        elif unit.startswith("hour"):
            multiplier = 3600

        return time.time() + (amount * multiplier), message

    def _parse_absolute_reminder(self, command):
        if re.search(r"\bremind me in\b", command, re.IGNORECASE):
            return None

        patterns = [
            re.compile(
                r"\bremind me\s+"
                r"(?:(today|tomorrow|tonight|next\s+\w+)\s+)?"
                r"(?:at\s+)?"
                r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"
                r"(?:\s+to\s+(.+))?",
                re.IGNORECASE
            ),
            re.compile(
                r"\bremind me\s+"
                r"(today|tomorrow|tonight|next\s+\w+)"
                r"(?:\s+(morning|afternoon|evening|night))?"
                r"(?:\s+to\s+(.+))?",
                re.IGNORECASE
            )
        ]

        timed = patterns[0].search(command)

        if timed:
            day_phrase = timed.group(1)
            hour = int(timed.group(2))
            minute = int(timed.group(3) or 0)
            meridiem = timed.group(4)
            message = (timed.group(5) or "Reminder").strip()

            due = self._date_for_phrase(day_phrase)
            due = due.replace(
                hour=self._normalize_hour(hour, meridiem),
                minute=minute,
                second=0,
                microsecond=0
            )

            if due <= self._now():
                due += timedelta(days=1)

            return due.timestamp(), message

        day_only = patterns[1].search(command)

        if day_only:
            day_phrase = day_only.group(1)
            part_of_day = day_only.group(2)
            message = (day_only.group(3) or "Reminder").strip()
            hour = self._hour_for_part_of_day(
                part_of_day,
                day_phrase=day_phrase
            )
            due = self._date_for_phrase(day_phrase).replace(
                hour=hour,
                minute=0,
                second=0,
                microsecond=0
            )

            if due <= self._now():
                due += timedelta(days=1)

            return due.timestamp(), message

        return None

    def _now(self):
        return datetime.now().astimezone()

    def _date_for_phrase(self, phrase):
        now = self._now()

        if not phrase or phrase.lower() == "today":
            return now

        phrase = phrase.lower().strip()

        if phrase == "tomorrow":
            return now + timedelta(days=1)

        if phrase == "tonight":
            return now

        if phrase.startswith("next "):
            weekday = phrase.replace("next ", "", 1).strip()
            target = self._weekday_number(weekday)

            if target is not None:
                days_ahead = (target - now.weekday()) % 7

                if days_ahead == 0:
                    days_ahead = 7

                return now + timedelta(days=days_ahead)

        return now

    def _weekday_number(self, weekday):
        weekdays = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6
        }

        return weekdays.get(weekday)

    def _normalize_hour(self, hour, meridiem):
        if meridiem:
            meridiem = meridiem.lower()

            if meridiem == "pm" and hour != 12:
                return hour + 12

            if meridiem == "am" and hour == 12:
                return 0

        return hour

    def _hour_for_part_of_day(self, part_of_day, day_phrase=None):
        if not part_of_day:
            if day_phrase and day_phrase.lower().strip() == "tonight":
                return 21

            return 9

        hours = {
            "morning": 9,
            "afternoon": 13,
            "evening": 18,
            "night": 21
        }

        return hours.get(part_of_day.lower(), 9)

    def _handle_voice_command(self, command):
        normalized = command.lower().strip()

        if (
            "what voice" in normalized
            or "which voice" in normalized
            or "current voice" in normalized
        ):
            from tts.manager import get_voice

            response = f"Current voice: {get_voice()}."

            return response

        pattern = re.compile(
            r"\b(?:use|switch to|set|change to)\s+"
            r"(?:the\s+)?(kokoro|sam)"
            r"(?:\s+voice)?\b",
            re.IGNORECASE
        )
        match = pattern.search(command)

        if not match:
            return None

        voice = match.group(1).lower()

        from tts.manager import set_voice

        set_voice(voice)

        response = f"Voice set to {voice}."

        return response

    def _is_diagnostics_command(self, command):
        normalized = command.lower()

        return (
            "diagnostic" in normalized
            or "system status" in normalized
            or "status report" in normalized
        )

    def execute(self, action):
        if not self.policy.allows(action):
            print(
                "Action blocked by policy:",
                action.type
            )
            return None

        for actuator in self.actuators:
            if actuator.can_handle(action):
                result = actuator.execute(action)
                self._record_action(action, result)
                self._learn_from_action(action)
                return result

        print(
            "No actuator for action:",
            action.type
        )

        return None

    def _record_action(self, action, result):
        self.recent_actions.append(
            {
                "id": action.id,
                "type": action.type,
                "payload": action.payload,
                "result": result,
                "created_at": action.created_at
            }
        )
        self.recent_actions = self.recent_actions[-10:]

    def _record_response(self, response, source="voice"):
        self.recent_responses.append(
            {
                "source": source,
                "text": response,
                "created_at": time.time()
            }
        )
        self.recent_responses = self.recent_responses[-10:]

    def _learn_from_action(self, action):
        try:
            self.learning_policy.observe_action(
                action,
                awareness_state=self.awareness.snapshot(),
                presence_state=self.presence.snapshot()
            )
        except Exception as exc:
            print("Learning from action failed:", exc)
