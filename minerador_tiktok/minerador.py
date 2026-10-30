#!/usr/bin/env python3
"""
minerador.py — minera vídeos do TikTok e manda os bons pro BestEditor (narration_video_site).

Fluxo de cada vídeo do feed:
  1. números brutos (curtidas, comentários, salvos, compartilhamentos, duração, hashtags, descrição)
  2. pré-filtro barato (config "filtro") — nada de IA aqui
  3. passou: 5 quadros do vídeo (JPEG pequeno) + os comentários (ordenados por curtidas)
  4. (opcional) Moondream local só pra DESCARTAR barato: jogo/gravação de tela, vídeo só de texto…
  5. TRIAGEM no Claude barato (Haiku): nota 0-10, qual MODELO DE VÍDEO do site serve, o momento forte
  6. só os aprovados: ROTEIRO no Claude bom (Sonnet) — no MESMO formato da aba ✍ Roteiro de comentário do site:
     gancho / história / final (idioma do post + português), 10 ganchos, 10 finais com pergunta, títulos, descrição,
     hashtags, o que a IA entendeu, o que conferir + 2º ÂNGULO + o que tirar dos comentários + plano de edição
  7. envia pro site (📥 aparece em ✍ Roteiro de comentário, com o link pronto pro 💬 curto) e grava .txt/.jsonl por hora

Modelos de vídeo do projeto que a triagem escolhe:
  comentario       — clipe viral + narração comentando (o principal)
  explicativo      — o clipe mostra algo curioso que dá pra EXPLICAR ("por que…?")
  noticia          — o clipe é de um fato recente que virou notícia (estilo Laestro)
  explicador_poker — mão/jogada de poker que rende o 🎬 Explicador animado (simulador 2D) no Poker Uncovered
  documentario     — história grande de uma pessoa/evento que rende um vídeo longo (estilo Stu Ungar)
  descartar

Requisitos (mesma pasta do tiktok_algo.py):
    pip install playwright anthropic pillow
    playwright install chromium
    export ANTHROPIC_API_KEY=...    (Windows: set ANTHROPIC_API_KEY=...)
    # Moondream é OPCIONAL (visao.backend "ollama" ou "hf"; padrão "nenhum" — o Claude já vê os quadros)

Uso:
    python minerador.py                     # roda sem parar
    python minerador.py --horas 3
    python minerador.py --sem-claude        # só coleta + filtro (teste sem gastar)
    python minerador.py --reenviar          # manda de novo pro site o que ficou em pendentes_site.jsonl
"""
import argparse
import base64
import io
import json
import random
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

VERSAO = "2.0"

# ---------------------------------------------------------------------------------------------------- config
PADRAO = {
    "filtro": {"min_curtidas": 20000, "min_comentarios": 200, "duracao_min_s": 5, "duracao_max_s": 90,
               "hashtags_bloqueadas": ["ad", "publi", "parceria", "tiktokshop", "sponsored", "giveaway"],
               "palavras_bloqueadas_descricao": ["link na bio", "link in bio", "cupom", "promo code", "use code"],
               "razao_comentarios_curtidas_boa": 0.008, "razao_compart_curtidas_boa": 0.02, "razao_salvos_curtidas_boa": 0.03,
               "curtidas_viral": 500000, "pontuacao_minima": 2},
    "visao": {"backend": "nenhum", "modelo_ollama": "moondream", "url_ollama": "http://localhost:11434", "revisao_hf": None,
              "fracoes_quadros": [0.08, 0.3, 0.5, 0.7, 0.92], "largura_quadro": 640,
              "descartar_se": ["Is this a video game or a screen recording?", "Is the image mostly text on a plain background?"]},
    "claude": {"modelo_triagem": "claude-haiku-5-5", "modelo_roteiro": "claude-sonnet-5-5", "max_tokens_roteiro": 8000,
               "enviar_quadros": True, "nota_minima": 7, "max_triagens_por_hora": 60, "max_roteiros_por_hora": 20,
               "lingua_post": "en", "tags_chatterbox": True,
               "modelos_aceitos": ["comentario", "explicativo", "noticia", "explicador_poker", "documentario"],
               "nichos_desejados": ["momentos engraçados", "animais", "esportes", "histórias emocionantes", "reviravoltas", "curiosidades", "poker"],
               "estilo_canal": "Canal de shorts de comentário: narração com IA, frases curtas, gancho forte nos 3 primeiros segundos, "
                               "cortes a cada 2-4 s, pergunta final que gera discussão."},
    "coleta": {"interesses": ["Animais", "Comédia", "Esportes"], "comentarios_candidato": 60, "videos_por_sessao": 80,
               "pausa_entre_sessoes_s": 120, "persona": "persona_minerador.json",
               "mostrar_navegador": True},
    "site": {"url": "http://localhost:5050", "enviar": True},
    "saida": {"pasta": "minerados", "intervalo_min": 60},
}

