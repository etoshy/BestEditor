"""🟠🟢 v84_423 — usar a SUA ASSINATURA (Claude ou ChatGPT) no lugar da API, nos pedidos de TEXTO.

A assinatura do site do Claude/ChatGPT não dá chave de API. O que dá é a ferramenta de linha de comando oficial de cada um,
que entra com a sua conta e gasta da cota da assinatura:
  🟠 Claude  → Claude Code   (`claude -p`; instale: npm install -g @anthropic-ai/claude-code e rode `claude` uma vez pra entrar
               com a conta do Claude — Pro/Max)
  🟢 ChatGPT → Codex CLI     (`codex exec`; instale: npm install -g @openai/codex e rode `codex login` com a conta do ChatGPT)

Só texto: pedido com IMAGEM (juiz das cenas, revisão do diretor, fichas de foto…) continua na API.
Se a assinatura falhar (limite de 5 horas, não instalado, não logado) e a "reserva" estiver ligada, a API faz no lugar.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple

MODOS = {
    "api": "🔑 API (a chave, pago por uso)",
    "claude": "🟠 Minha assinatura do Claude (Claude Code)",
    "chatgpt": "🟢 Minha assinatura do ChatGPT (Codex)",
}
MODELOS_CLAUDE = {"sonnet": "Sonnet (equilibrado — recomendado)", "opus": "Opus (o melhor, gasta a cota mais rápido)",
                  "haiku": "Haiku (rápido, gasta pouco da cota)"}
EXE = {"claude": "claude", "chatgpt": "codex"}
# variáveis que fariam a ferramenta cobrar pela API em vez de usar a assinatura
_SEM_ENV = {"claude": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"),
            "chatgpt": ("OPENAI_API_KEY",)}
_FERRAMENTAS_PROIBIDAS = "Bash Edit Write MultiEdit NotebookEdit Read Glob Grep Task TodoWrite"


class AssinaturaErro(Exception):
    pass


def executavel(modo: str) -> Optional[str]:
    nome = EXE.get(modo)
    if not nome:
        return None
    achou = shutil.which(nome)
    if achou:
        return achou
    if os.name == "nt":  # npm global no Windows
        for base in (os.environ.get("APPDATA") or "", os.path.expanduser("~\\AppData\\Roaming")):
            for ext in (".cmd", ".exe", ""):
                c = os.path.join(base, "npm", nome + ext)
                if os.path.isfile(c):
                    return c
    return None


def tem_imagem(conteudo: Any) -> bool:
    if isinstance(conteudo, list):
        return any(isinstance(b, dict) and b.get("type") in ("image", "document") for b in conteudo)
    return False


def texto_de(conteudo: Any) -> str:
    if isinstance(conteudo, str):
        return conteudo
    if isinstance(conteudo, list):
        return "\n\n".join(str(b.get("text") or "") for b in conteudo if isinstance(b, dict) and b.get("type") == "text")
    return str(conteudo or "")


def montar_prompt(system: str, texto: str, schema: Optional[Dict[str, Any]] = None, so_pedido: bool = False) -> str:
    p = [texto] if so_pedido else [f"<instrucoes>\n{system}\n</instrucoes>", "", texto]
    if schema:
        p += ["", "RESPONDA SOMENTE com um JSON válido (sem texto antes ou depois, sem ```), seguindo este JSON Schema:",
              json.dumps(schema, ensure_ascii=False)]
    p += ["", "Não use ferramentas de arquivo nem de terminal: responda direto com o texto pedido."]
    return "\n".join(p)


def _env(modo: str) -> Dict[str, str]:
    e = dict(os.environ)
    for k in _SEM_ENV.get(modo, ()):
        e.pop(k, None)
    e.setdefault("PYTHONIOENCODING", "utf-8")
    return e


def _rodar(cmd: List[str], entrada: str, modo: str, timeout: float) -> Tuple[int, str, str]:
    with tempfile.TemporaryDirectory(prefix="be_ia_") as pasta:  # pasta vazia: a ferramenta não enxerga o site
        try:
            r = subprocess.run(cmd, input=entrada.encode("utf-8"), capture_output=True, cwd=pasta, env=_env(modo),
                               timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise AssinaturaErro(f"demorou mais de {int(timeout)} s") from exc
        except OSError as exc:
            raise AssinaturaErro(f"não consegui abrir o {EXE[modo]}: {exc}") from exc
        return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def chamar_claude(prompt: str, modelo: str = "sonnet", web: bool = False, timeout: float = 600, system: str = "") -> str:
    """`claude -p` com as instruções do SITE no lugar das do Claude Code (que gastariam ~40 mil tokens da cota a cada
    pedido), sem ferramentas (só a busca na internet quando `web`), sem CLAUDE.md/plugins/MCP."""
    exe = executavel("claude")
    if not exe:
        raise AssinaturaErro("o Claude Code não está instalado (npm install -g @anthropic-ai/claude-code)")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(system or "Você é um assistente. Responda exatamente o que for pedido, sem usar ferramentas de arquivo.")
        arq_system = f.name
    try:
        cmd = [exe, "-p", "--output-format", "json", "--model", modelo or "sonnet", "--system-prompt-file", arq_system,
               "--tools", "WebSearch,WebFetch" if web else "", "--safe-mode", "--strict-mcp-config"]
        if web:
            cmd += ["--allowedTools", "WebSearch", "WebFetch"]
        rc, out, err = _rodar(cmd, prompt, "claude", timeout)
    finally:
        try:
            os.remove(arq_system)
        except OSError:
            pass
    try:
        d = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
    except (ValueError, IndexError):
        d = {}
    if isinstance(d, list):  # algumas versões devolvem a lista de mensagens
        d = next((x for x in reversed(d) if isinstance(x, dict) and x.get("type") == "result"), {})
    texto = str(d.get("result") or "").strip() if isinstance(d, dict) else ""
    if rc != 0 or (isinstance(d, dict) and d.get("is_error")) or not texto:
        msg = texto or err.strip() or out.strip() or f"saiu com código {rc}"
        if "login" in msg.lower() or "authenticate" in msg.lower():
            msg += " — abra um terminal, rode `claude` e entre com a sua conta do Claude"
        raise AssinaturaErro(msg[:500])
    return texto


def chamar_codex(prompt: str, web: bool = False, timeout: float = 600) -> str:
    exe = executavel("chatgpt")
    if not exe:
        raise AssinaturaErro("o Codex não está instalado (npm install -g @openai/codex)")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        saida = f.name
    try:
        cmd = [exe, "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--color", "never",
               "--output-last-message", saida]
        if web:
            cmd += ["-c", "tools.web_search=true"]
        cmd.append("-")
        rc, out, err = _rodar(cmd, prompt, "chatgpt", timeout)
        try:
            with open(saida, encoding="utf-8") as f:
                texto = f.read().strip()
        except OSError:
            texto = ""
        if rc != 0 or not texto:
            msg = (err.strip() or out.strip() or f"saiu com código {rc}")[-500:]
            if "login" in msg.lower() or "auth" in msg.lower():
                msg += " — abra um terminal e rode `codex login` com a sua conta do ChatGPT"
            raise AssinaturaErro(msg)
        return texto
    finally:
        try:
            os.remove(saida)
        except OSError:
            pass


def chamar(modo: str, system: str, conteudo: Any, schema: Optional[Dict[str, Any]] = None, web: bool = False,
           modelo_claude: str = "sonnet", timeout: float = 600) -> Any:
    """O texto (ou o objeto, com schema) da resposta. AssinaturaErro em qualquer problema."""
    if tem_imagem(conteudo):
        raise AssinaturaErro("pedido com imagem — vai pela API")
    if modo == "claude":  # as instruções vão no lugar das do Claude Code; o pedido vai pela entrada
        t = chamar_claude(montar_prompt("", texto_de(conteudo), schema, so_pedido=True), modelo_claude, web, timeout,
                          system=system)
    elif modo == "chatgpt":
        t = chamar_codex(montar_prompt(system, texto_de(conteudo), schema), web, timeout)
    else:
        t = None
    if t is None:
        raise AssinaturaErro("modo inválido")
    if not schema:
        return t
    import json_ia
    try:
        return json_ia.carregar(t)
    except Exception as exc:  # noqa: BLE001
        raise AssinaturaErro(f"a resposta não veio em JSON: {t[:200]}") from exc


def testar(modo: str, modelo_claude: str = "sonnet") -> Dict[str, Any]:
    if modo not in ("claude", "chatgpt"):
        return {"ok": False, "erro": "escolha uma assinatura"}
    if not executavel(modo):
        return {"ok": False, "erro": ("Claude Code" if modo == "claude" else "Codex") + " não encontrado no PC — instale: "
                + ("npm install -g @anthropic-ai/claude-code e rode `claude` uma vez pra entrar" if modo == "claude"
                   else "npm install -g @openai/codex e rode `codex login`")}
    try:
        r = chamar(modo, "Responda só o JSON pedido.", "Diga ok.", schema={"type": "object", "properties": {"ok": {"type": "boolean"}},
                                                                            "required": ["ok"]}, modelo_claude=modelo_claude, timeout=180)
        return {"ok": bool(isinstance(r, dict) and r.get("ok")), "resposta": r}
    except AssinaturaErro as exc:
        return {"ok": False, "erro": str(exc)}
