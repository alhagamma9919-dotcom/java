# Comfy Remote

Control ComfyUI on your PC from your phone: **start / stop ComfyUI**, pick a workflow,
upload a photo, edit prompt / seed / steps / cfg / models, generate, watch progress with live
preview, and save or reuse results. Dark, mobile-first UI. Works at home and away (Tailscale).

```
Phone ──(Wi-Fi / Tailscale, PIN)──► launcher.py :8190 ──► ComfyUI 127.0.0.1:8188
```

- `launcher.py` is always on (starts at logon, hidden). It starts/stops ComfyUI and serves the UI.
- ComfyUI only listens on `127.0.0.1`, so it is never exposed directly.
- Every request needs the PIN, and only home-network / Tailscale addresses are accepted.

## Install (once)
1. Install ComfyUI in `C:\ComfyUI` with a `venv` (see the main guide), and make sure your
   workflows run on the PC.
2. Get this folder, e.g. `git clone -b claude/hoi-jr8lbs https://github.com/alhagamma9919-dotcom/java C:\src\java`
3. PowerShell **as Administrator**:
   ```
   powershell -ExecutionPolicy Bypass -File C:\src\java\comfy-remote\install.ps1
   ```
   It prints your **PIN** and the phone URLs. Settings are in `config.json` (created on first run).
4. On the phone open the printed URL → enter PIN → *Add to Home screen* for an app icon.

## Add workflows (Qwen Image Edit, MiniMax image-to-video, …)
In ComfyUI on the PC: open the workflow → **Workflow → Export (API)** → save the `.json` into
`comfy-remote\workflows\`. Or import it on the phone with **＋** and tap Save.

The UI builds itself from the workflow: image inputs get a camera/gallery button, prompts get
text boxes, seed gets 🎲 random / 📌 fixed, numbers get sliders with the node's real min/max,
and dropdowns show the real choices (samplers, schedulers, model files, MiniMax model, …).
Rename nodes in ComfyUI (e.g. "Positive", "Negative") to get clearer labels.

### Curated layouts (`<workflow>.ui.json`)
Optional file next to a workflow that gives it a clean form: friendly labels, groups, help text,
slider ranges, one field writing to several nodes, and hidden clutter. Everything not listed
stays under **Advanced**. Included: `Qwen Image 2.1 Edit` and `MiniMax H3 Image to Video`.
```json
{"note": "…", "fields": [{"t": [["470", "image"]], "label": "Photo 1", "group": "Photos"}], "hide": [["472"]]}
```
If you re-export a workflow and node IDs change, update its `.ui.json` (or delete it to get the automatic form).

### MiniMax / other API nodes
These run on Comfy.org's servers and cost credits. Create an API key at platform.comfy.org and
put it in `config.json` as `"comfy_api_key"`. The key stays on the PC and is never sent to the phone.

## config.json
| key | default | meaning |
|---|---|---|
| `port` | 8190 | port for the phone |
| `comfy_dir` | `C:\ComfyUI` | folder with `main.py` |
| `comfy_python` | auto (`venv`) | python used to start ComfyUI |
| `comfy_args` | `--preview-method auto` | extra ComfyUI args (e.g. `--lowvram`) |
| `pin` | random 6 digits | phone login PIN (change it any time, then restart the task) |
| `comfy_api_key` | empty | Comfy.org key for API nodes |
| `autostart_comfy` | `true` | start ComfyUI as soon as the PC boots |

After editing: `Stop-ScheduledTask "Comfy Remote"; Start-ScheduledTask "Comfy Remote"`.

## Tips
- The PC must be awake: Settings → System → Power → Sleep: **Never** (when plugged in).
- Logs: *PC* tab in the app, or `comfy-remote\comfyui.log`.
- Uninstall: `Unregister-ScheduledTask "Comfy Remote" -Confirm:$false; Remove-NetFirewallRule -DisplayName "Comfy Remote"`
- **Never port-forward 8190/8188 on your router.** Use Tailscale for outside access.
