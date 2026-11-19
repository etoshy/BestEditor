"""💸 v84_425 — a aba "Economia de IA": liga/desliga cada atalho de economia, aplica o recomendado, volta como era antes e
testa tudo (com o erro pra copiar e o passo a passo do que falta instalar).

O recomendado (o que combinamos):
  🟠 texto (roteiro, revisão, checagem, TTS, thumbs/títulos, temas, formatos) pela ASSINATURA do Claude (Claude Code), Sonnet,
     com a API de reserva;
  🖥 IA local (Qwen no Ollama/LM Studio) nas buscas, Wikipedia e YouTube — e no juiz das cenas se tiver um Qwen com visão;
  💸 notas do texto bruto gravando o cache uma vez só (sempre ligado, não tem o que desligar).
"Voltar como era antes": tudo pela API (a chave), IA local desligada — o juiz visual continua DESLIGADO (o que mais gastava).
"""
from __future__ import annotations

import base64
import io
import time
from typing import Any, Dict, List, Optional

LOCAL_RECOMENDADO = ["buscas", "nova_busca", "wikipedia", "youtube_ordem", "youtube_momento", "sound_design"]
VISAO_RECOMENDADO = ["juiz", "juiz_manual"]

INSTRUCOES = {
    "claude": {
        "titulo": "🟠 Instalar o Claude Code (usa a sua assinatura do Claude)",
        "passos": [
            "Instale o Node.js (versão LTS) em https://nodejs.org — avance tudo no instalador.",
            "Feche e abra o PowerShell de novo e rode:  npm install -g @anthropic-ai/claude-code",
            "Rode:  claude  — ele abre o navegador pra você entrar com a SUA conta do Claude (Pro ou Max). Depois de entrar, "
            "digite  /exit  pra sair.",
            "Feche a janela do site (python app.py) e abra de novo — pra ele enxergar o programa novo.",
            "Volte aqui e clique em 🧪 Testar tudo.",
        ],
    },
    "chatgpt": {
        "titulo": "🟢 Instalar o Codex (usa a sua assinatura do ChatGPT)",
        "passos": [
            "Instale o Node.js (versão LTS) em https://nodejs.org, se ainda não tiver.",
            "No PowerShell:  npm install -g @openai/codex",
            "Rode:  codex login  — entre com a SUA conta do ChatGPT.",
            "Feche a janela do site (python app.py) e abra de novo.",
            "Volte aqui e clique em 🧪 Testar tudo. (No plano Go a cota do Codex é pequena — o Claude é a opção principal.)",
        ],
    },
    "local": {
        "titulo": "🖥 Instalar o Ollama e o Qwen (IA local, grátis)",
        "passos": [
            "Baixe e instale o Ollama em https://ollama.com/download (Windows). Ele fica rodando sozinho perto do relógio.",
            "No PowerShell, baixe o Qwen de texto:  ollama pull qwen2.5:7b  (uns 5 GB)",
            "Pro juiz das cenas (olha as imagens), baixe o Qwen com visão:  ollama pull qwen2.5vl:7b  (uns 6 GB)",
            "Já tem o Qwen no LM Studio? Abra o LM Studio → aba Developer → Start Server, e aqui no Endereço use  "
            "http://localhost:1234/v1  e o nome do modelo que aparece lá.",
            "Clique em 🧪 Testar tudo — ele mostra os modelos instalados; se o nome for outro, clique em “usar este”.",
        ],
    },
}


