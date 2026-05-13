import gc
import os
from pathlib import Path

from PIL import Image
from rembg import new_session, remove
from tqdm import tqdm

SOURCE_DIR = Path("/Users/brunosantos/Documents/Infinity Imports pt/Camisas")
DEST_DIR = Path("/Users/brunosantos/Documents/Infinity Imports pt/Camisas_sem_fundo")
LOG_FILE = Path("/Users/brunosantos/Documents/Infinity Imports pt/erros_processamento.txt")

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def collect_images(source: Path) -> list[Path]:
    images = []
    for root, _, files in os.walk(source):
        for fname in files:
            if Path(fname).suffix.lower() in EXTENSIONS:
                images.append(Path(root) / fname)
    return images


def main():
    print("A mapear imagens na pasta de origem...")
    all_images = collect_images(SOURCE_DIR)
    total = len(all_images)
    print(f"Total de imagens encontradas: {total}")

    print("A carregar modelo u2net (carregado uma única vez)...")
    session = new_session("u2net")

    processed_count = 0

    with tqdm(all_images, desc="Removendo fundos", unit="img", total=total) as pbar:
        for source_path in pbar:
            relative = source_path.relative_to(SOURCE_DIR)
            output_path = DEST_DIR / relative.with_suffix(".png")

            if output_path.exists():
                pbar.set_postfix_str(f"ignorado (já existe): {source_path.name}")
                continue

            output_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                with Image.open(source_path) as img:
                    result = remove(img, session=session)
                    result.save(output_path, format="PNG")

                processed_count += 1
                pbar.set_postfix_str(source_path.name)

                if processed_count % 100 == 0:
                    gc.collect()

            except Exception as e:
                msg = f"{source_path.resolve()} | {e}"
                tqdm.write(f"[ERRO] {msg}")
                with open(LOG_FILE, "a", encoding="utf-8") as log:
                    log.write(msg + "\n")
                continue

    print(f"\nConcluído. {processed_count} imagens processadas.")
    if LOG_FILE.exists():
        print(f"Erros registados em: {LOG_FILE}")


if __name__ == "__main__":
    main()
