# Darío on Personal Jarvis: diagnosis and architecture

Darío is a single, persistent, Spanish-speaking personal assistant built on
this repository. This document records what the codebase already provides,
what was missing, how Darío is layered on top without changing the product's
architecture, and which work runs in the cloud versus on the Windows PC.

Everything marked **implemented** below exists in this branch and is covered
by tests that ran green. Everything marked **planned** does not exist yet.

## 1. State of the codebase

- Version **2.9.0** (`pyproject.toml`, CHANGELOG entry 2026-10-05). The fork's
  `main` matched its `origin/main` at the start of this work.
- Python 3.11–3.14, FastAPI backend, React/Vite frontend shipped as a
  prebuilt bundle in `jarvis/ui/web/dist/`, desktop shell as a WebView.
- The binding rules for every coding agent are in `AGENTS.md`; the anti-pattern
  register (AP-n) and the bug history are in `docs/BUGS.md`; decisions are ADRs
  in `docs/adr/`.

### What already exists and Darío reuses unchanged

| Need | Where it lives | Notes |
|---|---|---|
| Assistant name | `jarvis/brain/assistant_name.py` | Derived from the wake phrase; there is no separate name setting. |
| Character and tone | `<data>/workspace/SOUL.md`, `jarvis/memory/soul.py`, `jarvis/brain/identity.py` | Rendered into every prompt (chat, pipeline voice, realtime voice). |
| Wake word | `jarvis/speech/wake_phrase.py`, `jarvis/plugins/wake/` | Generic chain: user-trained ONNX, then per-language Vosk keyword spotting, then local Whisper transcript match, then hotkey-only. Spanish (`es`) is a supported wake language. |
| Languages | `jarvis/core/turn_language.py`, `[brain] reply_language`, `[ui] language` | `de`, `en`, `es` are equal locales. |
| Brain providers | `jarvis/plugins/brain/` | `claude-api` (Anthropic API key, billed per token), `claude-cli` (Claude subscription through the Claude Code CLI; its own docstring measures 10–12 s start-up, so it is not a voice tier), plus OpenAI, Gemini, Grok, OpenRouter, local Ollama/llama.cpp. |
| Voice | `jarvis/speech/pipeline.py`, `jarvis/plugins/realtime/` | Classic pipeline (speech-to-text → brain → text-to-speech) or a realtime speech-to-speech provider. No Anthropic realtime provider exists, so Claude as the voice brain means the classic pipeline. |
| Spanish male voice | `jarvis/plugins/tts/` | Gemini Flash TTS voice `Charon` (the shipped default, male, needs a Google AI Studio key) or the keyless local Piper voice `es_ES-davefx` (male, Castilian accent). No Colombian-accent voice is catalogued. |
| Memory | `jarvis/memory/` | SQLite recall, the Obsidian wiki vault, `USER.md`/`SOUL.md`/`people/` in the local data folder. All local. |
| Permissions | `jarvis/safety/` | Risk tiers safe / monitor / ask / block, blacklist > whitelist > default, two-turn voice confirmation for `ask`. Only `ToolExecutor.execute()` runs a tool. |
| PC control | `jarvis/plugins/tool/` | `run_shell` (destructive commands escalate to `ask`), `open_app`, app actions, keyboard/mouse, the `computer` tool for screen work. |
| Development tools | `jarvis/agentic_ide/`, `jarvis/society/`, `jarvis/missions/` | Terminal panes running Claude Code or Codex, named agents, mission workers in isolated git worktrees, git and GitHub status. |
| Other computers | `jarvis/computers/`, `jarvis/agent_chat/remote_cli.py` | Machines reached over SSH (LAN or rented), coding-agent turns run on them with tools forwarded back through the pinned SSH connection. |
| Remote messaging | `jarvis/channels/telegram.py`, `discord.py` | Long polling: no public endpoint and no open port. |
| Local automation API | `docs/jarvis-control-api.md`, `docs/jarvis-cli.md` | Bound to `127.0.0.1`, per-install key in the OS keyring. Lets a local agent (Claude Code) drive the running app. |
| Autostart | `jarvis/autostart/windows.py` | Logon scheduled task (one UAC prompt) with a Startup-folder fallback. Never a Windows Service (no microphone, AP-17). |
| Home Assistant | `jarvis/plugins/tool/home_assistant_rest.py` | Marketplace plugin over the documented REST API, risk `ask`. |
| Profiles | `load_config()` in `jarvis/core/config.py` | `[profile] name = "<x>"` deep-merges `profiles/<x>.yaml` over `jarvis.toml`. |

