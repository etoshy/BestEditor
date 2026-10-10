"""
Diagnóstico pós-export: "por que o vídeo final não ficou igual à telinha do Estúdio?"

Roda sozinho no fim de toda montagem (e em /job/<id>/download-diagnostico?refazer=1)
e escreve `jobs/<id>/diagnostico_export.txt` (+ `diagnostico_export.json`).

Junta três fontes:
  1. a FOTO DA TELINHA (`previa_snapshot.json`): o Estúdio, ao clicar em Montar,
     passa a telinha por vários momentos e anota o que ela mostrava — o clipe de cada
     trecho, a letra/tamanho/linhas/posição de cada destaque, o fundo e o escurecimento,
     que clipe estava em cada janela das cenas, a legenda, o filtro;
  2. o que a MONTAGEM fez (`montagem_relatorio.json` + `job["fixacao_previa"]`): de onde
     veio cada clipe (o da telinha fixado pelo link, ou uma busca nova — e por quê), o
     tamanho/quebra/fonte que o export calculou, a cor do fundo das cenas…;
  3. MEDIÇÃO no vídeo pronto: tira quadros do vídeo final nos mesmos momentos e compara
     com o clipe do trecho (é o mesmo clipe? ficou mais escuro? que take está em cada
     janela da cena?) e pergunta ao libass qual arquivo de fonte ele realmente usou.

Nada aqui muda o vídeo — só explica. Tudo é tolerante a falha: o que não der pra medir
vira "não deu pra conferir".
"""
from __future__ import annotations

import datetime
import glob
import io
import json
import math
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

ORCAMENTO_S = 150  # tempo máximo medindo quadros (vídeos longos: mede o que der)

# ------------------------------------------------------------------ utilidades de imagem/vídeo


def _quadro(video: str, t: float, w: int = 192, h: int = 108):
    """Quadro do vídeo no segundo t, reduzido (PIL RGB) — ou None."""
    from PIL import Image
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", video, "-frames:v", "1",
                            "-vf", f"scale={w}:{h}:flags=area", "-f", "image2pipe", "-vcodec", "png", "-"],
                           capture_output=True, timeout=40)
        if r.returncode != 0 or not r.stdout:
            return None
        return Image.open(io.BytesIO(r.stdout)).convert("RGB")
    except Exception:  # noqa: BLE001
        return None


def _duracao(video: str) -> Optional[float]:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                           capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:  # noqa: BLE001
        return None


def _resolucao(video: str) -> Optional[Tuple[int, int]]:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", video], capture_output=True, text=True, timeout=30)
        w, h = r.stdout.strip().split(",")[:2]
        return int(w), int(h)
    except Exception:  # noqa: BLE001
        return None


def _luz(im) -> Optional[float]:
    """Luz típica do quadro (mediana do cinza, 0-255) — pouco afetada por texto branco."""
    if im is None:
        return None
    from PIL import ImageStat
    return float(ImageStat.Stat(im.convert("L")).median[0])


def _vetor(im, w: int = 32, h: int = 18) -> Optional[List[float]]:
    if im is None:
        return None
    return list(im.convert("L").resize((w, h)).tobytes())


def _parecido(a, b) -> Optional[float]:
    """Correlação (-1..1) entre dois quadros — mede se é a MESMA imagem, sem ligar
    pra brilho/contraste (escurecer não muda o resultado)."""
    va, vb = _vetor(a), _vetor(b)
    if not va or not vb:
        return None
    n = len(va)
    ma, mb = sum(va) / n, sum(vb) / n
    da = [x - ma for x in va]
    db = [x - mb for x in vb]
    num = sum(x * y for x, y in zip(da, db))
    den = math.sqrt(sum(x * x for x in da) * sum(y * y for y in db))
    if den < 1e-6:
        return 1.0 if abs(ma - mb) < 12 else 0.0  # duas telas lisas
    return num / den


def _recorte(im, rect: List[float]):
    """rect = [x, y, w, h] em fração da tela."""
    if im is None:
        return None
    W, H = im.size
    x, y, w, h = rect
    box = (int(max(0, x) * W), int(max(0, y) * H), int(min(1, x + w) * W), int(min(1, y + h) * H))
    if box[2] - box[0] < 4 or box[3] - box[1] < 4:
        return None
    return im.crop(box)


