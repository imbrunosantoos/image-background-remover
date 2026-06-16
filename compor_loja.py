"""
compor_loja.py — Infinity Imports PT

Pega nas fotos das camisolas, classifica o tipo de foto, remove o fundo cinza de
estudio e compoe o resultado na cena da loja (manequim no poste) ou troca o fundo
mantendo o zoom. Imagens duvidosas vao para uma pasta de revisao em vez de polirem
a saida boa.

Modos:
  python3 compor_loja.py --compare-models "<foto>"   # passo 0: escolher modelo
  python3 compor_loja.py --preview "<foto>"          # afinar ancora do poste
  python3 compor_loja.py --one "<pasta do produto>"  # processar 1 produto
  python3 compor_loja.py                             # lote completo (resume-safe)

Reutiliza o padrao robusto de remover_fundos.py (sessao unica, resume, tqdm, log, gc).
"""

from __future__ import annotations

import argparse
import csv
import gc
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from rembg import new_session, remove
from tqdm import tqdm

# ------------------------------------------------------------------ Caminhos
BASE = Path("/Users/brunosantos/Documents/Infinity Imports pt")
SOURCE_DIR = BASE / "Camisas" / "fotos"
DEST_DIR = BASE / "Camisas_loja"
REVIEW_DIR = DEST_DIR / "_revisar"
REPORT_CSV = DEST_DIR / "relatorio.csv"
LOG_FILE = BASE / "erros_processamento.txt"

FUNDO_POSTE = BASE / "Camisas" / "fundos" / "FundoRoupa.png"   # cena COM poste
FUNDO_LIMPO = BASE / "Camisas" / "fundos" / "Fundo.jpg"        # cena SEM poste

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# ------------------------------------------------------------------ Modelo
# Escolhido apos --compare-models. Opcoes: "u2net", "isnet-general-use", "birefnet-general"
MODEL_NAME = "isnet-general-use"

# ------------------------------------------------------------------ Ancora do poste
# Fracoes relativas ao FundoRoupa.png (1080x1350). Calibrar com --preview.
ANCHOR_X_FRAC = 0.50      # centro horizontal do poste
POLE_TOP_Y_FRAC = 0.55    # y onde assenta a BASE do recorte (topo do poste)
TARGET_H_FRAC = 0.42      # altura do manequim como fracao da altura do fundo
SHADOW = True             # sombra suave por baixo

# ------------------------------------------------------------------ Limiares
ALPHA_THR = 30            # alfa > isto = foreground

# Classificacao
HERO_COV_MIN, HERO_COV_MAX = 0.18, 0.55
HERO_BBOX_H_MIN = 0.80
HERO_EDGE_MAX = 0.20
# Threshold alto = precisao: so planos completos contra fundo de estudio uniforme
# (claro ou escuro) qualificam; close-ups e cabides ficam KEEP/revisar.
GREY_FRAC_MIN = 0.58      # fundo de estudio bem presente nas bordas

# Deteccao de fundo de estudio neutro (no espaco RGB 0-255)
GREY_SAT_MAX = 40         # max-min dos canais (baixa saturacao)
GREY_VAL_MIN, GREY_VAL_MAX = 55, 210   # do cinza escuro ao claro

# Corte da base (poste/madeira por baixo do manequim)
STAND_NARROW_FRAC = 0.28  # largura "estreita" relativa ao torso = base a cortar

# Confianca
CONF_MIN = 0.62           # abaixo disto -> _revisar/


# ============================================================ Utilidades

def collect_images(source: Path) -> list[Path]:
    images = []
    for root, _, files in os.walk(source):
        for fname in files:
            if fname.upper().startswith("DELETAR"):
                continue  # ficheiros marcados para apagar pelo utilizador
            if Path(fname).suffix.lower() in EXTENSIONS:
                images.append((Path(root) / fname).resolve())
    return images


def grey_edge_fraction(rgb: np.ndarray) -> float:
    """Fracao das faixas de borda que sao cinza neutro de estudio."""
    h, w, _ = rgb.shape
    b = max(4, int(min(h, w) * 0.06))
    bands = np.concatenate([
        rgb[:b, :, :].reshape(-1, 3),
        rgb[-b:, :, :].reshape(-1, 3),
        rgb[:, :b, :].reshape(-1, 3),
        rgb[:, -b:, :].reshape(-1, 3),
    ])
    mx = bands.max(axis=1)
    mn = bands.min(axis=1)
    sat = mx - mn
    val = bands.mean(axis=1)
    grey = (sat <= GREY_SAT_MAX) & (val >= GREY_VAL_MIN) & (val <= GREY_VAL_MAX)
    return float(grey.mean())


def mask_metrics(alpha: np.ndarray):
    """cobertura, bbox (frac), edge_touch a partir do canal alfa."""
    h, w = alpha.shape
    mask = alpha > ALPHA_THR
    cov = float(mask.mean())
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return cov, 0.0, 0.0, 0.0, None
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    bw = (bbox[2] - bbox[0]) / w
    bh = (bbox[3] - bbox[1]) / h
    edge = float(mask[0, :].mean() + mask[-1, :].mean()
                 + mask[:, 0].mean() + mask[:, -1].mean())
    return cov, bw, bh, edge, bbox


