# Comfy Remote

A single mobile page to control ComfyUI from your phone: pick a workflow, upload an image,
edit prompts/seed/steps, generate, watch progress with live preview, save results, and reuse
an output as the next input (handy for Qwen Image Edit chains).

It is a tiny ComfyUI custom node (no Python dependencies), so the page is served by ComfyUI itself.

## Install
1. Copy this `comfy-remote` folder to `ComfyUI\custom_nodes\comfy-remote`.
2. Start ComfyUI listening on your network:
   ```
   python main.py --listen 0.0.0.0 --preview-method auto
   ```
   When Windows Firewall asks, allow **Private networks only**.
3. On your phone (same Wi-Fi) open `http://<PC-IP>:8188/remote`
   (find the IP with `ipconfig`, e.g. `192.168.1.20`).

## Add workflows
1. In ComfyUI on the PC, build/open a workflow and make sure it runs (e.g. Templates → Qwen Image Edit).
2. **Workflow → Export (API)** and save the `.json` into `comfy-remote\workflows\`,
   or open it from the phone with 📂 and tap **Save**.

The page finds inputs automatically:
- `LoadImage` nodes → image upload (camera/gallery)
- text/prompt inputs → prompt boxes
- seed (🎲 = new random seed each run), steps, cfg, denoise, width, height → Settings
- everything else → Advanced

Tip: rename nodes in ComfyUI (e.g. "Positive", "Negative") — those titles are used as labels.

## Security
ComfyUI has no login. Only use it on your home Wi-Fi or over Tailscale
(`http://<pc-tailscale-name>:8188/remote`). **Never port-forward 8188 on your router.**
