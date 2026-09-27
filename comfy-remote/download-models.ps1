# Downloads the model files the Qwen Image 2.1 Edit and MiniMax H3 workflows were built for,
# from the official Comfy-Org repos on Hugging Face. Safe to re-run: skips finished files,
# resumes partial ones.
#   powershell -ExecutionPolicy Bypass -File download-models.ps1 [-ComfyDir C:\ComfyUI]
param([string]$ComfyDir = "C:\ComfyUI")
$ErrorActionPreference = "Stop"
$models = Join-Path $ComfyDir "models"

$wanted = @(
  @{ repo = "Comfy-Org/Qwen-Image-2.1"; file = "qwen_image_2.1_int8_convrot.safetensors";                      dir = "diffusion_models" },
  @{ repo = "Comfy-Org/Qwen-Image-2.1"; file = "qwen3vl_8b_int8_convrot.safetensors";                          dir = "text_encoders" },
  @{ repo = "Comfy-Org/Qwen-Image-2.1"; file = "qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors";     dir = "text_encoders" },
  @{ repo = "Comfy-Org/MiniMax-H3";     file = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors";                  dir = "text_encoders" },
  @{ repo = "Comfy-Org/MiniMax-H3";     file = "minimax_h3_video_vae_int8_convrot.safetensors";                 dir = "vae" },
  @{ repo = "Comfy-Org/MiniMax-H3";     file = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors";     dir = "loras" }
)

$trees = @{}
foreach ($w in $wanted) {
  if (-not $trees[$w.repo]) {
    $trees[$w.repo] = Invoke-RestMethod "https://huggingface.co/api/models/$($w.repo)/tree/main?recursive=true"
  }
  $f = $trees[$w.repo] | Where-Object { $_.type -eq "file" -and (Split-Path $_.path -Leaf) -eq $w.file } | Select-Object -First 1
  if (-not $f) { Write-Warning "Not found in $($w.repo): $($w.file)"; continue }

  $destDir = Join-Path $models $w.dir
  New-Item -ItemType Directory -Force $destDir | Out-Null
  $out = Join-Path $destDir $w.file
  $gb = [math]::Round($f.size / 1GB, 1)
  if ((Test-Path $out) -and (Get-Item $out).Length -eq $f.size) { "OK (already there)  $($w.file)"; continue }

  "Downloading $($w.file)  ($gb GB)  ->  $($w.dir)"
  curl.exe -L --fail --retry 10 --retry-delay 5 -C - -o "$out.part" "https://huggingface.co/$($w.repo)/resolve/main/$($f.path)"
  if ($LASTEXITCODE -ne 0) { Write-Warning "Download stopped for $($w.file). Run the script again to resume."; continue }
  if ((Get-Item "$out.part").Length -ne $f.size) { Write-Warning "Size mismatch for $($w.file). Run again to resume."; continue }
  Move-Item -Force "$out.part" $out
  "Done  $($w.file)"
}
""
"Finished. Tell Claude so the workflows can be switched back to these files."
