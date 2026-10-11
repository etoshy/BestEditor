"""
📘 Ferramentas do guia (rode na pasta do site):

  python dp_guia.py verificar            confere os extras e o que falta (miniatura, fonte, som, mapeamento…)
  python dp_guia.py miniaturas [--refazer id …]
                                         gera SÓ as miniaturas/prévias que faltam (destaques, filtros, animações, overlays);
                                         --refazer apaga antes as de um item que você mudou
  python dp_guia.py listar <tipo>        ids que dá pra usar em "base"/"igual_a" (transicoes, efeitos, entradas,
                                         filtros, destaques, cenas, arranjos, fundos, fontes, sons, paletas)
  python dp_guia.py som <arquivo> [--categoria meus] [--nome "Boom grave"]
                                         converte pra .m4a em assets/sons/<categoria>/, mede o pico e registra nos extras
  python dp_guia.py fonte <arquivo.ttf> --chave minha [--nome "Minha Fonte"] [--estilo Bold|Regular|Italic]
                                         renomeia a família pra "DP <Nome>", copia pra assets/fonts/dp e registra nos extras

Guia completo: docs/guia/README.md (ou a página 📘 Guia do site).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List

_AQUI = os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------------------------ verificar
def verificar() -> Dict[str, List[str]]:
    """{"erros": [...], "avisos": [...], "faltando_miniatura": [...]} — o que a pessoa precisa olhar."""
    import cenas_dp
    import dp_cores  # noqa: F401  (aplica as paletas dos extras)
    import dp_destaques
    import dp_extras
    import dp_fundos
    import dp_galeria
    import dp_sons
    import dp_visual
    dp_visual.dp()
    dp_sons.sons()
    cenas_dp.catalogo()
    avisos: List[str] = []
    falta: List[str] = []
    # filtros
    for f in dp_visual.filtros():
        if f["id"] != "original" and not f["cadeia"]:
            avisos.append(f"filtro {f['id']}: sem cadeia do ffmpeg (sai igual ao Original).")
        if not dp_galeria.existe("filtros", f"{f['id']}.jpg"):
            falta.append(f"filtros/{f['id']}.jpg")
    # transições
    for t in dp_visual.transicoes():
        alvo = dp_visual.MAPA_TRANSICOES.get(t["dp_id"])
        if not alvo:
            avisos.append(f"transição {t['id']}: sem mapeamento (vira fade) — ponha \"xfade\", \"expr\" ou \"igual_a\".")
        elif alvo.startswith("@") and alvo[1:] not in dp_visual._ESPECIAIS:
            avisos.append(f"transição {t['id']}: expressão {alvo} não existe.")
    # entradas / efeitos
    for g in dp_visual.entradas():
        if g["id"] != "none" and not dp_galeria.existe("animacoes", f"entrada_{g['id']}.mp4"):
            falta.append(f"animacoes/entrada_{g['id']}.mp4")
    for e in dp_visual.efeitos():
        if e["id"] == "none":
            continue
        if dp_visual.efeito_e_movimento(e["id"]):
            if not dp_galeria.existe("animacoes", f"camera_{e['id']}.mp4"):
                falta.append(f"animacoes/camera_{e['id']}.mp4")
        else:
            if not dp_visual.atmosfera(e["id"], 64, 36, 1.0, os.path.join(_AQUI, "outputs", "_guia_tmp"))[1]:
                avisos.append(f"efeito {e['id']}: sem visual de atmosfera (não muda nada na montagem).")
            if not dp_galeria.existe("overlays", f"{e['id']}.mp4"):
                falta.append(f"overlays/{e['id']}.mp4")
    # destaques
    sons_ids = {s["id"] for s in dp_sons.sons()}
    for hid, h in dp_destaques.catalogo().items():
        fonte = (h.get("tipografia") or {}).get("fonte")
        if fonte and fonte not in dp_destaques._FONTE:
            avisos.append(f"destaque {hid}: fonte {fonte!r} não existe (usa DP Inter) — veja  python dp_guia.py listar fontes")
        cena = h.get("cena") or {}
        if h.get("_extra") and cena.get("fundo") and cena["fundo"] not in dp_fundos._DO_DARKPLANNER and cena["fundo"] not in dp_fundos.IDS_DESTAQUE:
            avisos.append(f"destaque {hid}: cena.fundo {cena['fundo']!r} desconhecido (usa o do tratamento).")
        for a in (h.get("audio") or {}).get("assets") or []:
            sid = dp_sons.do_darkplanner(a) or (a if a in sons_ids else None)
            if not sid and h.get("_extra"):
                avisos.append(f"destaque {hid}: som {a!r} não encontrado — use um id de  python dp_guia.py listar sons")
        if not dp_galeria.existe("destaques", f"{hid}.jpg"):
            falta.append(f"destaques/{hid}.jpg")
    # quadros editoriais
    import dp_editorial
    for tipo in dp_editorial.TIPOS:
        if not dp_galeria.existe("editorial", f"{tipo}.jpg"):
            falta.append(f"editorial/{tipo}.jpg")
    # fontes dos extras
    for k, v in (dp_extras.carregar().get("fontes") or {}).items():
        for est, arq in (v.get("arquivos") or {}).items():
            if not os.path.isfile(os.path.join(dp_destaques.FONTES_DIR, arq)):
                avisos.append(f"fonte {k}: arquivo assets/fonts/dp/{arq} ({est}) não existe.")
    shutil.rmtree(os.path.join(_AQUI, "outputs", "_guia_tmp"), ignore_errors=True)
    return {"erros": dp_extras.erros(), "avisos": avisos, "faltando_miniatura": falta}


def miniaturas(refazer: List[str] = ()) -> Dict[str, int]:
    """Gera só as miniaturas que faltam. `refazer`: ids cujas miniaturas são apagadas antes (item que mudou)."""
    import dp_galeria
    for iid in refazer or ():
        for rel in (f"destaques/{iid}.jpg", f"filtros/{iid}.jpg", f"animacoes/entrada_{iid}.mp4", f"animacoes/entrada_{iid}.jpg",
                    f"animacoes/camera_{iid}.mp4", f"animacoes/camera_{iid}.jpg", f"overlays/{iid}.mp4", f"overlays/{iid}.jpg"):
            c = os.path.join(dp_galeria.GALERIA_DIR, rel)
            if os.path.isfile(c):
                os.remove(c)
        prev = os.path.join(_AQUI, "outputs", "previas_destaques")
        if os.path.isdir(prev):
            for n in os.listdir(prev):
                if n.startswith(iid + "_") and n.endswith(".mp4"):
                    os.remove(os.path.join(prev, n))
    falta = verificar()["faltando_miniatura"]
    por = {"destaques": [], "filtros": [], "animacoes": [], "overlays": [], "editorial": []}
    for f in falta:
        pasta, nome = f.split("/", 1)
        por[pasta].append(os.path.splitext(nome)[0])
    feitas = {}
    if por["destaques"]:
        feitas["destaques"] = dp_galeria.gerar_destaques(por["destaques"])
    if por["filtros"]:
        feitas["filtros"] = dp_galeria.gerar_filtros(por["filtros"])
    if por["animacoes"]:
        feitas["animacoes"] = dp_galeria.gerar_animacoes(por["animacoes"])
    if por["overlays"]:
        feitas["overlays"] = dp_galeria.gerar_overlays(por["overlays"])
    if por["editorial"]:
        import dp_editorial
        feitas["editorial"] = dp_editorial.gerar_miniaturas(os.path.join(dp_galeria.GALERIA_DIR, "editorial"), dp_galeria.foto_exemplo(), por["editorial"])
    return feitas


# ------------------------------------------------------------------ listar
def listar(tipo: str) -> List[str]:
    import cenas_dp
    import dp_cores
    import dp_destaques
    import dp_fundos
    import dp_sons
    import dp_visual
    if tipo == "transicoes":
        return [f"{t['dp_id']:<28} {t['rotulo']}" for t in dp_visual.transicoes()] + \
               [f"{n:<28} (nativa/nossa)" for n in sorted(dp_visual._XFADE_NATIVAS)]
    if tipo == "efeitos":
        return [f"{e['id']:<24} {e['rotulo']}{'  (câmera, só foto)' if e['so_foto'] else ''}" for e in dp_visual.efeitos()]
    if tipo == "entradas":
        return [f"{e['id']:<18} {e['rotulo']}  ~{e['dur']}s" for e in dp_visual.entradas()]
    if tipo == "filtros":
        return [f"{f['id']:<16} {f['rotulo']}" for f in dp_visual.filtros()]
    if tipo == "destaques":
        return [f"{e['id']:<28} {e['nome']}  [{e['categoria']}] {e['forma']} · {e['zona']}" for e in dp_destaques.catalogo_para_editor()]
    if tipo == "cenas":
        return [f"{c['id']:<28} {c['nome']}  ({c['slots']} trecho(s), arranjo {c['arranjo']})" for c in cenas_dp.catalogo_para_editor()]
    if tipo == "arranjos":
        return [f"{k:<22} {len(v['janelas'])} janela(s)" for k, v in cenas_dp._ARRANJOS.items()]
    if tipo == "fundos":
        return [f"{f[0]:<18} {f[1]}" for f in dp_fundos.FUNDOS_DESTAQUE]
    if tipo == "fontes":
        return [f"{k:<14} {v}" for k, v in dp_destaques._FONTE.items()]
    if tipo == "sons":
        return [f"{s['id']:<38} {s.get('dur', 0):.2f}s  pico {s.get('pico', 0):.2f}s" for s in dp_sons.sons()]
    if tipo == "paletas":
        return [f"{p['id']:<16} {p['nome']}  {p['primaria']} {p['secundaria']} {p['acento']}" for p in dp_cores.PALETAS]
    raise SystemExit(f"tipo desconhecido: {tipo}")


# ------------------------------------------------------------------ registrar nos extras
def _arquivo_extras(nome: str) -> str:
    import dp_extras
    os.makedirs(dp_extras.pasta(), exist_ok=True)
    return os.path.join(dp_extras.pasta(), nome)


def _ler_json(caminho: str) -> Dict[str, Any]:
    try:
        with open(caminho, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar_json(caminho: str, d: Dict[str, Any]) -> None:
    with open(caminho + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(caminho + ".tmp", caminho)


def _slug(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:40] or "som"


def medir_som(caminho: str) -> Dict[str, float]:
    """dur, inicio_som, pico, fim_som (s) e nivel_db (pico em dBFS) — o pico é o que cai no instante do evento."""
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", caminho, "-ac", "1", "-ar", "22050", "-f", "f32le", "-"],
                       capture_output=True, timeout=300)
    if r.returncode or not r.stdout:
        raise SystemExit(f"Não consegui ler o áudio: {r.stderr.decode(errors='replace')[-300:]}")
    a = np.abs(np.frombuffer(r.stdout, dtype=np.float32))
    sr = 22050
    pico_v = float(a.max()) if len(a) else 0.0
    if pico_v <= 0:
        raise SystemExit("O áudio está em silêncio.")
    janela = max(1, sr // 100)  # envelope de 10 ms (o pico de um clique de 1 amostra não conta)
    env = np.convolve(a, np.ones(janela) / janela, mode="same")
    acima = np.where(env > env.max() * 0.1)[0]
    return {"dur": round(len(a) / sr, 3), "inicio_som": round(float(acima[0]) / sr, 3), "pico": round(float(env.argmax()) / sr, 3),
            "fim_som": round(float(acima[-1]) / sr, 3), "nivel_db": round(20 * float(np.log10(pico_v)), 1)}


def adicionar_som(arquivo: str, categoria: str = "meus", nome: str = "") -> Dict[str, Any]:
    import dp_sons
    if not os.path.isfile(arquivo):
        raise SystemExit(f"Arquivo não encontrado: {arquivo}")
    categoria = _slug(categoria) or "meus"
    base = _slug(nome or os.path.splitext(os.path.basename(arquivo))[0])
    destino_rel = f"{categoria}/{base}.m4a"
    destino = os.path.join(dp_sons.SONS_DIR, destino_rel)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", arquivo, "-vn", "-ac", "2", "-ar", "48000", "-c:a", "aac", "-b:a", "192k", destino],
                       capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise SystemExit(f"ffmpeg não converteu: {r.stderr[-300:]}")
    item = {"id": f"{categoria}/{base}", "categoria": categoria, "nome": nome or base.replace("_", " "), "arquivo": destino_rel,
            **medir_som(destino)}
    cam = _arquivo_extras("sons.json")
    d = _ler_json(cam)
    d["sons"] = [s for s in d.get("sons") or [] if s.get("id") != item["id"]] + [item]
    _gravar_json(cam, d)
    return item


def adicionar_fonte(arquivo: str, chave: str, nome: str = "", estilo: str = "") -> Dict[str, Any]:
    import dp_destaques
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        raise SystemExit("Precisa do fontTools:  pip install fonttools")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_]{1,30}", chave or ""):
        raise SystemExit("--chave: letras minúsculas, números e _ (ex.: minha_fonte).")
    if chave in dp_destaques._FONTES_DE_FABRICA:
        raise SystemExit(f"A chave {chave!r} já é uma fonte do DarkPlanner — escolha outra.")
    fonte = TTFont(arquivo)
    nomes = fonte["name"]
    sub = str(nomes.getDebugName(2) or "Regular")
    estilo = estilo or ("Bold" if "bold" in sub.lower() else "Italic" if "italic" in sub.lower() else "Regular")
    if estilo not in ("Bold", "Regular", "Italic"):
        raise SystemExit("--estilo: Bold, Regular ou Italic.")
    nome = nome or str(nomes.getDebugName(16) or nomes.getDebugName(1) or chave).strip()
    familia = "DP " + re.sub(r"^DP\s+", "", nome)
    for rec in list(nomes.names):
        if rec.nameID in (1, 16):
            rec.string = familia
        elif rec.nameID == 4:
            rec.string = f"{familia} {estilo}" if estilo != "Regular" else familia
        elif rec.nameID == 6:
            rec.string = re.sub(r"[^A-Za-z0-9-]", "", familia.replace(" ", "")) + "-" + estilo
    arq = f"{chave.replace('_', '-')}-{estilo}.ttf"
    os.makedirs(dp_destaques.FONTES_DIR, exist_ok=True)
    fonte.save(os.path.join(dp_destaques.FONTES_DIR, arq))
    cam = _arquivo_extras("fontes.json")
    d = _ler_json(cam)
    fs = d.setdefault("fontes", {})
    atual = fs.get(chave) or {"familia": familia, "arquivos": {}}
    atual["familia"] = familia
    atual["arquivos"][estilo] = arq
    fs[chave] = atual
    _gravar_json(cam, d)
    return {"chave": chave, "familia": familia, "estilo": estilo, "arquivo": arq}


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Ferramentas do 📘 Guia (extras do DarkPlanner)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verificar")
    p = sub.add_parser("miniaturas")
    p.add_argument("--refazer", nargs="*", default=[], help="ids que mudaram (apaga a miniatura antes)")
    p = sub.add_parser("listar")
    p.add_argument("tipo")
    p = sub.add_parser("som")
    p.add_argument("arquivo")
    p.add_argument("--categoria", default="meus")
    p.add_argument("--nome", default="")
    p = sub.add_parser("fonte")
    p.add_argument("arquivo")
    p.add_argument("--chave", required=True)
    p.add_argument("--nome", default="")
    p.add_argument("--estilo", default="")
    a = ap.parse_args(argv)
    if a.cmd == "verificar":
        r = verificar()
        for e in r["erros"]:
            print("❌", e)
        for e in r["avisos"]:
            print("⚠ ", e)
        if r["faltando_miniatura"]:
            print(f"🖼  {len(r['faltando_miniatura'])} miniatura(s) faltando — rode:  python dp_guia.py miniaturas")
            for f in r["faltando_miniatura"][:30]:
                print("    ", f)
        if not any(r.values()):
            print("✔ Tudo certo.")
        return 1 if r["erros"] else 0
    if a.cmd == "miniaturas":
        print(miniaturas(a.refazer) or "Nenhuma miniatura faltando.")
    elif a.cmd == "listar":
        print("\n".join(listar(a.tipo)))
    elif a.cmd == "som":
        it = adicionar_som(a.arquivo, a.categoria, a.nome)
        print(f"✔ Som {it['id']} ({it['dur']}s, pico em {it['pico']}s) — reinicie o site ou clique 🔄 Reler os extras no 📘 Guia.")
    elif a.cmd == "fonte":
        it = adicionar_fonte(a.arquivo, a.chave, a.nome, a.estilo)
        print(f"✔ Fonte {it['familia']} ({it['estilo']}) — use \"tipografia\": {{\"fonte\": \"{it['chave']}\"}} num destaque.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
