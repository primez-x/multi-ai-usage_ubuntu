# AI Usage Tracker

A GNOME Shell extension that surfaces remaining usage limits for multiple AI
coding assistants directly in the top panel, with per-provider brand icons and
a per-provider detail menu. Designed for GNOME 50 on Ubuntu.

Supported providers:

| Provider | Panel icon | Credentials read from |
| --- | --- | --- |
| **Codex** (ChatGPT) | OpenAI mark | `~/.codex/auth.json` — run `codex login` |
| **Claude** (Anthropic) | Claude mark | `~/.claude/.credentials.json` (Claude Code OAuth) |
| **Kimi** (Moonshot) | Kimi mark | `~/.kimi/credentials/kimi-code.json` + `~/.kimi/device_id` |
| **GLM** (Z.ai) | Z.ai mark | `ZAI_API_KEY` / `GLM_API_KEY` env, or a `claude-glm` env file, or `~/.claude/settings.json` (only when its base URL routes through z.ai) |

Each provider is optional — enable/disable and reorder them in the extension
preferences. A provider with no detected credentials simply shows nothing.

## How it works

- A small Python helper (`bin/ai_usage_tracker_helper.py`) runs as a background
  **systemd user service** in `--loop` mode, polling each provider's usage API
  on your refresh interval and writing a JSON snapshot.
- The GNOME extension (JS) reads that snapshot and renders one panel indicator
  per enabled provider: the brand icon plus a remaining/used percentage, colored
  by urgency. The menu breaks out each usage window (Session / Weekly / etc.).
- The helper only ever reads credentials from disk; it never logs them and never
  writes them to the snapshot/cache. GLM tokens are only sent to `z.ai` hosts
  (host-anchored check).

## Requirements

- GNOME Shell 50 (Wayland or X11)
- Python 3 (stdlib only — no pip packages)
- A working `systemd --user` session

## Install

```sh
# 1. Place the extension
mkdir -p ~/.local/share/gnome-shell/extensions
cp -r ai-usage-tracker@local ~/.local/share/gnome-shell/extensions/

# 2. Compile the GSettings schema (the .compiled catalog is gitignored)
cd ~/.local/share/gnome-shell/extensions/ai-usage-tracker@local
glib-compile-schemas schemas/

# 3. Install + enable the background helper service
cp systemd/ai-usage-tracker.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-usage-tracker.service

# 4. Load the extension (Wayland requires log out / log back in;
#    you cannot restart gnome-shell live)
```

Then enable **AI Usage Tracker** in *Extensions* (or
`gnome-extensions enable ai-usage-tracker@local`).

> After editing any JS, log out and back in on Wayland to reload the extension.
> The Python helper picks up changes on its next loop iteration, or restart it
> with `systemctl --user restart ai-usage-tracker.service`.

## Configuration

Open the extension preferences to set the refresh interval, panel display mode
(remaining % / used % / compact), color mode, and which providers are enabled
and in what order. New providers added by future versions are auto-enabled once;
providers you have deliberately disabled stay disabled.

## Tests

```sh
python3 -m unittest tests.test_helper
```