def classify(rgb: np.ndarray, alpha: np.ndarray):
    """Devolve (tipo, metrics dict)."""
    grey = grey_edge_fraction(rgb)
    cov, bw, bh, edge, bbox = mask_metrics(alpha)
    m = dict(grey=grey, cov=cov, bbox_w=bw, bbox_h=bh, edge=edge, bbox=bbox)

    if grey < GREY_FRAC_MIN:
        return "KEEP", m
    is_hero = (HERO_COV_MIN <= cov <= HERO_COV_MAX
               and bh >= HERO_BBOX_H_MIN and edge <= HERO_EDGE_MAX)
    return ("HERO" if is_hero else "SWAP"), m


# ============================================================ HERO

def trim_stand(rgba: np.ndarray):
    """Remove a base estreita (poste/madeira) por baixo do torso.
    Devolve (rgba_aparado, ok). ok=False se a transicao nao for clara."""
    alpha = rgba[:, :, 3]
    mask = alpha > ALPHA_THR
    rows_w = mask.sum(axis=1)
    if rows_w.max() == 0:
        return rgba, False
    torso_max = rows_w.max()
    narrow = int(torso_max * STAND_NARROW_FRAC)
    h = mask.shape[0]

    # da base para cima: encontrar onde deixa de ser estreito (entra no torso)
    cut = h
    saw_narrow = False
    for y in range(h - 1, -1, -1):
        if rows_w[y] == 0:
            continue
        if rows_w[y] <= narrow:
            saw_narrow = True
            cut = y
        else:
            break
    ok = saw_narrow and cut < h - 2
    if ok:
        rgba = rgba.copy()
        rgba[cut:, :, 3] = 0
    return rgba, ok


def tight_crop(rgba: np.ndarray) -> np.ndarray:
    alpha = rgba[:, :, 3]
    ys, xs = np.where(alpha > ALPHA_THR)
    if len(xs) == 0:
        return rgba
    return rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1, :]


def compose_hero(cutout_rgba: np.ndarray, bg: Image.Image) -> Image.Image:
    """Escala e cola o recorte no poste da cena."""
    W, H = bg.size
    cut = Image.fromarray(cutout_rgba, "RGBA")
    target_h = int(H * TARGET_H_FRAC)
    scale = target_h / cut.height
    cut = cut.resize((max(1, int(cut.width * scale)), target_h), Image.LANCZOS)

    cx = int(W * ANCHOR_X_FRAC)
    base_y = int(H * POLE_TOP_Y_FRAC)
    x = cx - cut.width // 2
    y = base_y - cut.height

    canvas = bg.convert("RGBA").copy()
    if SHADOW:
        sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        a = cut.split()[3].point(lambda p: int(p * 0.45))
        blob = Image.new("RGBA", cut.size, (0, 0, 0, 0))
        blob.putalpha(a)
        sh.paste(blob, (x + 6, y + 10), blob)
        sh = sh.filter(ImageFilter.GaussianBlur(9))
        canvas = Image.alpha_composite(canvas, sh)
    canvas.paste(cut, (x, y), cut)
    return canvas.convert("RGB")


# ============================================================ SWAP

def swap_background(rgb: np.ndarray, backdrop: Image.Image) -> tuple[Image.Image, float]:
    """Troca o cinza de estudio pelo backdrop, mantendo o zoom.
    Devolve (imagem, frac_fundo_detetado)."""
    h, w, _ = rgb.shape
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    sat = mx - mn
    val = rgb.mean(axis=2)
    is_bg = (sat <= GREY_SAT_MAX) & (val >= GREY_VAL_MIN) & (val <= GREY_VAL_MAX)
    bg_frac = float(is_bg.mean())

    fg_alpha = (~is_bg).astype(np.uint8) * 255
    # suavizar a borda
    a_img = Image.fromarray(fg_alpha, "L").filter(ImageFilter.GaussianBlur(1.2))

    back = backdrop.convert("RGB").resize((w, h), Image.LANCZOS)
    fg = Image.fromarray(rgb, "RGB")
    fg.putalpha(a_img)
    out = back.convert("RGBA")
    out = Image.alpha_composite(out, fg.convert("RGBA"))
    return out.convert("RGB"), bg_frac


# ============================================================ Pipeline 1 imagem

