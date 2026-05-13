# Batch Background Remover — Football Jerseys

A Python script to batch-remove backgrounds from a large collection of product images (~10,000 photos, 23 GB), producing transparent PNGs ready for e-commerce or design use.

Built for **Infinity Imports PT** jersey catalogue, organized by football league and club.

---

## Features

- **Single model load** — the AI model (`u2net`) is loaded once before the loop, not once per image
- **Resume-safe** — skips images already processed; safely stop and restart at any time with Ctrl+C
- **Resilient** — corrupted or unreadable files are logged and skipped; the script never crashes
- **Progress bar with ETA** — live `tqdm` bar showing speed and estimated time remaining
- **Persistent error log** — all failures are appended to `erros_processamento.txt` for review
- **Memory management** — forces garbage collection every 100 images to keep RAM stable over long runs
- **Tree preservation** — replicates the exact source folder structure inside the output folder
- **Always PNG output** — all images are saved as `.png` to preserve the transparency channel

---

## Folder Structure

```
Infinity Imports pt/
├── Camisas/                    ← source (original images, organized by league)
│   ├── Brasileiro Série A/
│   ├── Bundesliga/
│   ├── La Liga/
│   ├── Ligue 1/
│   ├── Premier League/
│   ├── Primeira Liga/
│   └── Serie A/
├── Camisas_sem_fundo/          ← output (created automatically, mirrors source tree)
│   └── ...
├── erros_processamento.txt     ← error log (created automatically if errors occur)
└── remover_fundos.py           ← this script
```

---

## Requirements

- Python 3.9+
- macOS with Apple Silicon (M1/M2/M3) — ONNX Runtime runs natively via the Neural Engine

---

## Installation

```bash
pip3 install rembg pillow tqdm
```

---

## Usage

```bash
cd "/Users/brunosantos/Documents/Infinity Imports pt/Camisas"
python3 remover_fundos.py
```

The script will:
1. Scan and count all images in the source folder
2. Load the `u2net` AI model (one-time, takes a few seconds)
3. Process each image and save the result as `.png` with transparent background
4. Show a live progress bar with current file, speed, and ETA

**To stop and resume later:** press `Ctrl+C` at any time. Re-running the script will automatically skip already-completed images.

---

## Configuration

To adapt the script to a different machine or folder layout, edit the three path constants at the top of `remover_fundos.py`:

```python
SOURCE_DIR = Path("/Users/brunosantos/Documents/Infinity Imports pt/Camisas")
DEST_DIR   = Path("/Users/brunosantos/Documents/Infinity Imports pt/Camisas_sem_fundo")
LOG_FILE   = Path("/Users/brunosantos/Documents/Infinity Imports pt/erros_processamento.txt")
```

---

## Supported Formats

Input: `.jpg`, `.jpeg`, `.png`, `.webp`
Output: `.png` (always, to support transparency)

---

## Error Handling

If a file fails (corrupted, unsupported encoding, etc.):
- A message is printed to the terminal
- The file path and error are appended to `erros_processamento.txt`
- Processing continues with the next image

At the end of the run, review `erros_processamento.txt` to re-process or discard failed files.

---

## Dependencies

| Package | Purpose |
|---|---|
| `rembg` | AI-based background removal (u2net model) |
| `Pillow` | Image loading and saving |
| `tqdm` | Progress bar with ETA |
| `onnxruntime` | ONNX inference engine (installed automatically with rembg) |
