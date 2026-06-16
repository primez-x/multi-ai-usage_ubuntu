# AI Usage Tracker

A GNOME Shell extension that surfaces remaining usage limits for multiple AI
coding assistants directly in the top panel, with per-provider brand icons and
a per-provider detail menu. Designed for GNOME 50 on Ubuntu.

<img width="437" height="40" style="border-radius: 10px;" alt="image" src="https://github.com/user-attachments/assets/6bb0af5a-e16e-4740-a392-6712b62dd33c" />

<br>

<img height="300" style="border-radius: 10px;" alt="glm lite" src="https://github.com/user-attachments/assets/06e8875a-1c4f-4331-8325-a5554df783dc" />
<img height="300" style="border-radius: 10px;" alt="claude lite" src="https://github.com/user-attachments/assets/c3641f80-f56a-4602-86f8-00a542bddbde" />
<img height="300" style="border-radius: 10px;" alt="codex lite" src="https://github.com/user-attachments/assets/b581549f-e515-4252-9f8e-2ef5fd12c282" />
<img height="300" style="border-radius: 10px;" alt="image" src="https://github.com/user-attachments/assets/5b90956b-5463-4e34-b77e-9b305c3ad797" />
<img height="300" style="border-radius: 10px;" alt="claude dark" src="https://github.com/user-attachments/assets/00741ccd-37ba-4d77-b7df-fcc8be64764f" />
<img height="300" style="border-radius: 10px;" alt="codex dark" src="https://github.com/user-attachments/assets/a005a4fb-b774-4ce6-876e-f382c11391cc" />

<br>

<img height="325" style="border-radius: 10px;" alt="image" src="https://github.com/user-attachments/assets/6d45cb39-97c7-4eb5-8d62-5cbba6c57e7a" />
<img height="325" style="border-radius: 10px;" alt="image" src="https://github.com/user-attachments/assets/bfbbf3ed-aca8-4f67-9b1c-db63ca8bb9e8" />


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