### What was missing

1. **Accented names broke.** The display tokenizer kept only `a–z`, digits and
   German umlauts, so the wake phrase "Darío" produced the name "Dar O". Fixed.
2. **No registry of the person's own devices** (desktop, laptop, phone, smart
   speaker, home hub) and what each may do. `jarvis/computers` is a list of SSH
   hosts, not personal devices. Added.
3. **No Wake-on-LAN** anywhere. Added.
4. **No OS power tool.** Shutdown/restart were only reachable by composing a
   shell command, and `systemctl poweroff` classified as a mere modification.
   Added, and the classification fixed.
5. **No Darío identity**: no profile, no character. Added as data, not code.
6. **Alexa and iPhone endpoints** do not exist. Planned (section 5).
7. **One identity across several installs** (desktop plus laptop each running
   the app) does not exist; each install has its own data folder. Planned
   (section 4).

## 2. What this branch implements

| Item | Files | Verified by |
|---|---|---|
| Accent-safe wake names, Spanish `oye` prefix | `jarvis/speech/wake_constants.py`, `frontend/src/lib/deriveAssistantName.ts` | `tests/unit/brain/test_assistant_name.py`, `tests/unit/speech/test_wake_phrase.py`, `deriveAssistantName.test.ts` |
| Owned-device registry | `jarvis/devices/models.py`, `store.py`, `__main__.py` | `tests/unit/devices/test_models_and_store.py`, `test_cli.py` |
| Wake-on-LAN (local network only) | `jarvis/devices/wol.py` | `tests/unit/devices/test_wol.py` (exact bytes, a real loopback send, internet targets refused) |
| OS power actions for this computer | `jarvis/devices/power.py` | `tests/unit/devices/test_power.py` |
| `device-control` brain tool | `jarvis/plugins/tool/device_control.py`, `ROUTER_TOOLS`, ADR-0011 amendment | `tests/unit/devices/test_device_control_tool.py`, `tests/unit/brain/test_routing.py` |
| Power commands ask first via the shell too | `jarvis/safety/command_impact.py` | `tests/unit/plugins/tool/test_command_impact.py` |
| Darío profile | `profiles/dario.yaml`, `profiles/dario.SOUL.md` | `tests/unit/scripts/test_setup_dario.py` |
| One-command setup with backups | `scripts/dario/setup_dario.py` | same |

### `device-control` tiers

| Call | Tier | Behaviour |
|---|---|---|
| `list` | safe | Registered devices and granted capabilities. |
| `wake` | monitor | One magic packet to a device with the `wake_on_lan` capability and a MAC the person entered. Reports "packet sent", never "device is on". |
| `power lock` | monitor | Locks this computer. |
| `power shutdown/restart/sleep` | ask | The person confirms first. Shutdown and restart carry a 60-second grace period on Windows and Linux. |
| `power cancel` | safe | Aborts a pending shutdown or restart. |

Power for another device is refused with an honest message until Darío runs
on that device.

### The profile

`profiles/dario.yaml` sets only identity and language: wake phrase "Darío"
(matching folds accents, so "Dario" wakes it too), Spanish wake model, Spanish
replies and interface, `tts.language_code = auto`, and "Darío" as an
STT bias word. Providers, keys and voices stay an in-app choice. While the
profile is active its keys win over the same keys changed in Settings.

`profiles/dario.SOUL.md` is the character: male, informal, natural, moderately
Colombian, never corporate, explicit limits on inventing facts and on acting
without confirmation.

## 3. Architecture

