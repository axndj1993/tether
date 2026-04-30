"""Claude Code (and compatible) hook scripts.

These run via host-configured hooks (e.g. .claude/settings.json) and
drain the Telegram inbox at turn boundaries so the agent auto-replies
to operator messages without polling.

Wired automatically by `tether install claude-code`.
"""