def process_image(path: Path, session, bg_poste: Image.Image,
                  bg_limpo: Image.Image):
    """Devolve (image_out:Image, tipo:str, confianca:float, motivo:str|None)."""
    with Image.open(path) as im:
        rgb_img = im.convert("RGB")
    rgb = np.array(rgb_img)
    cut = remove(rgb_img, session=session)
    alpha = np.array(cut)[:, :, 3]

    tipo, m = classify(rgb, alpha)

    if tipo == "HERO":
        rgba = np.array(cut)
        rgba, trimmed = trim_stand(rgba)
        rgba = tight_crop(rgba)
        out = compose_hero(rgba, bg_poste)
        conf = 0.9
        motivo = None
        if not trimmed:
            conf -= 0.35
            motivo = "base_nao_cortada"
        if not (HERO_COV_MIN + 0.02 <= m["cov"] <= HERO_COV_MAX - 0.02):
            conf -= 0.1
        return out, tipo, conf, motivo

    if tipo == "SWAP":
        out, bg_frac = swap_background(rgb, bg_limpo)
        # SWAP em fotos de detalhe e pouco fiavel (maos, recortes parciais):
        # vai sempre para _revisar para o utilizador decidir, nunca para a saida boa.
        if 0.08 <= bg_frac <= 0.70:
            conf = 0.50
            motivo = "swap_rever"
        else:
            conf = 0.40
            motivo = f"swap_fundo_suspeito({bg_frac:.2f})"
        return out, tipo, conf, motivo

    # KEEP
    return rgb_img, tipo, 0.8, None


def dest_for(src: Path, tipo: str, conf: float, motivo: str | None):
    rel = src.relative_to(SOURCE_DIR.resolve()).with_suffix(".png")
    if conf < CONF_MIN:
        tag = motivo or "baixa_confianca"
        name = f"{rel.stem}__{tipo}_{tag}.png"
        return REVIEW_DIR / rel.parent / name, True
    return DEST_DIR / rel, False


# ============================================================ Modos

def run_compare_models(photo: Path):
    out_dir = DEST_DIR / "_compare_models"
    out_dir.mkdir(parents=True, exist_ok=True)
    models = ["u2net", "isnet-general-use", "birefnet-general"]
    with Image.open(photo) as im:
        rgb = im.convert("RGB")
    for name in models:
        print(f"-> {name} (pode descarregar o modelo na 1a vez)...")
        try:
            s = new_session(name)
            res = remove(rgb, session=s)
            res.save(out_dir / f"{photo.stem}__{name}.png")
            print(f"   guardado: {out_dir / (photo.stem + '__' + name + '.png')}")
        except Exception as e:
            print(f"   [ERRO] {name}: {e}")
    print(f"\nCompara os ficheiros em {out_dir} e fixa MODEL_NAME no topo do script.")


def run_preview(photo: Path):
    session = new_session(MODEL_NAME)
    bg_poste = Image.open(FUNDO_POSTE)
    bg_limpo = Image.open(FUNDO_LIMPO)
    out, tipo, conf, motivo = process_image(photo, session, bg_poste, bg_limpo)
    out_dir = DEST_DIR / "_preview"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{photo.stem}__{tipo}.png"
    out.save(dest)
    print(f"tipo={tipo} conf={conf:.2f} motivo={motivo}")
    print(f"guardado: {dest}")
    print(f"Afina ANCHOR_X_FRAC / POLE_TOP_Y_FRAC / TARGET_H_FRAC e repete.")


def run_batch(images: list[Path], label: str):
    session = new_session(MODEL_NAME)
    bg_poste = Image.open(FUNDO_POSTE)
    bg_limpo = Image.open(FUNDO_LIMPO)

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    new_report = not REPORT_CSV.exists()
    report = open(REPORT_CSV, "a", newline="", encoding="utf-8")
    writer = csv.writer(report)
    if new_report:
        writer.writerow(["origem", "tipo", "modelo", "confianca", "destino", "motivo"])

    done = 0
    with tqdm(images, desc=f"Compondo ({label})", unit="img") as pbar:
        for src in pbar:
            try:
                out, tipo, conf, motivo = process_image(
                    src, session, bg_poste, bg_limpo)
                dest, review = dest_for(src, tipo, conf, motivo)
                if dest.exists():
                    pbar.set_postfix_str(f"existe: {src.name}")
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                out.save(dest, format="PNG")
                writer.writerow([str(src), tipo, MODEL_NAME, f"{conf:.2f}",
                                 str(dest), motivo or ""])
                report.flush()
                done += 1
                pbar.set_postfix_str(f"{tipo}{'*' if review else ''} {src.name}")
                if done % 100 == 0:
                    gc.collect()
                    report.flush()
            except Exception as e:
                msg = f"{src.resolve()} | {e}"
                tqdm.write(f"[ERRO] {msg}")
                with open(LOG_FILE, "a", encoding="utf-8") as log:
                    log.write(msg + "\n")
                continue
    report.close()
    print(f"\nConcluido. {done} imagens processadas. Relatorio: {REPORT_CSV}")
    if REVIEW_DIR.exists():
        print(f"Revisar: {REVIEW_DIR}")


# ============================================================ Main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare-models", metavar="FOTO")
    ap.add_argument("--preview", metavar="FOTO")
    ap.add_argument("--one", metavar="PASTA")
    args = ap.parse_args()

    if args.compare_models:
        run_compare_models(Path(args.compare_models))
    elif args.preview:
        run_preview(Path(args.preview))
    elif args.one:
        imgs = collect_images(Path(args.one))
        print(f"{len(imgs)} imagens em {args.one}")
        run_batch(imgs, "1 pasta")
    else:
        print("A mapear imagens...")
        imgs = collect_images(SOURCE_DIR)
        print(f"Total: {len(imgs)}")
        run_batch(imgs, "lote completo")


if __name__ == "__main__":
    main()