def estado() -> Dict[str, Any]:
    import ia_assinatura as ias
    import ia_local as il
    import ia_servico as ia
    c = ia.config()
    lc = il.config(c)
    return {"texto_via": c.get("texto_via") or "api", "assinatura_modelo": c.get("assinatura_modelo") or "sonnet",
            "assinatura_reserva_api": bool(c.get("assinatura_reserva_api", True)), "local": lc,
            "tem_claude": bool(ias.executavel("claude")), "tem_codex": bool(ias.executavel("chatgpt")),
            "tem_chave": bool(ia.chave(c)), "ia_ligada": bool(c.get("ativo")),
            "modos": ias.MODOS, "modelos_claude": ias.MODELOS_CLAUDE, "recursos_locais": il.RECURSOS_LOCAIS,
            "instrucoes": INSTRUCOES, "salvo_antes": bool(c.get("antes_economia")), "juiz_modo": juiz_modo(c),
            "juiz_modos": JUIZ_MODOS, "gasto_juiz": _gasto("juiz"),
            "juiz_curtos_modo": juiz_modo(c, "juiz_curtos"), "juiz_curtos_modos": JUIZ_CURTOS_MODOS}


def _gasto(recurso: str) -> Dict[str, Any]:
    import ia_servico as ia
    g = ia.gasto()
    r = (g.get("por_recurso") or {}).get(recurso) or {}
    return {"usd": float(r.get("usd") or 0), "chamadas": int(r.get("chamadas") or 0), "total": float(g.get("usd") or 0)}


JUIZ_CURTOS_MODOS = {"api": "🔑 na API (o padrão) — uns US$ 0,01 por curto",
                     "local": "🖥 no Qwen com visão (grátis; se ele falhar, fica o resultado da busca, sem gastar na API)",
                     "off": "⏸ desligado — fica o melhor resultado da busca que ainda não foi usado"}
JUIZ_MODOS = {"off": "⏸ desligado (o padrão) — fica o melhor resultado da busca que ainda não foi usado (sem repetir clipe)",
              "local": "🖥 no Qwen com visão (grátis; se ele falhar, o trecho fica com o resultado da busca, sem gastar na API)",
              "api": "🔑 na API (o que mais gasta — umas 10 imagens por trecho)"}


def juiz_modo(c: Dict[str, Any], rec: str = "juiz") -> str:
    """rec = "juiz" (vídeos longos) ou "juiz_curtos" (⚡ vídeos curtos)."""
    import ia_local as il
    if not (c.get("recursos") or {}).get(rec, rec == "juiz_curtos"):
        return "off"
    lc = il.config(c)
    if lc["ativo"] and rec in lc["recursos"] and (lc.get("modelo_visao") or "").strip():
        return "local"
    return "api"


def _campos_juiz(modo: str, c: Dict[str, Any], rec: str = "juiz") -> Dict[str, Any]:
    import ia_local as il
    lc = il.config(c)
    junto = ("juiz", "juiz_manual") if rec == "juiz" else ("juiz_curtos",)
    rec_local = [r for r in lc["recursos"] if r not in junto]
    so = [r for r in lc["so_local"] if r not in junto]
    if modo == "local":
        rec_local += list(junto)
        so += [rec]
    rs = dict(c.get("recursos") or {})
    rs[rec] = modo != "off"
    outro = "juiz_curtos" if rec == "juiz" else "juiz"
    rs["nova_busca"] = rs[rec] or bool(rs.get(outro, outro == "juiz_curtos"))  # a nova busca depende das notas de algum juiz
    return {"recursos": rs, "local": {"recursos": rec_local, "so_local": so, **({"ativo": True} if modo == "local" else {})}}


def salvar(campos: Dict[str, Any]) -> Dict[str, Any]:
    """Um interruptor por vez (a página salva na hora)."""
    import ia_servico as ia
    novos: Dict[str, Any] = {}
    for k in ("texto_via", "assinatura_modelo", "assinatura_reserva_api"):
        if k in campos:
            novos[k] = campos[k]
    if isinstance(campos.get("local"), dict):
        novos["local"] = campos["local"]
    if novos:
        ia.salvar_config(novos)
    if campos.get("juiz_modo") in JUIZ_MODOS:
        ia.salvar_config(_campos_juiz(campos["juiz_modo"], ia.config()))
    if campos.get("juiz_curtos_modo") in JUIZ_CURTOS_MODOS:
        ia.salvar_config(_campos_juiz(campos["juiz_curtos_modo"], ia.config(), "juiz_curtos"))
    return estado()