```
DARÍO CORE  = the Personal Jarvis install on the desktop PC
  identity  : profiles/dario.yaml + <data>/workspace/SOUL.md
  memory    : <data>/ (SQLite recall, wiki vault, USER.md, people/)
  brain     : Claude through claude-api (voice/router) and claude-cli (heavy work)
  safety    : ToolExecutor tiers, voice confirmation
  devices   : <user data>/devices/devices.json
     │
     ├── Desktop agent ........ the same install (local tools, voice, PC control)
     ├── HP OMEN agent ........ planned: an SSH-connected computer of the core
     ├── iPhone endpoint ...... today: Telegram channel (no open port); later: Shortcuts
     ├── Home Assistant ....... existing marketplace plugin (REST, ask tier)
     └── Alexa endpoint ....... planned, official skill route only
```

Principles kept from the existing architecture:

- Higher layers reach lower ones through `jarvis/core/protocols.py`; Darío adds
  no new layer.
- The router stays a pure dispatcher; the one new tool went through the
  ADR-0011 amendment process.
- Darío is configuration plus data. Removing the `[profile]` line returns the
  install to stock Personal Jarvis.
- Nothing listens on a public interface. Wake-on-LAN sends one UDP datagram
  to a private or broadcast address and opens no port.

## 4. Cloud versus the Windows PC

| Work | Cloud (Claude Code on the web) | Windows PC |
|---|---|---|
| Read and change code, run the Linux test suite, open PRs | yes | yes |
| Build the frontend bundle | yes | yes |
| Run the desktop app, microphone, speaker, live wake word | no | yes |
| Credentials in the Windows Credential Manager | no | yes |
| Wake-on-LAN on the home network, OS power actions | no | yes |
| Autostart registration (one UAC prompt) | no | yes |
| Windows-only tests | no | yes |

How Claude reaches the PC:

1. **Remote Control** from this project: a Claude Code session started on the
   PC in the repository folder can pull this branch, reinstall, run the setup
   script and the Windows tests, and restart the app.
2. **Inside Personal Jarvis**: Claude Code runs in the app's terminal panes and
   as named agents, and can drive the running app through the local Control API
   and the `jarvis` CLI (`.agents/skills/drive-jarvis-cli`).

### Several devices, one Darío

The simplest design that keeps one identity and needs no new infrastructure:
the desktop install is the core; the HP OMEN is added as an SSH-connected
computer of that core (`jarvis/computers`, LAN address, OpenSSH server on
Windows, key authentication). Darío then runs coding agents there through the
existing remote CLI path, wakes it with Wake-on-LAN, and can shut it down over
SSH. Memory and character stay in one place. A second full install on the
laptop would split memory and is not recommended until a sync design exists.

## 5. Planned endpoints

- **Alexa.** Alexa keeps its own wake word and native functions; no firmware
  change. The supported route is a custom Alexa skill invoked by name ("Alexa,
  pídele a Darío …"). A skill's backend runs in Amazon's cloud and must reach
  the core without an open port on the PC, which needs an outbound relay from
  the PC. That relay is the open design question; nothing is built yet.
- **iPhone.** Today: the Telegram channel. Later: Shortcuts calling the same
  outbound-only route.
- **Home Assistant.** Connect the existing marketplace plugin in the app.

## 6. Manual steps on the PC

1. Get this branch (or `main` after merge) and reinstall in place so the new
   tool's entry point registers: `pip install -e . --no-deps`.
2. `python scripts/dario/setup_dario.py` (dry run), then `--apply`, then restart
   the app.
3. Choose how Claude is paid for: an Anthropic API key (per-token billing) for
   the voice/router tier, and/or a Claude subscription through the Claude Code
   CLI for heavy work. Enter keys in the app; never in `jarvis.toml`.
4. Choose the voice: Gemini `Charon` (key) or local Piper `es_ES-davefx`
   (download in the app).
5. Register devices with real values, for example
   `python -m jarvis.devices add --id desktop --name "Desktop PC" --kind desktop --platform windows --endpoint local_agent --this-machine --cap power --cap apps --cap files --cap shell --cap dev_tools --cap coding_agents --cap voice`.
   The laptop's MAC comes from `Get-NetAdapter` on the laptop; Wake-on-LAN must
   be enabled in its firmware and network adapter.
