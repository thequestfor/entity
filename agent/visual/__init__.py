VISUAL_MODES = ("2d", "3d", "unreal")


def create_visual_sink(mode):
    normalized = str(mode).strip().lower()

    if normalized == "unreal":
        from agent.visual.unreal import UnrealRemoteControlSink

        return UnrealRemoteControlSink(enabled=True)

    if normalized in {"2d", "3d"}:
        from agent.visual.web import WebVisualSink

        return WebVisualSink(normalized)

    raise ValueError(
        f"Unknown visual mode {mode!r}. Choose: {', '.join(VISUAL_MODES)}."
    )


__all__ = [
    "VISUAL_MODES",
    "create_visual_sink"
]
