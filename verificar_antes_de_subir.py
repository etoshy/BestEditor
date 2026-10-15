#!/usr/bin/env python3
"""
🔒 Confere, ANTES de subir pro GitHub, se não vai junto nada pessoal ou sensível.

Uso (na pasta do projeto, depois do `git add -A`):

    python verificar_antes_de_subir.py            # só confere (o que está preparado pro commit)
    python verificar_antes_de_subir.py --corrigir # tira do commit os arquivos pessoais (git rm --cached)
    python verificar_antes_de_subir.py --instalar # passa a conferir sozinho em todo `git commit`

O que ele procura:
  1) ARQUIVOS pessoais/dados gerados: config com chaves (site_config.json, ia_config.json), cookies e
     sessões de navegador, a pasta do Flow (conta Google), bancos de dados, projetos, vídeos e áudios
     gerados, transcrições e análises obtidas (jobs/, outputs/, dossies/, analises_canal/…);
  2) CONTEÚDO sensível dentro dos arquivos: chaves de API (Anthropic, Google, GitHub, AWS, OpenAI…),
     chaves privadas, cookies de sessão do YouTube/Google e o seu e-mail;
  3) arquivos grandes demais pro GitHub (> 95 MB).

Não muda nada sem `--corrigir`. Nunca mostra uma chave inteira (só o começo).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import List, Tuple

# ---------------------------------------------------------------- o que nunca sobe
PASTAS_PESSOAIS = (
    "jobs/", "uploads/", "outputs/", "narracoes/", "conversas/", "roteiros_yt/", "vendas/", "dossies/",
    "modelados/", "chamadas_padrao/", "downloads/", "flow_dados/", "runpod_dados/", "ia_cache/", "analises_canal/",
    "niche_miner/data/", "toolkit/tts/models/", ".chrome_downloads/",
    "ia_google/perfil_navegador/", "ia_google/conversas/", "ia_google/debug/", "ia_google/erros/", "ia_google/resultados/",
    "ia_google/videos/", "ia_google/config.json",
)
ARQUIVOS_PESSOAIS = re.compile(
    r"(^|/)(site_config\.json|ia_config\.json|ia_uso\.json|youtube_cookies\.json|cookies[^/]*\.(txt|json)|"
    r"sessao[^/]*\.json|[^/]*storage_state[^/]*\.json|\.env(\.[^/]+)?|perfis_info\.json|vozes_multi\.json|"
    r"predefinicoes_usuario\.json|estilos_modelados\.json|toolkit_config\.local\.json|[^/]*\.(db|sqlite3?|pem|key|p12|pfx))$",
    re.I)
EXCECOES = re.compile(r"(^|/)\.env\.example$")
MIDIA_SOLTA = re.compile(r"^[^/]+\.(mp4|mov|mkv|webm|wav|mp3|m4a|zip)$", re.I)  # na raiz do projeto

# ---------------------------------------------------------------- conteúdo sensível
SEGREDOS: List[Tuple[str, re.Pattern]] = [
    ("chave da Anthropic", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("chave da OpenAI", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}")),
    ("chave do Google (API)", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("token do GitHub", re.compile(r"\b(ghp|gho|ghu|ghs)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}")),
    ("chave da AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("token do Slack", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("chave privada", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----")),
    ("cookie de sessão do Google/YouTube", re.compile(r"\b(__Secure-[13]PSID|SAPISID|__Secure-3PAPISID|LOGIN_INFO)\b[\"'\s:=\t]+[A-Za-z0-9_\-./:%]{20,}")),
    ("chave do ElevenLabs", re.compile(r"\bsk_[a-f0-9]{40,}\b")),
    ("chave do Runpod", re.compile(r"\brpa_[A-Za-z0-9]{30,}\b")),
]
# testes usam chaves falsas de propósito ("AIzaFake…", "sk-ant-teste")
FALSO = re.compile(r"fake|falsa|teste|test|exemplo|example|xxxx|errada|qualquer", re.I)
TAMANHO_MAX = 95 * 1024 * 1024
EXT_TEXTO = re.compile(r"\.(py|js|json|html|htm|txt|md|csv|ini|cfg|toml|yml|yaml|bat|ps1|sh|env|css|xml|srt|vtt)$", re.I)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def _arquivos(preparados: bool) -> List[str]:
    if preparados:
        saida = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
        if not saida.strip():  # nada preparado: confere tudo que o git acompanha
            saida = _git("ls-files")
    else:
        saida = _git("ls-files")
    return [l.strip() for l in saida.splitlines() if l.strip()]


def _mascarar(s: str) -> str:
    return s[:8] + "…" if len(s) > 8 else "…"


def _email_do_dono() -> str:
    return (_git("config", "user.email").strip() or os.environ.get("BESTEDITOR_EMAIL", "")).lower()


def conferir(arquivos: List[str], email: str = "") -> Tuple[List[str], List[str], List[str]]:
    pessoais, conteudo, grandes = [], [], []
    for a in arquivos:
        n = a.replace("\\", "/")
        if (any(n.startswith(p) for p in PASTAS_PESSOAIS) or ARQUIVOS_PESSOAIS.search(n) or MIDIA_SOLTA.match(n)) \
                and not EXCECOES.search(n):
            pessoais.append(a)
            continue
        try:
            tam = os.path.getsize(a)
        except OSError:
            continue
        if tam > TAMANHO_MAX:
            grandes.append(f"{a} ({tam / 1024 / 1024:.0f} MB)")
            continue
        if not EXT_TEXTO.search(n) or tam > 5 * 1024 * 1024:
            continue
        try:
            with open(a, encoding="utf-8", errors="ignore") as f:
                linhas = f.read().splitlines()
        except OSError:
            continue
        for i, linha in enumerate(linhas, 1):
            for nome, rx in SEGREDOS:
                m = rx.search(linha)
                if m and not FALSO.search(m.group(0)) and not FALSO.search(linha):
                    conteudo.append(f"{a}:{i} — {nome}: {_mascarar(m.group(0))}")
            if email and email in linha.lower() and not n.endswith(".gitignore"):
                conteudo.append(f"{a}:{i} — o seu e-mail ({_mascarar(email)})")
    return pessoais, conteudo, grandes


def instalar_gancho() -> None:
    pasta = _git("rev-parse", "--git-dir").strip()
    if not pasta:
        print("Isso não é um repositório git (rode dentro da pasta do projeto).")
        sys.exit(1)
    caminho = os.path.join(pasta, "hooks", "pre-commit")
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/sh\n# 🔒 BestEditor: não deixa subir nada pessoal/sensível\n"
                "python verificar_antes_de_subir.py || python3 verificar_antes_de_subir.py || exit 1\n")
    try:
        os.chmod(caminho, 0o755)
    except OSError:
        pass
    print(f"✅ Instalado: todo `git commit` confere antes ({caminho}). Pra pular uma vez: git commit --no-verify")


def main(argv: List[str]) -> int:
    if "--instalar" in argv:
        instalar_gancho()
        return 0
    arquivos = _arquivos(preparados="--tudo" not in argv)
    if not arquivos:
        print("Nada pra conferir (rode `git add -A` antes, dentro da pasta do projeto).")
        return 0
    pessoais, conteudo, grandes = conferir(arquivos, _email_do_dono())
    if pessoais and "--corrigir" in argv:
        for i in range(0, len(pessoais), 100):
            subprocess.run(["git", "rm", "-r", "-q", "--cached", "--", *pessoais[i:i + 100]], check=False)
        print(f"🧹 {len(pessoais)} arquivo(s) pessoal(is) tirado(s) do commit (continuam no seu PC).")
        pessoais = []
    ok = not (pessoais or conteudo or grandes)
    print(f"🔒 Conferidos {len(arquivos)} arquivos.")
    if pessoais:
        print(f"\n❌ {len(pessoais)} arquivo(s) PESSOAL(IS) / dado gerado no commit:")
        for a in pessoais[:40]:
            print("   -", a)
        if len(pessoais) > 40:
            print(f"   … e mais {len(pessoais) - 40}")
        print("   → rode:  python verificar_antes_de_subir.py --corrigir")
    if conteudo:
        print(f"\n❌ {len(conteudo)} trecho(s) com chave/cookie/e-mail:")
        for c in conteudo[:40]:
            print("   -", c)
        print("   → apague do arquivo (ou mova pra site_config.json / ia_config.json, que não sobem).")
        print("   ⚠ Se uma chave dessas JÁ subiu alguma vez, troque a chave no site do serviço: apagar do git não basta.")
    if grandes:
        print("\n❌ Arquivo(s) grande(s) demais pro GitHub (limite 100 MB):")
        for g in grandes:
            print("   -", g)
    if ok:
        print("✅ Nada pessoal ou sensível. Pode fazer o commit e o push.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