def recomendado() -> Dict[str, Any]:
    """Aplica o que combinamos (guarda como estava, pra 'voltar')."""
    import ia_local as il
    import ia_servico as ia
    c = ia.config()
    if not c.get("antes_economia"):
        ia.salvar_config({"antes_economia": {"texto_via": c.get("texto_via") or "api", "local": c.get("local") or {}}})
    lc = il.config(c)
    instalados = il.listar_modelos(c)
    visao = lc.get("modelo_visao") or next((m for m in instalados if "vl" in m.lower() and "qwen" in m.lower()), "")
    texto = lc.get("modelo") if (not instalados or lc.get("modelo") in instalados) else \
        next((m for m in instalados if "qwen" in m.lower() and "vl" not in m.lower()), lc.get("modelo"))
    ia.salvar_config({"texto_via": "claude", "assinatura_modelo": "sonnet", "assinatura_reserva_api": True,
                      "local": {"ativo": True, "modelo": texto, "modelo_visao": visao, "recursos": list(LOCAL_RECOMENDADO)}})
    # ⚖️ o juiz é o que mais gasta: desligado (dá pra ligar na aba, com o aviso — no Qwen com visão ou na API)
    ia.salvar_config(_campos_juiz("off", ia.config()))
    return estado()


def voltar() -> Dict[str, Any]:
    """Como era antes de hoje: tudo pela API, IA local desligada."""
    import ia_servico as ia
    c = ia.config()
    ia.salvar_config({"texto_via": "api", "local": dict(c.get("local") or {}, ativo=False, so_local=[])})
    ia.salvar_config(_campos_juiz("off", ia.config()))  # o juiz continua desligado (o que mais gastava)
    return estado()


# ------------------------------------------------------------------ 🧪 testar tudo
def _imagem_teste() -> Dict[str, Any]:
    from PIL import Image
    im = Image.new("RGB", (64, 64), (220, 20, 20))
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}