def _cobrir(im, aspecto: float):
    """Como o ffmpeg põe um clipe numa janela (cover: escala e corta o meio)."""
    if im is None:
        return None
    W, H = im.size
    if W / H > aspecto:
        nw = int(H * aspecto)
        return im.crop(((W - nw) // 2, 0, (W - nw) // 2 + nw, H))
    nh = int(W / aspecto)
    return im.crop((0, (H - nh) // 2, W, (H - nh) // 2 + nh))


def _num_ids(*textos: Optional[str]) -> set:
    out = set()
    for t in textos:
        for m in re.findall(r"(\d{3,})", str(t or "")):
            out.add(m)
    return out


def _fmt_t(t: Optional[float]) -> str:
    if t is None:
        return "?"
    m, s = divmod(max(0.0, float(t)), 60)
    return f"{int(m)}:{s:04.1f}"


def _pct(x: float) -> str:
    return f"{x * 100:+.0f}%"


# ------------------------------------------------------------------ o que a telinha faz com a luz (aproximação)
_ESCURECE_PREVIA = {  # fundo do destaque -> luz que sobra na telinha (int = 1)
    "escurecer": lambda i: 1 - 0.35 * i, "desfoque_escuro": lambda i: 0.75 * (1 - 0.3 * i), "flash": lambda i: 1 - 0.15 * i,
    "midia": lambda i: 1 - 0.3 * i,
}
_CSS_BRILHO = re.compile(r"brightness\(([\d.]+)\)")


_SIMULAVEIS = {"nenhum", "escurecer", "desfoque_escuro", "flash", "vinheta", "gradiente", "painel", "desfoque", "pb", "granulado"}


def _simular_previa(clipe, foto: Dict[str, Any]):
    """O quadro do clipe com o que a telinha põe por cima (camadas pretas/gradientes
    dos fundos dos destaques e o brightness() do filtro CSS). None = a telinha cobre
    a cena com algo que não dá pra simular (cartaz, grade, cor sólida…)."""
    from PIL import Image
    if clipe is None:
        return None, []
    im = clipe.convert("RGB")
    W, H = im.size
    porque = []
    for d in foto.get("destaques") or []:
        fd = d.get("fundo") or {}
        fid, i = fd.get("id") or "nenhum", float(fd.get("intensidade") or 1)
        if fid not in _SIMULAVEIS:
            return None, [f"fundo '{fid}' (não simulável)"]
        alfa = None
        if fid in _ESCURECE_PREVIA:
            k = _ESCURECE_PREVIA[fid](i)
            alfa = Image.new("L", (W, H), int(round((1 - k) * 255)))
        elif fid == "vinheta":
            R = math.hypot(W / 2, H / 2)
            alfa = Image.new("L", (W, H))
            alfa.putdata([int(max(0.0, (math.hypot(x + .5 - W / 2, y + .5 - H / 2) / R - 0.4) / 0.6) * 0.7 * 255 * i) for y in range(H) for x in range(W)])
        elif fid == "gradiente":
            alfa = Image.new("L", (W, H))
            alfa.putdata([int(max(0.0, (y / H - 0.35) / 0.65) * 0.82 * 255 * i) for y in range(H) for _x in range(W)])
        elif fid == "painel":
            alfa = Image.new("L", (W, H))
            alfa.putdata([int(0.62 * 255 * i) if x < W * 0.46 else 0 for _y in range(H) for x in range(W)])
        if alfa is not None:
            im = Image.composite(Image.new("RGB", (W, H)), im, alfa)
            porque.append(f"fundo '{fid}' do destaque")
    m = _CSS_BRILHO.search(foto.get("filtro_css") or "")
    if m:
        k = float(m.group(1))
        im = im.point(lambda v: min(255, int(v * k)))
        porque.append(f"filtro {foto.get('filtro_css')}")
    return im, porque


def _luz_esperada_previa(foto: Dict[str, Any]) -> Tuple[float, List[str]]:
    fator, porque = 1.0, []
    for d in foto.get("destaques") or []:
        fd = d.get("fundo") or {}
        f = _ESCURECE_PREVIA.get(fd.get("id"))
        if f:
            k = f(float(fd.get("intensidade") or 1))
            fator *= k
            porque.append(f"fundo '{fd.get('id')}' do destaque ({_pct(k - 1)})")
    m = _CSS_BRILHO.search(foto.get("filtro_css") or "")
    if m:
        fator *= float(m.group(1))
        porque.append(f"filtro {foto.get('filtro_css')}")
    return fator, porque


# ------------------------------------------------------------------ diagnóstico


class _Achados:
    def __init__(self):
        self.itens: List[Dict[str, Any]] = []

    def add(self, nivel: str, area: str, onde: str, o_que: str, causa: str = "", fazer: str = "", **extra):
        self.itens.append({"nivel": nivel, "area": area, "onde": onde, "o_que": o_que, "causa": causa, "fazer": fazer, **extra})


def _destaques_do_job(job: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Os destaques como a montagem recebeu (com o fundo padrão do projeto)."""
    lista = job.get("destaques") or []
    pad = (job.get("editor_defaults") or {}).get("hl_fundo") or {}
    if not pad.get("fundo"):
        return list(lista)
    out = []
    for d in lista:
        if not d.get("fundo") and not d.get("sem_fundo"):
            d = dict(d, fundo=pad["fundo"], **({"fundo_cor": pad["fundo_cor"]} if pad.get("fundo_cor") and not d.get("fundo_cor") else {}),
                     **({"fundo_int": pad["fundo_int"]} if pad.get("fundo_int") is not None and d.get("fundo_int") is None else {}))
        out.append(d)
    return out


def _fontes_do_libass(job_dir: str, W: int, H: int) -> Dict[str, str]:
    """Pergunta ao próprio libass que arquivo ele escolheu pra cada fonte pedida nos .ass
    da montagem (destaques e legendas)."""
    import dp_destaques
    from video_assembler import _escape_path_for_ffmpeg_filter
    achadas: Dict[str, str] = {}
    arquivos = [p for p in glob.glob(os.path.join(job_dir, "**", "*.ass"), recursive=True)][:6]
    for ass in arquivos:
        try:
            dur = 1.0
            with open(ass, encoding="utf-8") as f:
                tempos = re.findall(r"^Dialogue: \d+,([\d:.]+),([\d:.]+)", f.read(), re.M)
            if tempos:
                def _s(x):
                    h, m, s = x.split(":")
                    return int(h) * 3600 + int(m) * 60 + float(s)
                dur = min(1800.0, max(_s(b) for _a, b in tempos) + 0.5)
            vf = f"ass='{_escape_path_for_ffmpeg_filter(ass)}':fontsdir='{_escape_path_for_ffmpeg_filter(dp_destaques.FONTES_DIR)}'"
            r = subprocess.run(["ffmpeg", "-v", "verbose", "-f", "lavfi", "-i", f"color=black:s={W // 4 * 2}x{H // 4 * 2}:r=1:d={dur:.1f}",
                                "-vf", vf, "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
            for m in re.finditer(r"fontselect: \((.+?), (\d+), (\d+)\) -> (.+)", r.stderr):
                achadas[f"{m.group(1)} (peso {m.group(2)}{', itálico' if m.group(3) != '0' else ''})"] = m.group(4).strip()
        except Exception:  # noqa: BLE001
            continue
    return achadas


def gerar(job_id: str, job: Dict[str, Any], job_dir: str, video: str) -> str:
    t_ini = time.time()
    import dp_destaques
    import dp_fundos
    A = _Achados()
    rel = {}
    try:
        with open(os.path.join(job_dir, "montagem_relatorio.json"), encoding="utf-8") as f:
            rel = json.load(f)
    except (OSError, ValueError):
        pass
    snap = {}
    try:
        with open(os.path.join(job_dir, "previa_snapshot.json"), encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, ValueError):
        pass
    cfg = rel.get("config") or {}
    res = _resolucao(video) or (cfg.get("W"), cfg.get("H"))
    W, H = int(res[0] or 1920), int(res[1] or 1080)
    trechos_rel = {t["trecho"]: t for t in rel.get("trechos") or []}
    segs = job.get("video_segments") or job.get("pending_segments") or []
    fixacao = {m["trecho"]: m for m in job.get("fixacao_previa") or []}
    fotos = [f for f in snap.get("fotos") or [] if "erro" not in f]
    snap_trechos = {t["trecho"]: t for t in snap.get("trechos") or []}
    dur_final = _duracao(video)
    dur_narr = rel.get("duracao_narracao") or (segs[-1]["end"] if segs else None)
    tem_cortes = any(c.get("resolved_path") for c in job.get("cutaway_suggestions") or [])

    # ---------------------------------------------------------------- 0. sem foto da telinha
    if not snap:
        A.add("info", "geral", "—", "Sem a foto da telinha (previa_snapshot.json): o diagnóstico compara só com o que estava salvo no servidor.",
              "A montagem foi disparada fora do Estúdio novo, ou por uma versão antiga da página.",
              "Monte de novo pelo botão 🎬 Montar vídeo do Estúdio pra ter a comparação completa.")

    # ---------------------------------------------------------------- 1. duração
    if dur_final and dur_narr and not tem_cortes and abs(dur_final - float(dur_narr)) > 0.6:
        A.add("alto", "tempo", "vídeo inteiro", f"O vídeo final tem {dur_final:.1f}s e a narração {float(dur_narr):.1f}s.",
              "Algum pedaço saiu com duração diferente da planejada — tudo depois dele fica deslocado (cenas/destaques fora do lugar).",
              "Veja a lista de pedaços no fim deste arquivo (esperado × real).")
    for p in rel.get("pedacos") or []:
        if p.get("real") is not None and p.get("esperado") and abs(p["real"] - p["esperado"]) > 0.15:
            A.add("medio", "tempo", f"pedaço {p['pedaco']}", f"durou {p['real']:.2f}s, o plano era {p['esperado']:.2f}s.",
                  "Clipe/efeito/cena que encurtou ou alongou depois do ajuste.", "")

    # ---------------------------------------------------------------- 2. clipes de cada trecho
    linhas_clipes: List[str] = []
    cortados: List[Tuple[int, int]] = []
    for i, sg in enumerate(segs, start=1):
        tr = trechos_rel.get(i, {})
        org = tr.get("origem") or {}
        fx = fixacao.get(i) or {}
        st = snap_trechos.get(i) or {}
        url_tela = st.get("url_na_telinha") or fx.get("video_previa")
        modo = org.get("modo") or "?"
        onde = f"trecho {i} ({_fmt_t(sg.get('start'))}–{_fmt_t(sg.get('end'))}) “{sg.get('query', '')}”"
        linhas_clipes.append(f"  Trecho {i:>3} {_fmt_t(sg.get('start'))}–{_fmt_t(sg.get('end'))}  [{sg.get('provider')}] “{sg.get('query', '')}”")
        linhas_clipes.append(f"        telinha: {url_tela or '(sem prévia)'}")
        linhas_clipes.append(f"        vídeo:   {modo} — {org.get('link') or ', '.join(os.path.basename(a) for a in org.get('arquivos') or []) or '?'}")
        if fx.get("motivo"):
            linhas_clipes.append(f"        fixação: {fx['motivo']}" + (" — mas o link NÃO baixou na montagem" if modo == "previa_nao_baixou_busca_nova" else ""))
        if modo == "previa_nao_baixou_busca_nova":
            A.add("alto", "clipe", onde, "Clipe TROCADO: o clipe da telinha não baixou na hora de montar e entrou o resultado de uma busca nova.",
                  f"Erro ao baixar o link da prévia: {' '.join(str(org.get('erro_previa') or '?').split())}",
                  "Confira se o servidor do banco (ex.: Anime Pexels local) estava ligado; ou escolha o clipe à mão (🔍 Ver opções → usar).")
        elif modo == "busca_nova" and url_tela and not st.get("escolhido"):
            A.add("alto", "clipe", onde, "Clipe provavelmente TROCADO: a telinha mostrava um clipe, mas a montagem fez uma busca nova.",
                  fx.get("motivo") or "o trecho não foi fixado no clipe da prévia",
                  "Atualize a prévia do trecho (🔍 Buscar) ou escolha o clipe à mão pra ele ficar fixo.")
        elif modo.startswith("busca_nova") and not url_tela:
            A.add("info", "clipe", onde, "O trecho não tinha prévia na telinha; o vídeo usou uma busca nova.", fx.get("motivo") or "", "")
        if org.get("completado_com_outra_cena") and not sg.get("clipes_extra"):
            A.add("medio", "clipe", onde, f"Entrou mais de um clipe no trecho ({len(org.get('arquivos') or [])}): o clipe era curto e foi completado com OUTRA cena.",
                  "Clipe escolhido à mão mais curto que o trecho é completado com outra cena da busca (a telinha mostra o clipe repetindo).",
                  "Encurte o trecho, escolha um clipe mais longo, ou use \"completar_trecho_curto\" nas configurações.")
        ids_tela = _num_ids(fx.get("link_previa"), url_tela, (st.get("preview") or {}).get("result_url"))
        ids_video = _num_ids(org.get("link"), *(org.get("arquivos") or []))
        if modo == "clipe_da_previa" and ids_tela and ids_video and not (ids_tela & ids_video):
            A.add("medio", "clipe", onde, "O link fixado não parece ser o mesmo clipe da telinha (os números de ID não batem).",
                  f"telinha: {sorted(ids_tela)[:3]}  ×  vídeo: {sorted(ids_video)[:3]}", "Confira o trecho no vídeo final.")
        if st and st.get("query") is not None and sg.get("query") and " ".join(str(st["query"]).split()) != " ".join(str(sg["query"]).split()):
            A.add("medio", "clipe", onde, "A busca do trecho na telinha era diferente da que foi montada.", f"“{st['query']}” × “{sg['query']}”", "")
        q = int(tr.get("corta_quadros_inicio") or 0)
        if q and url_tela and not st.get("img"):
            cortados.append((i, q))
    if cortados:
        qs = sorted({q for _i, q in cortados})
        A.add("info", "clipe", f"{len(cortados)} trecho(s)", f"O vídeo pula os {'/'.join(map(str, qs))} primeiros quadros de cada clipe (≈{qs[0] / 30:.2f}s); a telinha toca o clipe desde o começo — por isso a cena pode parecer \"adiantada\" um pouquinho.",
              "Opção ✂ (cortar quadros do início) da barra de cima do Estúdio.", "Ponha 0 se quiser o começo exato do clipe.")
    if (cfg.get("trim_position") or "start") != "start":
        A.add("alto", "clipe", "todos os trechos", f"clip_trim_position = \"{cfg.get('trim_position')}\": o vídeo pega o clipe do MEIO/aleatório, a telinha mostra desde o começo.",
              "Configuração clip_trim_position no site_config.json.", "Volte para \"start\" pra o vídeo bater com a telinha.")

    # ---------------------------------------------------------------- 3. destaques: fonte, tamanho, quebra, posição, fundo
    destaques_job = {str(d.get("id")): d for d in _destaques_do_job(job)}
    vistos = set()
    linhas_hl: List[str] = []
    for foto in fotos:
        for dh in foto.get("destaques") or []:
            did = str(dh.get("id"))
            if did in vistos or did not in destaques_job or dh.get("faltou_desenhar"):
                continue
            vistos.add(did)
            d = destaques_job[did]
            try:
                med = dp_destaques.medidas_texto(d, W, H)
            except Exception as exc:  # noqa: BLE001
                A.add("info", "destaque", did, f"Não consegui calcular as medidas do export: {exc}")
                continue
            onde = f"destaque “{(dh.get('texto') or '')[:40]}” ({_fmt_t(d.get('start'))})"
            fam_tela = (dh.get("familia") or "").split(",")[0].strip().strip("'\"")
            tam_tela = float(dh.get("tamanho_rel") or 0)
            tam_vid = med["tam_px"] / H
            l_tela = [l for l in dh.get("linhas") or []]
            l_vid = med["linhas"]
            linhas_hl.append(f"  {onde}")
            linhas_hl.append(f"        telinha: fonte {fam_tela or '?'} · letra {tam_tela * 100:.1f}% da altura · {len(l_tela)} linha(s): {' / '.join(l_tela)}")
            linhas_hl.append(f"        vídeo:   fonte {med['fonte']} · letra {tam_vid * 100:.1f}% da altura · {len(l_vid)} linha(s): {' / '.join(l_vid)}")
            if dh.get("fonte_carregada") is False:
                A.add("alto", "fonte", onde, f"A fonte {fam_tela} NÃO estava carregada na telinha: o navegador desenhou com outra fonte (a do sistema).",
                      "O arquivo da fonte (/dp-fonte/...) não carregou a tempo ou falhou.", "Recarregue o Estúdio (Ctrl+F5) e confira a telinha antes de montar.")
            if fam_tela and fam_tela.lower() != med["fonte"].lower():
                A.add("alto", "fonte", onde, f"FONTE DIFERENTE: telinha “{fam_tela}” × vídeo “{med['fonte']}”.",
                      "O estilo/fonte do destaque mudou entre a telinha e a montagem.", "Escolha a fonte no destaque (campo Fonte) e monte de novo.")
            if tam_tela and abs(tam_vid / tam_tela - 1) > 0.08:
                A.add("medio", "fonte", onde, f"Tamanho da letra diferente: vídeo {_pct(tam_vid / tam_tela - 1)} em relação à telinha.",
                      "A telinha encolhe o texto pra caber na tela (manterNaTela) de um jeito que o export reproduz aproximado.", "")
            norm = lambda ls: [re.sub(r"\s+", " ", x).strip().lower() for x in ls]  # noqa: E731
            if l_tela and norm(l_tela) != norm(l_vid):
                A.add("medio", "fonte", onde, f"Quebra de linha diferente: telinha {len(l_tela)} linha(s) × vídeo {len(l_vid)} linha(s).",
                      "A largura das letras medida pelo navegador e pelo export diferiu (fonte não carregada, zoom do navegador, texto editado).", "")
            rect = dh.get("rect") or [0, 0, 0, 0]
            cx_t, cy_t = rect[0] + rect[2] / 2, rect[1] + rect[3] / 2
            x_v, y_v = med["x"] / W, med["y"] / H
            an = med["an"]
            cx_v = x_v + (med["largura_txt"] / W / 2 if an in (1, 4, 7) else -med["largura_txt"] / W / 2 if an in (3, 6, 9) else 0)
            alt_v = med["altura_txt"] / H
            cy_v = y_v + (alt_v / 2 if an in (7, 8, 9) else -alt_v / 2 if an in (1, 2, 3) else 0)
            if abs(cx_t - cx_v) > 0.06 or abs(cy_t - cy_v) > 0.07:
                A.add("medio", "posição", onde, f"Posição diferente: centro do texto na telinha ({cx_t:.0%}, {cy_t:.0%}) × vídeo ({cx_v:.0%}, {cy_v:.0%}).", "", "")
            if (dp_destaques.estilo(d.get("estilo")) or {}).get("coreografia", {}).get("interna") == "brilho" and d.get("interna") != "nenhuma":
                A.add("info", "fonte", onde, "O estilo tem brilho pulsando em volta das letras (\"interna: brilho\") — só aparece no vídeo, a telinha não desenha.",
                      "", "No destaque, mude \"Animação interna\" pra nenhuma se não quiser o brilho.")
            # fundo / escurecimento
            fid, _cor, inten = dp_fundos.resolver(d, (dp_destaques.estilo(d.get("estilo")) or {}).get("cena") or {}, cfg.get("paleta"))
            ft = dh.get("fundo") or {}
            if ft and ft.get("id") != fid:
                A.add("alto", "escurecimento", onde, f"Fundo do destaque diferente: telinha “{ft.get('id')}” × vídeo “{fid}”.",
                      "O fundo padrão do projeto e o do estilo foram resolvidos de jeitos diferentes.", "Escolha o fundo no próprio destaque.")
            elif ft and abs(float(ft.get("intensidade") or 1) - inten) > 0.05:
                A.add("medio", "escurecimento", onde, f"Intensidade do fundo diferente: telinha {float(ft.get('intensidade') or 1):.2f} × vídeo {inten:.2f}.", "", "")
            linhas_hl.append(f"        fundo:   telinha {ft.get('id', '?')} ({float(ft.get('intensidade') or 1):.2f}) · vídeo {fid} ({inten:.2f})")

    # fonte que o libass realmente usou
    fontes_ass = _fontes_do_libass(job_dir, W, H)
    for pedida, usada in fontes_ass.items():
        familia = pedida.split(" (")[0]
        if familia.startswith("DP ") and not re.sub(r"[^a-z]", "", usada.lower()).startswith(re.sub(r"[^a-z]", "", familia.lower())):
            A.add("alto", "fonte", "vídeo inteiro", f"O libass NÃO achou a fonte “{familia}” e usou “{usada}” no lugar.",
                  "Arquivo da fonte faltando em assets/fonts/dp ou nome interno diferente.", "Reinstale a pasta assets/fonts/dp do site.")

    # ---------------------------------------------------------------- 4. cenas (templates): janelas e fundo
    import cenas_dp
    import dp_cores
    pal = dp_cores.normalizar(cfg.get("paleta")) if dp_cores.vale_para(cfg.get("paleta"), "cenas") else None
    linhas_cena: List[str] = []
    for g in rel.get("grupos_cena") or []:
        a, b, tid = g["de"], g["ate"], g["template"]
        campos = (trechos_rel.get(a) or {}).get("campos_cena") or (segs[a - 1].get("template_campos") if a - 1 < len(segs) else {}) or {}
        estilos = cenas_dp.fundos_do_template(tid)
        estilo = campos.get("_fundo") if campos.get("_fundo") in (estilos + sorted(dp_fundos.IDS_CENA)) else estilos[0]
        cor_fundo = campos.get("_fundo_cor") if re.fullmatch(r"#[0-9a-fA-F]{6}", str(campos.get("_fundo_cor") or "")) else None
        tom = cenas_dp.fundo_tom(tid, estilo, cor_fundo, pal)
        nome = (cenas_dp.template(tid) or {}).get("nome", tid)
        onde = f"cena “{nome}” (trechos {a}–{b})"
        fts = [f for f in fotos if f.get("cena") and f["cena"].get("de") == a]
        css = fts[0]["cena"].get("fundo_css") if fts else None
        linhas_cena.append(f"  {onde}")
        linhas_cena.append(f"        fundo telinha: {fts[0]['cena'].get('fundo_id') if fts else '?'} {css or ''}")
        linhas_cena.append(f"        fundo vídeo:   {estilo} " + (f"tingido com {tom}" if tom else "(cor própria do fundo)"))
        if fts and fts[0]["cena"].get("fundo_id") and fts[0]["cena"]["fundo_id"] != estilo:
            A.add("alto", "cena", onde, f"Fundo da cena diferente: telinha “{fts[0]['cena']['fundo_id']}” × vídeo “{estilo}”.", "", "Escolha o fundo da cena no trecho.")
        lay = cenas_dp.layout_para(tid, W, H)
        if float(lay.get("escurecer") or 0):
            A.add("info", "escurecimento", onde, f"Esta cena escurece os takes em tela cheia em {float(lay['escurecer']):.2f} no vídeo (a telinha não mostra isso).", "", "")
        for f in fts:
            for jn in f["cena"].get("janelas") or []:
                if jn.get("vazio"):
                    A.add("medio", "cena", onde, f"Na telinha a janela do take {jn['take']} (trecho {jn['trecho']}) estava VAZIA em {_fmt_t(f['t'])} — o vídeo mostra o clipe que a montagem achou.",
                          "O trecho estava sem prévia na telinha.", "Busque a prévia do trecho antes de montar.")

    # ---------------------------------------------------------------- 5. medição nos quadros do vídeo final
    medicoes: List[str] = []
    cache_q: Dict[Tuple[str, float], Any] = {}

    def q(v, t):
        k = (v, round(t, 2))
        if k not in cache_q:
            cache_q[k] = _quadro(v, t)
        return cache_q[k]

    amostras = fotos or [{"t": (s["start"] + s["end"]) / 2, "trecho": k + 1} for k, s in enumerate(segs)]
    escuros = []
    for f in amostras:
        if time.time() - t_ini > ORCAMENTO_S:
            medicoes.append("  (parei de medir: tempo esgotado — o resto não foi conferido)")
            break
        t = float(f["t"])
        i = int(f.get("trecho") or 0)
        tr = trechos_rel.get(i) or {}
        clip = tr.get("clipe_normalizado")
        sg = segs[i - 1] if 0 < i <= len(segs) else None
        if not sg:
            continue
        fv = q(video, t)
        if fv is None:
            continue
        cena = f.get("cena")
        if cena:  # janelas: que take está em cada uma?
            for jn in cena.get("janelas") or []:
                rect = jn.get("rect")
                if not rect or rect[2] * rect[3] < 0.02:
                    continue
                pedaco = _recorte(fv, rect)
                if pedaco is None:
                    continue
                notas = {}
                for k in range(cena["de"], cena["ate"] + 1):
                    c2 = (trechos_rel.get(k) or {}).get("clipe_normalizado")
                    s2 = segs[k - 1] if k - 1 < len(segs) else None
                    if not c2 or not os.path.exists(c2) or not s2:
                        continue
                    tc = t - float(s2["start"])
                    if tc < 0:
                        continue
                    notas[k] = _parecido(pedaco, _cobrir(q(c2, tc), rect[2] * W / max(1e-6, rect[3] * H)))
                if notas:
                    melhor = max(notas, key=lambda k: notas[k] if notas[k] is not None else -2)
                    esperado = jn.get("trecho")
                    medicoes.append(f"  {_fmt_t(t)} cena janela {jn.get('take')}: esperado trecho {esperado}, parece trecho {melhor} "
                                    + " ".join(f"[{k}:{(v if v is not None else float('nan')):.2f}]" for k, v in sorted(notas.items())))
                    if esperado in notas and melhor != esperado and (notas[melhor] or 0) > 0.45 and (notas[melhor] or 0) - (notas.get(esperado) or 0) > 0.2:
                        A.add("alto", "cena", f"cena trechos {cena['de']}–{cena['ate']} em {_fmt_t(t)}",
                              f"Janela {jn.get('take')} da cena mostra o clipe do TRECHO {melhor}, mas na telinha era o do trecho {esperado}.",
                              "Ordem/tempo dos takes diferente entre a telinha e a montagem.", "")
                    elif esperado in notas and (notas.get(esperado) or 0) < 0.25 and max((v or 0) for v in notas.values()) < 0.25:
                        A.add("medio", "cena", f"cena trechos {cena['de']}–{cena['ate']} em {_fmt_t(t)}",
                              f"Janela {jn.get('take')}: o conteúdo não parece com nenhum clipe da cena — confira se a mídia do trecho {esperado} é a da telinha.", "", "")
            continue
        if not clip or not os.path.exists(clip):
            continue
        fc = q(clip, max(0.0, t - float(sg["start"])))
        sim = _parecido(fv, fc)
        lz_v, lz_c = _luz(fv), _luz(fc)
        razao = (lz_v + 4) / (lz_c + 4) if lz_v is not None and lz_c is not None else None
        if fotos:
            sim_prev, porque = _simular_previa(fc, f)
            lz_p = _luz(sim_prev)
            esperado = (lz_p + 4) / (lz_c + 4) if lz_p is not None and lz_c is not None else None
        else:
            esperado, porque = 1.0, []
        medicoes.append(f"  {_fmt_t(t)} trecho {i}: mesmo clipe? {sim if sim is None else round(sim, 2)} · luz vídeo/clipe {razao if razao is None else round(razao, 2)}"
                        f" (telinha ≈ {esperado if esperado is None else round(esperado, 2)}{': ' + ', '.join(porque) if porque else ''})")
        if esperado is None:
            continue
        if sim is not None and sim < 0.2 and not f.get("destaques"):
            A.add("medio", "clipe", f"trecho {i} em {_fmt_t(t)}", "O quadro do vídeo final não parece o clipe do trecho nesse momento (cena fora do lugar?).",
                  "Transição/entrada longa, efeito pesado, ou tempo deslocado por um pedaço com duração errada.", "")
        if razao is not None and lz_c is not None and lz_c > 18:
            dif = razao / max(0.05, esperado)
            if dif < 0.85:
                escuros.append((t, i, dif, porque))
            elif dif > 1.2:
                A.add("medio", "escurecimento", f"trecho {i} em {_fmt_t(t)}", f"Vídeo MAIS CLARO que a telinha ({_pct(dif - 1)}).", "", "")
    pior: Dict[int, Tuple[float, int, float, List[str]]] = {}
    for item in escuros:  # um aviso por trecho (o momento mais escuro)
        if item[1] not in pior or item[2] < pior[item[1]][2]:
            pior[item[1]] = item
    for (t, i, dif, porque) in sorted(pior.values())[:20]:
        causas = []
        filtro = cfg.get("filtro_cor")
        if filtro and filtro != "original":
            causas.append(f"filtro de cor “{filtro}” (no vídeo é uma cadeia do ffmpeg, na telinha um filtro CSS aproximado)")
        sg = segs[i - 1]
        if sg.get("efeito"):
            causas.append(f"efeito do trecho “{sg['efeito']}”")
        tr_i = trechos_rel.get(i) or {}
        if tr_i.get("cena"):
            causas.append(f"cena “{tr_i['cena']}”")
        if porque:
            causas.append("no vídeo o mesmo tratamento saiu mais forte que na telinha (" + ", ".join(porque) + ")")
        A.add("alto" if dif < 0.7 else "medio", "escurecimento", f"trecho {i} em {_fmt_t(t)}",
              f"Vídeo MAIS ESCURO que a telinha: {_pct(dif - 1)} de luz em relação ao que a telinha mostrava.",
              "; ".join(causas) or "algo escureceu só no vídeo (filtro/efeito/tratamento que a telinha não mostra)",
              "Se for o fundo “escurecer” de um destaque: a partir da v84_20 o export escurece igual à telinha (multiplica, não subtrai). Diminua a intensidade do fundo ou troque o filtro de cor.")

    # ---------------------------------------------------------------- 6. legenda
    leg_fotos = [f["legenda"] for f in fotos if f.get("legenda")]
    if leg_fotos and (job.get("legendas") or {}).get("ativa"):
        lf = leg_fotos[0]
        fam = (lf.get("familia") or "").split(",")[0].strip().strip("'\"")
        cfg_leg = job.get("legendas") or {}
        if lf.get("fonte_carregada") is False:
            A.add("alto", "fonte", "legenda", f"A fonte da legenda ({fam}) não estava carregada na telinha.", "", "Recarregue o Estúdio.")
        if cfg_leg.get("tamanho") and lf.get("tamanho_rel") and abs(float(lf["tamanho_rel"]) / float(cfg_leg["tamanho"]) - 1) > 0.1:
            A.add("info", "fonte", "legenda", f"Tamanho da legenda: telinha {float(lf['tamanho_rel']) * 100:.1f}% da altura, configuração {float(cfg_leg['tamanho']) * 100:.1f}%.", "", "")

    # ---------------------------------------------------------------- escrever
    unicos, vistos_k = [], set()
    for x in A.itens:
        k = (x["area"], re.sub(r" em \d+:[\d.]+$", "", x["onde"]), x["o_que"][:60])
        if k not in vistos_k:
            vistos_k.add(k)
            unicos.append(x)
    A.itens = unicos
    ordem = {"alto": 0, "medio": 1, "info": 2}
    A.itens.sort(key=lambda x: (ordem.get(x["nivel"], 3), x["area"]))
    rot = {"alto": "🔴 ALTO ", "medio": "🟡 MÉDIO", "info": "ℹ INFO "}
    L: List[str] = []
    L.append("DIAGNÓSTICO DO VÍDEO EXPORTADO × TELINHA DO ESTÚDIO")
    L.append("=" * 64)
    L.append(f"Projeto: {job_id}   Gerado em: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    L.append(f"Vídeo: {os.path.basename(video)}  {W}x{H}  duração {dur_final or 0:.2f}s  (narração {float(dur_narr or 0):.2f}s)")
    L.append(f"Foto da telinha: {'sim, ' + str(len(fotos)) + ' momentos (' + str(snap.get('quando', '')) + ')' if snap else 'NÃO'}"
             + (f"   Timeline: {snap.get('timeline')}" if snap.get("timeline") else ""))
    L.append(f"Filtro de cor: {cfg.get('filtro_cor') or 'original'}   Cortar quadros do início: {snap.get('corta_quadros', '?') if snap else '?'}"
             f"   Bordas: {snap.get('bordas', '?') if snap else '?'}")
    L.append("")
    n_alto = sum(1 for x in A.itens if x["nivel"] == "alto")
    n_medio = sum(1 for x in A.itens if x["nivel"] == "medio")
    L.append(f"RESUMO: {n_alto} problema(s) sério(s), {n_medio} diferença(s) média(s), {len(A.itens) - n_alto - n_medio} observação(ões).")
    if not A.itens:
        L.append("Nada fora do lugar encontrado: clipes, textos, fundos e luz bateram com a telinha.")
    L.append("")
    for k, x in enumerate(A.itens, 1):
        L.append(f"{k:>3}. {rot.get(x['nivel'], x['nivel'])} [{x['area']}] {x['onde']}")
        L.append(f"      {x['o_que']}")
        if x.get("causa"):
            L.append(f"      Causa provável: {x['causa']}")
        if x.get("fazer"):
            L.append(f"      O que fazer: {x['fazer']}")
    L.append("")
    L.append("-" * 64)
    L.append("CLIPES — o que a telinha mostrava × o que entrou no vídeo")
    L += linhas_clipes or ["  (sem dados)"]
    if linhas_hl:
        L.append("")
        L.append("-" * 64)
        L.append("DESTAQUES — fonte, tamanho e quebra de linha")
        L += linhas_hl
    if fontes_ass:
        L.append("")
        L.append("Fontes que o libass usou no vídeo:")
        L += [f"  {k} -> {v}" for k, v in fontes_ass.items()]
    if linhas_cena:
        L.append("")
        L.append("-" * 64)
        L.append("CENAS (templates)")
        L += linhas_cena
    if medicoes:
        L.append("")
        L.append("-" * 64)
        L.append("MEDIÇÕES NO VÍDEO FINAL (mesmo clipe? 1 = idêntico, 0 = nada a ver · luz vídeo/clipe: 1 = igual, 0,5 = metade)")
        L += medicoes
    if rel.get("pedacos"):
        L.append("")
        L.append("-" * 64)
        L.append("PEDAÇOS JUNTADOS (duração esperada × real)")
        L += [f"  {p['pedaco']:>3}: {p.get('esperado')}s × {p.get('real')}s  transição depois: {p.get('transicao_depois')}" for p in rel["pedacos"]]
    L.append("")
    L.append(f"(diagnóstico levou {time.time() - t_ini:.1f}s)")
    texto = "\n".join(L) + "\n"
    caminho = os.path.join(job_dir, "diagnostico_export.txt")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(texto)
    try:
        with open(os.path.join(job_dir, "diagnostico_export.json"), "w", encoding="utf-8") as f:
            json.dump({"achados": A.itens, "fontes_libass": fontes_ass, "W": W, "H": H}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return caminho
