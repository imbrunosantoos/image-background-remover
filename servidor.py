"""
servidor.py — UI local para testar o compor_loja.py

Sobe um servidor em http://localhost:5000 onde podes arrastar imagens ou escolher
uma pasta inteira; o servidor recorta/compoe cada uma e mostra o resultado lado a
lado com o tipo (HERO/SWAP/KEEP) e a confianca.

O modelo rembg e carregado UMA vez no arranque e fica residente (mais leve para a
maquina do que lancar um processo por imagem).

Correr:
    cd "/Users/brunosantos/Documents/Infinity Imports pt/Camisas"
    python3 servidor.py
"""

import base64
import importlib.util
import io
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request
from PIL import Image
from rembg import new_session

# importar o pipeline ja existente
_spec = importlib.util.spec_from_file_location(
    "compor_loja", Path(__file__).with_name("compor_loja.py"))
cl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cl)

app = Flask(__name__)

print(f"A carregar modelo {cl.MODEL_NAME} (uma vez)...")
SESSION = new_session(cl.MODEL_NAME)
BG_POSTE = Image.open(cl.FUNDO_POSTE).convert("RGB")
BG_LIMPO = Image.open(cl.FUNDO_LIMPO).convert("RGB")
PORT = 8000  # 5000 e ocupada pelo AirPlay Receiver do macOS (ControlCenter)
print(f"Pronto. Abre http://localhost:{PORT}")


PAGE = """
<!doctype html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Infinity Imports — Compor na loja</title>
<script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-neutral-950 text-neutral-100 min-h-screen">
<div class="max-w-6xl mx-auto px-4 py-8">
  <h1 class="text-2xl font-bold mb-1">Infinity Imports — Compor na loja</h1>
  <p class="text-neutral-400 mb-6">Arrasta imagens ou escolhe uma pasta. O servidor
     recorta e compoe cada camisola na cena da loja.</p>

  <div id="drop" class="border-2 border-dashed border-neutral-700 rounded-xl p-10
       text-center transition-colors cursor-pointer hover:border-neutral-500">
    <p class="text-lg mb-3">Arrasta as imagens para aqui</p>
    <div class="flex gap-3 justify-center">
      <label class="bg-neutral-800 hover:bg-neutral-700 px-4 py-2 rounded-lg cursor-pointer">
        Escolher ficheiros
        <input id="files" type="file" accept="image/*" multiple class="hidden">
      </label>
      <label class="bg-neutral-800 hover:bg-neutral-700 px-4 py-2 rounded-lg cursor-pointer">
        Escolher pasta
        <input id="dir" type="file" webkitdirectory multiple class="hidden">
      </label>
    </div>
  </div>

  <div id="bar" class="hidden mt-6">
    <div class="flex justify-between text-sm text-neutral-400 mb-1">
      <span id="status">A processar...</span><span id="count"></span>
    </div>
    <div class="w-full bg-neutral-800 rounded-full h-2">
      <div id="prog" class="bg-emerald-500 h-2 rounded-full" style="width:0%"></div>
    </div>
  </div>

  <div class="flex gap-4 mt-6 text-sm text-neutral-400" id="legend"></div>
  <div id="grid" class="grid grid-cols-2 md:grid-cols-3 gap-4 mt-4"></div>
</div>

<script>
const COLORS = {HERO:'bg-emerald-600', SWAP:'bg-amber-600', KEEP:'bg-neutral-600'};
const drop = document.getElementById('drop');
const grid = document.getElementById('grid');
const bar = document.getElementById('bar');
const prog = document.getElementById('prog');
const countEl = document.getElementById('count');
const statusEl = document.getElementById('status');
let queue = [], total = 0, done = 0;

['dragenter','dragover'].forEach(e => drop.addEventListener(e, ev => {
  ev.preventDefault(); drop.classList.add('border-emerald-500');
}));
['dragleave','drop'].forEach(e => drop.addEventListener(e, ev => {
  ev.preventDefault(); drop.classList.remove('border-emerald-500');
}));
drop.addEventListener('drop', ev => addFiles(ev.dataTransfer.files));
document.getElementById('files').addEventListener('change', e => addFiles(e.target.files));
document.getElementById('dir').addEventListener('change', e => addFiles(e.target.files));

function addFiles(fileList) {
  const imgs = [...fileList].filter(f => f.type.startsWith('image/'));
  if (!imgs.length) return;
  queue.push(...imgs); total += imgs.length;
  bar.classList.remove('hidden');
  updateBar();
  if (queue.length === imgs.length) pump();
}

function updateBar() {
  countEl.textContent = done + ' / ' + total;
  prog.style.width = (total ? (done/total*100) : 0) + '%';
  statusEl.textContent = done < total ? 'A processar...' : 'Concluido';
}

function card(file) {
  const el = document.createElement('div');
  el.className = 'bg-neutral-900 rounded-xl overflow-hidden border border-neutral-800';
  el.innerHTML = `
    <div class="grid grid-cols-2">
      <img src="${URL.createObjectURL(file)}" class="aspect-[4/5] object-cover bg-neutral-800">
      <div class="result aspect-[4/5] flex items-center justify-center bg-neutral-800 text-neutral-500 text-sm">...</div>
    </div>
    <div class="p-2 flex items-center justify-between">
      <span class="badge text-xs px-2 py-0.5 rounded bg-neutral-700">...</span>
      <span class="name text-xs text-neutral-500 truncate ml-2">${file.name}</span>
    </div>`;
  grid.prepend(el);
  return el;
}

async function pump() {
  while (queue.length) {
    const file = queue.shift();
    const el = card(file);
    const fd = new FormData(); fd.append('imagem', file);
    try {
      const r = await fetch('/processar', {method:'POST', body:fd});
      const d = await r.json();
      if (d.erro) throw new Error(d.erro);
      el.querySelector('.result').outerHTML =
        `<img src="${d.resultado}" class="result aspect-[4/5] object-cover bg-neutral-800">`;
      const b = el.querySelector('.badge');
      const rev = d.conf < d.conf_min;
      b.className = 'badge text-xs px-2 py-0.5 rounded ' + (COLORS[d.tipo]||'bg-neutral-700');
      b.textContent = d.tipo + (rev ? ' · REVISAR' : '') + '  ' + d.conf.toFixed(2);
    } catch (err) {
      el.querySelector('.result').textContent = 'erro';
      el.querySelector('.badge').textContent = 'ERRO';
    }
    done++; updateBar();
  }
}
</script>
</body>
</html>
"""


@app.get("/")
def index():
    return render_template_string(PAGE)


@app.post("/processar")
def processar():
    f = request.files.get("imagem")
    if not f:
        return jsonify(erro="sem imagem"), 400
    try:
        img = Image.open(f.stream).convert("RGB")
        out, tipo, conf, motivo = cl.process_pil(img, SESSION, BG_POSTE, BG_LIMPO)
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        data = base64.b64encode(buf.getvalue()).decode()
        return jsonify(
            tipo=tipo, conf=conf, motivo=motivo, conf_min=cl.CONF_MIN,
            resultado="data:image/png;base64," + data)
    except Exception as e:
        return jsonify(erro=str(e)), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=False)