MODELOS = {
    "comentario": "💬 curto de comentário (clipe + narração comentando)",
    "explicativo": "📚 curto explicativo (o clipe mostra algo curioso que dá pra explicar)",
    "noticia": "📰 curto de notícia (um fato recente)",
    "explicador_poker": "🃏 explicador animado de poker (mão no simulador 2D)",
    "documentario": "🎞 documentário (história grande pra vídeo longo)",
    "descartar": "🗑 não serve",
}
LINGUAS = {"en": "ENGLISH", "pt": "BRAZILIAN PORTUGUESE", "es": "SPANISH", "it": "ITALIAN", "fr": "FRENCH", "de": "GERMAN"}
TAGS_VOZ = ("gasp", "laugh", "chuckle", "sigh", "surprised", "sarcastic", "dramatic", "whispering", "happy")


def _mesclar(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _mesclar(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return out


def carregar_config(caminho):
    p = Path(caminho)
    bruto = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    cfg = _mesclar(PADRAO, bruto)
    # config antigo (v1): "modelo" único, "idioma_roteiro", "max_chamadas_por_hora"
    c = cfg["claude"]
    if c.get("modelo") and "modelo_roteiro" not in bruto.get("claude", {}):
        c["modelo_roteiro"] = c["modelo"]
    if c.get("idioma_roteiro"):
        c["lingua_post"] = {"inglês": "en", "ingles": "en", "english": "en", "português": "pt", "portugues": "pt",
                            "espanhol": "es"}.get(str(c["idioma_roteiro"]).lower(), c["lingua_post"])
    if c.get("max_chamadas_por_hora"):
        c["max_roteiros_por_hora"] = c["max_chamadas_por_hora"]
    return cfg


def mmss(seg):
    if seg is None:
        return "?"
    seg = int(round(float(seg)))
    return f"{seg // 60}:{seg % 60:02d}"


# ---------------------------------------------------------------------------------------------------- 2. pré-filtro
def prefiltro(d, f):
    """(passou, pontos, motivos). O feed não mostra visualizações, então as RAZÕES entre as métricas são o sinal:
    muito comentário por curtida = discussão (ótimo pra pergunta final); muito compartilhamento = história que as pessoas
    mandam pros amigos; muito salvo = curiosidade/utilidade (bom pro explicativo)."""
    likes, coms = d.get("curtidas_num") or 0, d.get("comentarios_num") or 0
    shares, salvos = d.get("compartilh_num") or 0, d.get("salvos_num") or 0
    dur = d.get("duracao_s") or 0
    tags = {t.lower().lstrip("#") for t in d.get("hashtags", [])}
    desc = (d.get("descricao") or "").lower()

    if likes < f["min_curtidas"]:
        return False, 0, [f"poucas curtidas ({likes})"]
    if coms < f["min_comentarios"]:
        return False, 0, [f"poucos comentários ({coms})"]
    if dur and not (f["duracao_min_s"] <= dur <= f["duracao_max_s"]):
        return False, 0, [f"duração fora da faixa ({dur}s)"]
    bloq = tags & {t.lower() for t in f["hashtags_bloqueadas"]}
    if bloq:
        return False, 0, [f"hashtag bloqueada: {', '.join(sorted(bloq))}"]
    pal = [w for w in f.get("palavras_bloqueadas_descricao", []) if w.lower() in desc]
    if pal:
        return False, 0, [f"propaganda na descrição: {pal[0]}"]

    pontos, motivos = 0, []
    r_com = coms / likes if likes else 0
    r_sha = shares / likes if likes else 0
    r_sal = salvos / likes if likes else 0
    if r_com >= f["razao_comentarios_curtidas_boa"]:
        pontos += 1; motivos.append(f"discussão alta (coment/curt={r_com:.3f})")
    if r_sha >= f["razao_compart_curtidas_boa"]:
        pontos += 1; motivos.append(f"muito compartilhado (comp/curt={r_sha:.3f})")
    if r_sal >= f["razao_salvos_curtidas_boa"]:
        pontos += 1; motivos.append(f"muito salvo (salv/curt={r_sal:.3f})")
    if likes >= f["curtidas_viral"]:
        pontos += 1; motivos.append(f"viral ({likes} curtidas)")
    if dur and dur <= 30:
        pontos += 1; motivos.append("curto (≤30 s), momento único")
    d["razoes"] = {"coment_curt": round(r_com, 4), "comp_curt": round(r_sha, 4), "salv_curt": round(r_sal, 4)}
    return pontos >= f["pontuacao_minima"], pontos, motivos


# ---------------------------------------------------------------------------------------------------- 3. quadros + comentários
def _js(tk, corpo):
    return corpo.replace("__H__", tk.JS_HELPERS)


JS_SEEK = """async (t) => {__H__
  const v = ativo('video'); if (!v) return null; v.pause();
  await new Promise(r => { const ok = () => { v.removeEventListener('seeked', ok); r(); };
    v.addEventListener('seeked', ok); v.currentTime = t; setTimeout(r, 3000); });
  return v.currentTime; }"""
JS_PLAY = "() => {__H__ const v = ativo('video'); if (v) v.play(); }"
JS_VIDEO = "() => {__H__ return ativo('video'); }"


def _jpeg(png_bytes, largura):
    """PNG do print → JPEG pequeno (5 quadros em PNG cheio custam muito mais tokens e não ajudam a IA)."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        if im.width > largura:
            im = im.resize((largura, round(im.height * largura / im.width)))
        b = io.BytesIO()
        im.save(b, "JPEG", quality=82)
        return b.getvalue()
    except Exception:  # sem Pillow: manda o PNG mesmo
        return None


def capturar_quadros(page, tk, dur, pasta, vid, vcfg):
    quadros = []
    dur = dur or 10
    for i, fr in enumerate(vcfg["fracoes_quadros"]):
        t = max(0.3, dur * fr)
        real = page.evaluate(_js(tk, JS_SEEK), t)
        time.sleep(0.5)
        el = page.evaluate_handle(_js(tk, JS_VIDEO)).as_element()
        if not el:
            continue
        try:
            png = el.screenshot()
        except Exception as e:  # noqa: BLE001
            print(f"   (falha no print do quadro {i + 1}: {e})")
            continue
        jpg = _jpeg(png, vcfg.get("largura_quadro", 640))
        caminho = pasta / f"{vid}_q{i + 1}.{'jpg' if jpg else 'png'}"
        caminho.write_bytes(jpg or png)
        quadros.append({"arquivo": str(caminho), "tipo": "image/jpeg" if jpg else "image/png",
                        "tempo_s": round(real if real is not None else t, 1)})
    page.evaluate(_js(tk, JS_PLAY))
    return quadros


def organizar_comentarios(coms, n):
    """Os mais curtidos primeiro, sem repetidos; marca PERGUNTAS (viram gancho/dúvida que o roteiro responde)."""
    vistos, out = set(), []
    for c in sorted(coms or [], key=lambda c: -(_n(c.get("curtidas")) + 3 * _n(c.get("respostas")))):
        t = " ".join(str(c.get("texto") or "").split())
        k = t.lower()[:80]
        if len(t) < 3 or k in vistos:
            continue
        vistos.add(k)
        out.append(dict(c, texto=t[:400], pergunta="?" in t))
        if len(out) >= n:
            break
    return out


def _n(v):
    if isinstance(v, (int, float)):
        return v
    s = str(v or "0").strip().lower().replace(",", ".")
    mult = 1
    if s.endswith("k") or s.endswith("mil"):
        mult, s = 1000, s.rstrip("kmil ")
    elif s.endswith("m"):
        mult, s = 1_000_000, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return 0


# ---------------------------------------------------------------------------------------------------- 4. Moondream (opcional, só descarte)
_HF = None


def _hf_modelo(vcfg):
    global _HF
    if _HF is None:
        import torch
        from transformers import AutoModelForCausalLM
        kw = {"trust_remote_code": True, "device_map": "cuda" if torch.cuda.is_available() else "cpu"}
        if vcfg.get("revisao_hf"):
            kw["revision"] = vcfg["revisao_hf"]
        print("Carregando Moondream2 (Hugging Face)...")
        _HF = AutoModelForCausalLM.from_pretrained("vikhyatk/moondream2", **kw)
    return _HF


def _ollama(vcfg, img_path, prompt):
    b64 = base64.b64encode(Path(img_path).read_bytes()).decode()
    corpo = json.dumps({"model": vcfg["modelo_ollama"], "prompt": prompt, "images": [b64], "stream": False,
                        "options": {"temperature": 0}}).encode()
    req = urllib.request.Request(vcfg["url_ollama"].rstrip("/") + "/api/generate", corpo, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())["response"].strip()


def descarte_visual(quadros, vcfg):
    """None = segue; texto = motivo pra descartar. Pergunta só no quadro do meio (é um filtro, não uma análise)."""
    if vcfg.get("backend") in (None, "", "nenhum") or not quadros or not vcfg.get("descartar_se"):
        return None
    q = quadros[len(quadros) // 2]
    try:
        for p in vcfg["descartar_se"]:
            if vcfg["backend"] == "hf":
                from PIL import Image
                r = _hf_modelo(vcfg).query(Image.open(q["arquivo"]), p + " Answer yes or no.")["answer"]
            else:
                r = _ollama(vcfg, q["arquivo"], p + " Answer only yes or no.")
            if str(r).strip().lower().startswith("yes"):
                return p
    except Exception as e:  # noqa: BLE001  (Moondream fora do ar não para o minerador)
        print(f"     (Moondream: {e})")
    return None


# ---------------------------------------------------------------------------------------------------- 5/6. Claude
def _o(props):
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


S, N, B = {"type": "string"}, {"type": "number"}, {"type": "boolean"}
LS = {"type": "array", "items": S}
OP = _o({"en": S, "pt": S})

TRIAGEM_SCHEMA = _o({
    "nota": N, "modelo": {"type": "string", "enum": list(MODELOS)}, "motivo": S, "nicho": S, "tom": S,
    "resumo_historia": S, "momento_forte": _o({"tempo_s": N, "descricao": S}),
    "depende_de_fala": B, "propaganda": B,
})
ROTEIRO_SCHEMA = _o({
    "entendi_pt": S, "tom": S,
    "gancho": OP, "corpo": OP, "final": OP,
    "ganchos": {"type": "array", "items": OP}, "perguntas": {"type": "array", "items": OP},
    "titulos": {"type": "array", "items": OP}, "descricao": S, "hashtags": LS, "conferir_pt": LS,
    "angulo": S,
    "angulo_b": _o({"angulo": S, "gancho": OP, "corpo": OP, "final": OP}),
    "reviravolta": S, "detalhe_escondido": _o({"tempo_s": N, "alvo_en": S, "descricao": S}),
    "discussao_principal": S,
    "comentarios_relevantes": {"type": "array", "items": _o({"indice": N, "tipo": {"type": "string", "enum": [
        "pergunta", "discussao", "contexto", "piada", "linguagem", "reclamacao"]}, "uso": S})},
    "plano_edicao": {"type": "array", "items": _o({"tempo_clipe": S, "acao": {"type": "string", "enum": [
        "corte", "zoom", "seta", "circulo", "freeze", "texto_na_tela", "camera_lenta", "som"]}, "alvo": S, "detalhe": S})},
    "assunto_explicativo": S, "ideia_longa": S, "alertas": LS,
})

TRIAGEM_SYS = (
    "You screen TikTok clips for a creator who makes YouTube videos with these models: " +
    "; ".join(f"'{k}' = {v}" for k, v in MODELOS.items()) +
    ". Judge ONLY what the frames, the description and the comments show. Score 'nota' 0-10 = how good a SHORT this becomes "
    "in the chosen model (a clear strong moment, a twist or a decision people argue about, emotion, a curious thing to "
    "explain). 10 = obvious viral story; 7 = solid; ≤4 = no clear moment. 'modelo': comentario for most viral moments; "
    "explicativo when the interesting part is HOW/WHY something works (an animal behavior, an object, a trick); noticia when "
    "it is a recent real event; explicador_poker for a poker hand worth breaking down; documentario when it points to a big "
    "story of a person or event (it still may get a short); descartar for ads, low-effort trends, dances/lip-sync without a "
    "story, or anything you cannot understand without hearing the speech. 'depende_de_fala' = true when the story is in the "
    "spoken words and the frames/comments do not reveal it. All text fields in Brazilian Portuguese.")


def _regra_lingua(lp, tags):
    L = LINGUAS.get(lp, "ENGLISH")
    t = (f" You may add 1 to 3 voice tags at natural moments, from: {', '.join(f'[{x}]' for x in TAGS_VOZ)} (read by "
         "Chatterbox Turbo); never other brackets." if lp == "en" and tags else " No brackets or tags.")
    return f"'en' fields in {L} (the language of the post){t} 'pt' fields = the same in natural Brazilian Portuguese (no tags)."


def roteiro_sys(modelo, lp, tags):
    if modelo == "explicativo":
        formula = ("FORMULA (explainer short): GANCHO = a surprising QUESTION or claim about the thing on screen ('Why does this "
                   "bird…?'); CORPO = the common belief → the real explanation step by step, concrete well-established facts "
                   "only; FINAL = the most surprising detail in one line + a short question for the comments.")
    elif modelo == "noticia":
        formula = ("FORMULA (news short): GANCHO = the most shocking fact of the event; CORPO = what happened, quickly, then the "
                   "other side / a counterpoint; FINAL = one strong line + a question about what people think. Facts NOT "
                   "confirmed by the clip go to 'conferir_pt'.")
    else:
        formula = ("FORMULA (commentary short): GANCHO = OPEN WITH THE MOST SHOCKING OR EMOTIONAL MOMENT (curiosity, "
                   "contradiction, surprising claim; under 15 words); CORPO = REVEAL THE STORY QUICKLY, in order, the twist, "
                   "plus the narrator's own point of view (that commentary is the creative value); FINAL = DELIVER THE FINAL "
                   "MOMENT IN ONE STRONG LINE + ONE question with more than one possible answer, about the decision or the "
                   "judgment — use the argument from the comments when there is one.")
    return (
        "You write scripts for short vertical videos (YouTube Shorts / TikTok / Reels) over a viral clip. " + formula +
        " Short spoken sentences, one flowing paragraph when read aloud (~2.6 words per second), length close to the clip "
        "(usually 15-35 s). Never invent names, numbers or reasons; context that only comes from comments is unconfirmed → "
        "'conferir_pt'/'alertas'. Rewrite everything in your own words. If the images contradict the description, trust the "
        "images. " + _regra_lingua(lp, tags) +
        " ALSO: 'ganchos' = 10 alternative hooks (first = the one used), 'perguntas' = 10 alternative final lines (final moment + "
        "question; first = the one used), 'titulos' = 5 short honest titles, 'descricao' (short, in the post language, ending "
        "with a credit line to the original creator), 3-6 'hashtags', 'angulo' = the name of your angle in Portuguese, "
        "'angulo_b' = a SECOND full script with a really different angle (e.g. A suspense/twist → B the controversial decision; "
        "A funny → B heartwarming). 'detalhe_escondido' = something easy to miss worth an arrow/circle ('alvo_en' = the object "
        "in English so it can be tracked; empty strings if none). 'comentarios_relevantes' = indices of the comments you used and "
        "how. 'plano_edicao' = visual changes every 2-4 s with clip times (m:ss). 'assunto_explicativo' = if this clip could ALSO "
        "be an explainer, the question it explains (else ''). 'ideia_longa' = if there is a bigger story for a long video "
        "(documentary), one sentence (else ''). 'entendi_pt' = the story as you understood it (1-3 sentences). Portuguese for "
        "every non-script field.")


def montar_dados(d, comentarios, triagem=None):
    L = ["== TIKTOK CLIP ==",
         f"Author: {d.get('autor_nome')} ({d.get('autor_href')})",
         f"Duration: {d.get('duracao_s')} s",
         f"Likes: {d.get('curtidas')} | Comments: {d.get('comentarios')} | Saves: {d.get('salvos')} | Shares: {d.get('compartilh')}",
         f"Ratios: {d.get('razoes')}",
         f"Description: {d.get('descricao')}",
         f"Hashtags: {' '.join('#' + t for t in d.get('hashtags', []))}", "",
         "== COMMENTS (index | likes | replies | ? = question | text) — the most liked first =="]
    for i, c in enumerate(comentarios):
        L.append(f"[{i}] {c.get('curtidas')} | {c.get('respostas', 0)} resp | {'?' if c.get('pergunta') else ' '} | {c['texto']}")
    if triagem:
        L += ["", "== SCREENING ==", json.dumps({k: triagem.get(k) for k in ("modelo", "tom", "resumo_historia", "momento_forte")},
                                                ensure_ascii=False)]
    return "\n".join(L)


class Claude:
    def __init__(self, ccfg):
        import anthropic
        self.cli = anthropic.Anthropic()  # usa ANTHROPIC_API_KEY
        self.c = ccfg
        self.uso = {"entrada": 0, "saida": 0, "cache_lido": 0}

    def _img(self, quadros):
        out = []
        if self.c.get("enviar_quadros"):
            for q in quadros:
                out.append({"type": "text", "text": f"Frame at {mmss(q['tempo_s'])}:"})
                out.append({"type": "image", "source": {"type": "base64", "media_type": q.get("tipo", "image/png"),
                                                        "data": base64.b64encode(Path(q["arquivo"]).read_bytes()).decode()}})
        return out

    def _chamar(self, modelo, sistema, conteudo, schema, max_tokens):
        r = self.cli.messages.create(
            model=modelo, max_tokens=max_tokens,
            system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],  # o system se repete: cache
            messages=[{"role": "user", "content": conteudo}],
            extra_body={"output_config": {"format": {"type": "json_schema", "schema": schema}}})  # JSON sempre válido
        u = getattr(r, "usage", None)
        if u:
            self.uso["entrada"] += getattr(u, "input_tokens", 0) or 0
            self.uso["saida"] += getattr(u, "output_tokens", 0) or 0
            self.uso["cache_lido"] += getattr(u, "cache_read_input_tokens", 0) or 0
        if getattr(r, "stop_reason", "") == "refusal":
            return None
        txt = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        return json.loads(txt[txt.find("{"): txt.rfind("}") + 1])

    def triagem(self, d, comentarios, quadros):
        return self._chamar(self.c["modelo_triagem"], TRIAGEM_SYS,
                            self._img(quadros) + [{"type": "text", "text": montar_dados(d, comentarios[:25])}], TRIAGEM_SCHEMA, 1200)

    def roteiro(self, d, comentarios, quadros, triagem):
        sis = roteiro_sys(triagem.get("modelo"), self.c["lingua_post"], self.c.get("tags_chatterbox", True))
        extra = f"\n\nChannel style: {self.c['estilo_canal']}"
        return self._chamar(self.c["modelo_roteiro"], sis,
                            self._img(quadros) + [{"type": "text", "text": montar_dados(d, comentarios, triagem) + extra}],
                            ROTEIRO_SCHEMA, self.c["max_tokens_roteiro"])


# ---------------------------------------------------------------------------------------------------- 7. saída: site + .txt
def _miniatura(quadros):
    """O quadro do meio, pequeno, pra aparecer na aba ⛏ do site."""
    if not quadros:
        return ""
    q = quadros[len(quadros) // 2]
    try:
        b = Path(q["arquivo"]).read_bytes()
        return q.get("tipo", "image/jpeg") + ";" + base64.b64encode(b).decode() if len(b) < 400_000 else ""
    except OSError:
        return ""


def item_para_site(it, lp):
    """O formato que o 📥 importar da aba ✍ Roteiro de comentário entende."""
    d, t, r = it["video"], it["triagem"], it["roteiro"]
    return {"versao": VERSAO, "origem": "minerador", "link": d.get("link"), "autor": d.get("autor_nome"), "autor_href": d.get("autor_href"),
            "titulo": (r.get("titulos") or [{}])[0].get("pt") or (t.get("resumo_historia") or "")[:80],
            "historia": t.get("resumo_historia") or r.get("entendi_pt") or "", "lingua_post": lp, "modelo": t.get("modelo"),
            "nota": t.get("nota"), "motivo": t.get("motivo"), "nicho": t.get("nicho"), "duracao_s": d.get("duracao_s"),
            "metricas": {k: d.get(k) for k in ("curtidas", "comentarios", "salvos", "compartilh")}, "razoes": d.get("razoes"),
            "momento_forte": t.get("momento_forte"), "comentarios": it["comentarios"], "res": r,
            "coletado_em": d.get("coletado_em"), "video_id": d.get("video_id"), "miniatura": _miniatura(it.get("quadros"))}


def enviar_site(scfg, pacote):
    if not scfg.get("enviar"):
        return False
    req = urllib.request.Request(scfg["url"].rstrip("/") + "/curtos/roteiro-comentario/importar",
                                 json.dumps({"itens": [pacote]}, ensure_ascii=False).encode("utf-8"),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return bool(json.loads(r.read()).get("ok"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"     (site fora do ar — guardei pra --reenviar: {e})")
        return False


def formatar_item(n, it):
    d, t, r, coms = it["video"], it["triagem"], it["roteiro"], it["comentarios"]
    L = ["=" * 78, f"#{n}  NOTA {t.get('nota')}/10  |  {MODELOS.get(t.get('modelo'), t.get('modelo'))}  |  {t.get('nicho')}  |  tom: {r.get('tom') or t.get('tom')}",
         "=" * 78, f"Link: {d.get('link')}",
         f"Autor: {d.get('autor_nome')}  |  {d.get('curtidas')} curtidas  |  {d.get('comentarios')} coment.  |  {d.get('salvos')} salvos  |  "
         f"{d.get('compartilh')} compart.  |  {d.get('duracao_s')} s",
         f"Por que vale: {t.get('motivo')}", "", f"HISTÓRIA: {r.get('entendi_pt') or t.get('resumo_historia')}"]
    mf = t.get("momento_forte") or {}
    L.append(f"MOMENTO FORTE: {mmss(mf.get('tempo_s'))} - {mf.get('descricao')}")
    for rot, k in (("REVIRAVOLTA", "reviravolta"), ("DISCUSSÃO NOS COMENTÁRIOS", "discussao_principal"),
                   ("DÁ UM EXPLICATIVO", "assunto_explicativo"), ("IDEIA PRA VÍDEO LONGO", "ideia_longa")):
        if r.get(k):
            L.append(f"{rot}: {r[k]}")
    de = r.get("detalhe_escondido") or {}
    if de.get("descricao"):
        L.append(f"DETALHE ESCONDIDO: {mmss(de.get('tempo_s'))} - {de['descricao']} (alvo: {de.get('alvo_en')})")
    L += ["", "COMENTÁRIOS QUE AJUDAM:"]
    for cr in r.get("comentarios_relevantes", []):
        i = int(cr.get("indice", -1))
        if 0 <= i < len(coms):
            c = coms[i]
            L.append(f"  [{cr.get('tipo')}] ({c.get('curtidas')} curt, {c.get('respostas', 0)} resp) {c.get('usuario') or '?'}: \"{c['texto']}\"")
            L.append(f"      -> {cr.get('uso')}")
    for nome, a in ((r.get("angulo") or "A", r), ((r.get("angulo_b") or {}).get("angulo") or "B", r.get("angulo_b") or {})):
        if not (a.get("corpo") or {}).get("en"):
            continue
        L += ["", f"--- ROTEIRO: {nome} ---",
              " ".join(x for x in ((a.get(p) or {}).get("en", "") for p in ("gancho", "corpo", "final")) if x),
              "🇧🇷 " + " ".join(x for x in ((a.get(p) or {}).get("pt", "") for p in ("gancho", "corpo", "final")) if x)]
    L += ["", "OUTROS GANCHOS:"] + [f"  - {o.get('en')}" for o in (r.get("ganchos") or [])[1:6]]
    L += ["OUTROS FINAIS:"] + [f"  - {o.get('en')}" for o in (r.get("perguntas") or [])[1:6]]
    L += ["PLANO DE EDIÇÃO:"] + [f"  clipe {p.get('tempo_clipe', '?'):>5} | {str(p.get('acao', '')).upper():<13} | {p.get('alvo', '')} | {p.get('detalhe', '')}"
                                  for p in r.get("plano_edicao", [])]
    if r.get("alertas") or r.get("conferir_pt"):
        L += ["", "⚠ CONFERIR: " + " | ".join((r.get("conferir_pt") or []) + (r.get("alertas") or []))]
    L.append("")
    return "\n".join(L)


def salvar_lote(pasta, aprovados, stats, uso):
    agora = datetime.now()
    arq = pasta / f"{agora:%Y-%m-%d_%Hh%M}.txt"
    cab = [f"MINERAÇÃO {agora:%d/%m/%Y %H:%M}  (minerador {VERSAO})",
           f"Vistos: {stats['vistos']} | passaram no filtro: {stats['prefiltro']} | descartados pela visão: {stats['visao']} | "
           f"triagem: {stats['triagem']} | roteiros: {stats['roteiro']} | aprovados: {len(aprovados)} | enviados pro site: {stats['site']}",
           f"Tokens: entrada {uso['entrada']} · saída {uso['saida']} · cache {uso['cache_lido']}", ""]
    if not aprovados:
        cab.append("Nenhum vídeo aprovado neste período.")
    corpo = [formatar_item(i + 1, it) for i, it in enumerate(sorted(aprovados, key=lambda x: -(x["triagem"].get("nota") or 0)))]
    arq.write_text("\n".join(cab + corpo), encoding="utf-8")
    with open(pasta / "aprovados.jsonl", "a", encoding="utf-8") as f:
        for it in aprovados:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"\n>>> Salvo {arq} ({len(aprovados)} aprovados)\n")


def reenviar(pasta, scfg):
    pend = pasta / "pendentes_site.jsonl"
    if not pend.exists():
        print("Nada pendente."); return
    linhas = [l for l in pend.read_text(encoding="utf-8").splitlines() if l.strip()]
    sobra = [l for l in linhas if not enviar_site(dict(scfg, enviar=True), json.loads(l))]
    pend.write_text("\n".join(sobra) + ("\n" if sobra else ""), encoding="utf-8")
    print(f"Enviados {len(linhas) - len(sobra)} de {len(linhas)}.")


# ---------------------------------------------------------------------------------------------------- loop
def main():
    ap = argparse.ArgumentParser(description="Minerador de vídeos do TikTok → BestEditor")
    ap.add_argument("--config", default="config_minerador.json")
    ap.add_argument("--horas", type=float, default=0, help="tempo total (0 = sem limite)")
    ap.add_argument("--sem-claude", action="store_true", help="não chama a API (teste)")
    ap.add_argument("--headless", action="store_true", help="esconde o navegador (o padrão é mostrar; ou coleta.mostrar_navegador=false)")
    ap.add_argument("--mostrar", action="store_true", help="mostra o navegador mesmo com mostrar_navegador=false")
    ap.add_argument("--reenviar", action="store_true", help="manda pro site o que ficou pendente")
    args = ap.parse_args()

    cfg = carregar_config(args.config)
    f, vcfg, ccfg, kcfg, scfg, site = cfg["filtro"], cfg["visao"], cfg["claude"], cfg["coleta"], cfg["saida"], cfg["site"]
    pasta = Path(scfg["pasta"]); pasta.mkdir(exist_ok=True)
    if args.reenviar:
        return reenviar(pasta, site)

    from playwright.sync_api import sync_playwright
    import tiktok_algo as tk

    interesses = [i for i in kcfg.get("interesses", []) if i.strip()]
    if 0 < len(interesses) < 3:  # o TikTok exige no mínimo 3
        print(f"Aviso: {len(interesses)} interesse(s); o TikTok exige 3 — o popup será fechado e o feed fica generalista.")
        interesses = []
    kcfg["interesses"] = interesses
    print("Feed: " + (f"interesses {', '.join(interesses)}" if interesses else "generalista"))

    escondido = bool(args.headless) or (not kcfg.get("mostrar_navegador", True) and not args.mostrar)
    print("Navegador: " + ("escondido (headless)" if escondido else "visível"))
    parar = pasta / "PARAR"  # ⏹ o botão parar do site cria este arquivo: termina o vídeo atual, salva e sai
    if parar.exists():
        parar.unlink()
    pasta_q = pasta / "quadros"; pasta_q.mkdir(exist_ok=True)
    arq_vistos = pasta / "vistos.txt"
    vistos = set(arq_vistos.read_text().split()) if arq_vistos.exists() else set()
    brutos = open(pasta / "brutos.jsonl", "a", encoding="utf-8")
    ia = None if args.sem_claude else Claude(ccfg)
    uso_vazio = {"entrada": 0, "saida": 0, "cache_lido": 0}

    fim = time.time() + args.horas * 3600 if args.horas else None
    zera = lambda: {"vistos": 0, "prefiltro": 0, "visao": 0, "triagem": 0, "roteiro": 0, "site": 0}  # noqa: E731
    aprovados, stats = [], zera()
    ultimo_salvo = time.time()
    cont = {"triagem": 0, "roteiro": 0, "inicio": time.time()}

    def talvez_salvar(forcar=False):
        nonlocal aprovados, stats, ultimo_salvo
        if forcar or time.time() - ultimo_salvo >= scfg["intervalo_min"] * 60:
            salvar_lote(pasta, aprovados, stats, ia.uso if ia else uso_vazio)
            aprovados, stats, ultimo_salvo = [], zera(), time.time()

    try:
        with sync_playwright() as p:
            while (not fim or time.time() < fim) and not parar.exists():
                browser = p.chromium.launch(headless=escondido)
                kw = dict(locale="pt-BR", viewport={"width": 1366, "height": 850})
                persona = Path(kcfg["persona"]) if kcfg.get("persona") else None
                if persona and persona.exists():
                    kw["storage_state"] = str(persona)
                ctx = browser.new_context(**kw)
                page = ctx.new_page()
                tk.onboarding(page, {})
                tk.tratar_interesses(page, kcfg["interesses"])

                ultimo_id = None
                for _ in range(kcfg["videos_por_sessao"]):
                    if (fim and time.time() >= fim) or parar.exists():
                        break
                    talvez_salvar()
                    if time.time() - cont["inicio"] >= 3600:
                        cont.update(triagem=0, roteiro=0, inicio=time.time())

                    tk.checar_captcha(page)  # captcha: espera VOCÊ resolver na janela (não tenta burlar)
                    tk.tratar_interesses(page, kcfg["interesses"])
                    page.evaluate(tk.JS_EXPANDIR_DESC)
                    tk.pausa(0.4, 0.8)
                    d = page.evaluate(tk.JS_EXTRAIR_VIDEO)
                    vid = d.get("video_id")
                    if not vid or vid == ultimo_id:
                        tk.proximo_video(page); continue
                    ultimo_id = vid
                    if vid in vistos:
                        time.sleep(random.uniform(1, 2)); tk.proximo_video(page); continue

                    stats["vistos"] += 1
                    d["coletado_em"] = datetime.now().isoformat(timespec="seconds")
                    d["duracao_s"] = tk.duracao_da_barra(d["tempo_barra"]) or (round(d["duracao_tag"]) if d["duracao_tag"] else None)
                    d["link"] = f"https://www.tiktok.com{d['autor_href']}/video/{vid}" if d.get("autor_href") else None
                    for k in ("curtidas", "comentarios", "salvos", "compartilh"):
                        d[k + "_num"] = tk.num(d[k])

                    passou, pontos, motivos = prefiltro(d, f)
                    brutos.write(json.dumps(dict(d, filtro_passou=passou, filtro_pontos=pontos, filtro_motivos=motivos), ensure_ascii=False) + "\n")
                    brutos.flush()
                    vistos.add(vid)
                    with open(arq_vistos, "a") as fv:
                        fv.write(vid + "\n")

                    autor = (d.get("autor_nome") or "?")[:22]
                    if not passou:
                        print(f"  .  {autor:<22} {d.get('curtidas')} - {motivos[0] if motivos else 'pontuação baixa'}")
                        time.sleep(random.uniform(1.5, 3.5)); tk.proximo_video(page); continue

                    stats["prefiltro"] += 1
                    print(f"  +  {autor:<22} {d.get('curtidas')} - candidato ({pontos} pts: {'; '.join(motivos)})")
                    quadros = capturar_quadros(page, tk, d["duracao_s"], pasta_q, vid, vcfg)
                    motivo_v = descarte_visual(quadros, vcfg)
                    if motivo_v:
                        stats["visao"] += 1
                        print(f"     descartado pela visão: {motivo_v}")
                        tk.proximo_video(page); continue
                    comentarios = organizar_comentarios(tk.coletar_comentarios(page, kcfg["comentarios_candidato"]), kcfg["comentarios_candidato"])

                    if not ia or cont["triagem"] >= ccfg["max_triagens_por_hora"]:
                        tk.proximo_video(page); continue
                    cont["triagem"] += 1; stats["triagem"] += 1
                    try:
                        t = ia.triagem(d, comentarios, quadros)
                    except Exception as e:  # noqa: BLE001
                        print(f"     erro na triagem: {e}"); t = None
                    ok = (t and (t.get("nota") or 0) >= ccfg["nota_minima"] and t.get("modelo") in ccfg["modelos_aceitos"]
                          and not t.get("propaganda") and not t.get("depende_de_fala"))
                    if not ok:
                        if t:
                            print(f"     ✗ nota {t.get('nota')} · {t.get('modelo')}: {t.get('motivo')}")
                        tk.proximo_video(page); continue
                    print(f"     ✓ nota {t.get('nota')} · {MODELOS.get(t['modelo'])}: {t.get('motivo')}")
                    if cont["roteiro"] >= ccfg["max_roteiros_por_hora"]:
                        print("     (limite de roteiros/hora — fica só a triagem no brutos.jsonl)")
                        brutos.write(json.dumps({"video_id": vid, "triagem": t}, ensure_ascii=False) + "\n")
                        tk.proximo_video(page); continue
                    cont["roteiro"] += 1; stats["roteiro"] += 1
                    try:
                        r = ia.roteiro(d, comentarios, quadros, t)
                    except Exception as e:  # noqa: BLE001
                        print(f"     erro no roteiro: {e}"); r = None
                    if r:
                        it = {"video": d, "comentarios": comentarios, "triagem": t, "roteiro": r, "quadros": quadros}
                        aprovados.append(it)
                        pacote = item_para_site(it, ccfg["lingua_post"])
                        if enviar_site(site, pacote):
                            stats["site"] += 1; print("     📥 enviado pro site")
                        else:
                            with open(pasta / "pendentes_site.jsonl", "a", encoding="utf-8") as fp:
                                fp.write(json.dumps(pacote, ensure_ascii=False) + "\n")
                    tk.proximo_video(page)

                if persona:
                    ctx.storage_state(path=str(persona))
                browser.close()
                if (not fim or time.time() < fim) and not parar.exists():
                    print(f"Fim da sessão. Pausa de {kcfg['pausa_entre_sessoes_s']} s...")
                    for _ in range(int(kcfg["pausa_entre_sessoes_s"])):
                        if parar.exists():
                            break
                        time.sleep(1)
    except KeyboardInterrupt:
        print("\nInterrompido.")
    finally:
        if parar.exists():
            print("⏹ Parado pelo site.")
            parar.unlink()
        talvez_salvar(forcar=True)
        brutos.close()


if __name__ == "__main__":
    main()