def testar_tudo() -> List[Dict[str, Any]]:
    """Cada item: {nome, ok (True/False/None = não usado), msg, erro (texto pra copiar), instrucao (chave de INSTRUCOES), sugestoes}."""
    import ia_assinatura as ias
    import ia_local as il
    import ia_servico as ia
    c = ia.config()
    out: List[Dict[str, Any]] = []

    def item(nome, ok, msg="", erro="", instrucao="", **extra):
        out.append(dict(nome=nome, ok=ok, msg=msg, erro=erro, instrucao=instrucao, **extra))

    # 🔑 API
    if ia.chave(c):
        t0 = time.time()
        try:
            r = ia.testar()
        except Exception as exc:  # noqa: BLE001
            r = {"ok": False, "erro": str(exc)}
        item("🔑 API do Claude (a chave — reserva e imagens)", bool(r.get("ok")),
             f"respondeu em {time.time() - t0:.1f} s" if r.get("ok") else "", "" if r.get("ok") else str(r.get("erro") or "sem resposta"))
    else:
        item("🔑 API do Claude (a chave — reserva e imagens)", None, "sem chave salva — o juiz das cenas e a reserva não funcionam sem ela",
             instrucao="")

    # 🟠 / 🟢 assinaturas
    for modo, nome in (("claude", "🟠 Assinatura do Claude (Claude Code)"), ("chatgpt", "🟢 Assinatura do ChatGPT (Codex)")):
        usado = c.get("texto_via") == modo
        if not ias.executavel(modo):
            item(nome, False if usado else None, "não instalado neste PC" + ("" if usado else " (não está em uso)"),
                 f"{ias.EXE[modo]} não encontrado no PATH nem em %APPDATA%\\npm", instrucao=modo)
            continue
        t0 = time.time()
        r = ias.testar(modo, c.get("assinatura_modelo") or "sonnet")
        item(nome, bool(r.get("ok")) if (usado or r.get("ok")) else False,
             (f"respondeu em {time.time() - t0:.1f} s" + ("" if usado else " (instalado, mas não está em uso)")) if r.get("ok") else "",
             "" if r.get("ok") else str(r.get("erro") or ""), instrucao="" if r.get("ok") else modo)

    # 🖥 IA local
    lc = il.config(c)
    instalados = il.listar_modelos(c)
    if not instalados:
        item("🖥 IA local — servidor", False if lc["ativo"] else None,
             f"nada respondendo em {lc['url']}" + ("" if lc["ativo"] else " (está desligada)"),
             f"GET {lc['url'].rstrip('/')}/models não respondeu (Ollama fechado? LM Studio sem o Local Server?)", instrucao="local")
    else:
        item("🖥 IA local — servidor", True, f"respondendo em {lc['url']} · modelos: {', '.join(instalados[:10])}")
        sug_texto = [m for m in instalados if "vl" not in m.lower()]
        sug_visao = [m for m in instalados if "vl" in m.lower() or "vision" in m.lower() or "llava" in m.lower()]
        for chave, nome, img, sugs in (("modelo", "🖥 IA local — modelo de texto (buscas)", False, sug_texto),
                                       ("modelo_visao", "🖥 IA local — modelo com visão (juiz das cenas)", True, sug_visao)):
            m = (lc.get(chave) or "").strip()
            if not m:
                item(nome, None, "não escolhido" + (" — o juiz continua na API" if img else ""), sugestoes=sugs, campo=chave,
                     instrucao="local" if img and not sugs else "")
                continue
            if m not in instalados:
                item(nome, False, f"“{m}” não está instalado", f"modelo {m} não existe em {lc['url']}; instalados: {', '.join(instalados)}",
                     instrucao="local", sugestoes=sugs, campo=chave)
                continue
            t0 = time.time()
            try:
                cont = [_imagem_teste(), {"type": "text", "text": "Qual a cor dessa imagem? Responda o JSON."}] if img else "Diga ok."
                schema = ({"type": "object", "properties": {"cor": {"type": "string"}}, "required": ["cor"]} if img else
                          {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]})
                r = il.chamar(m, "Responda só o JSON pedido.", cont, schema, max_tokens=60, timeout=180, c=c)
                bom = ("verm" in str(r.get("cor", "")).lower() or "red" in str(r.get("cor", "")).lower()) if img else bool(r.get("ok"))
                item(nome, bom, f"respondeu em {time.time() - t0:.1f} s" + (f" (disse: {r.get('cor')})" if img else ""),
                     "" if bom else f"resposta estranha: {r}", campo=chave, sugestoes=sugs)
            except il.LocalErro as exc:
                item(nome, False, "", str(exc), instrucao="local", campo=chave, sugestoes=sugs)
    item("💸 Notas do texto bruto (cache uma vez só)", True, "sempre ligado")
    return out


def migrar_uma_vez() -> bool:
    """Na 1ª vez que o site abre com esta versão: aplica o recomendado (dá pra ↩ voltar na aba). True se aplicou agora."""
    import os
    import ia_servico as ia
    if os.environ.get("BESTEDITOR_IA_SO_API") == "1":
        return False
    try:
        if ia.config().get("economia_aplicada"):
            return False
        recomendado()
        ia.salvar_config({"economia_aplicada": True})
        try:
            import notificacoes
            notificacoes.avisar("💸 Economia de IA ligada", "Texto pela sua assinatura do Claude (se instalado), buscas no Qwen local e o "
                                "juiz visual das cenas no Qwen com visão (ou desligado). Dá pra mudar ou voltar em 💸 Economia de IA.",
                                "/ia/economia", "ok", tipo="ia")
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception:  # noqa: BLE001
        return False
