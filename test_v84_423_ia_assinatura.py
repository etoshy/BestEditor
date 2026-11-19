"""v84_423 — pedidos de texto pela assinatura (Claude Code / Codex), imagem continua na API."""
import json
import os
import stat
import sys

import pytest

import ia_assinatura as ias


def _falso(tmp_path, nome, corpo):
    p = tmp_path / nome
    p.write_text("#!" + sys.executable + "\n" + corpo, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


CLAUDE = r'''
import sys, json, os
args = sys.argv[1:]
entrada = sys.stdin.read()
assert "-p" in args and "--output-format" in args
assert "ANTHROPIC_API_KEY" not in os.environ, "a chave da API vazou pro claude"
web = "WebSearch" in args[args.index("--tools") + 1]
assert "--system-prompt-file" in args and "--safe-mode" in args
sistema = open(args[args.index("--system-prompt-file") + 1], encoding="utf-8").read()
if "Diga ok" in entrada:
    print(json.dumps({"type": "result", "is_error": False, "result": '{"ok": true}'}))
else:
    print(json.dumps({"type": "result", "is_error": False, "result": "RESPOSTA web=%s modelo=%s" % (web, args[args.index("--model") + 1])}))
'''

CODEX = r'''
import sys
args = sys.argv[1:]
entrada = sys.stdin.read()
saida = args[args.index("--output-last-message") + 1]
open(saida, "w", encoding="utf-8").write('{"ok": true}' if "Diga ok" in entrada else "CODEX " + ("web" if "tools.web_search=true" in args else "sem web"))
'''


@pytest.fixture
def ferramentas(tmp_path, monkeypatch):
    c = _falso(tmp_path, "claude", CLAUDE)
    x = _falso(tmp_path, "codex", CODEX)
    monkeypatch.setattr(ias, "executavel", lambda modo: {"claude": c, "chatgpt": x}.get(modo))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")
    return c, x


def test_claude_e_codex(ferramentas):
    assert ias.chamar("claude", "s", "oi", modelo_claude="opus") == "RESPOSTA web=False modelo=opus"
    assert ias.chamar("claude", "s", "oi", web=True) == "RESPOSTA web=True modelo=sonnet"
    assert ias.chamar("chatgpt", "s", "oi", web=True) == "CODEX web"
    assert ias.testar("claude")["ok"] and ias.testar("chatgpt")["ok"]


def test_imagem_nao_vai_pela_assinatura(ferramentas):
    with pytest.raises(ias.AssinaturaErro):
        ias.chamar("claude", "s", [{"type": "image", "source": {}}, {"type": "text", "text": "x"}])


def test_ia_servico_usa_a_assinatura_e_cai_na_api(ferramentas, monkeypatch):
    import ia_servico as ia
    cfg = dict(ia.config(), ativo=True, texto_via="claude", assinatura_reserva_api=True, chave="sk-ant-x")
    monkeypatch.setattr(ia, "config", lambda: cfg)
    monkeypatch.setattr(ia, "_registrar", lambda *a, **k: None)
    api = []
    monkeypatch.setattr(ia, "_transporte", lambda payload, k, t: (api.append(1) or 200,
                        {"content": [{"type": "text", "text": "da API"}], "usage": {}}))
    assert ia.chamar("roteiros", "s", "oi", cache_local=False) == "RESPOSTA web=False modelo=sonnet" and not api
    # com imagem: API
    assert ia.chamar("juiz", "s", [{"type": "image", "source": {}}, {"type": "text", "text": "x"}], cache_local=False) == "da API"
    # assinatura falha → reserva na API; sem reserva → nada
    monkeypatch.setattr(ias, "chamar", lambda *a, **k: (_ for _ in ()).throw(ias.AssinaturaErro("limite de 5 horas")))
    assert ia.chamar("roteiros", "s", "oi", cache_local=False) == "da API"
    cfg["assinatura_reserva_api"] = False
    assert ia.chamar("roteiros", "s", "oi", cache_local=False) is None
    # não instalado: vai direto pela API (não trava quem nunca instalou)
    monkeypatch.setattr(ias, "executavel", lambda modo: None)
    assert ia.chamar("roteiros", "s", "oi", cache_local=False) == "da API"


def test_sem_chave_mas_com_assinatura_fica_ligada(monkeypatch):
    import ia_servico as ia
    base = dict(ia.config(), ativo=True, chave="", texto_via="claude")
    monkeypatch.setattr(ia, "chave", lambda c=None: "")
    assert ia.motivo_desligado("roteiros", base) is None
    assert ia.motivo_desligado("roteiros", dict(base, texto_via="api")) == "falta a chave da API"


def test_pagina_ia_mostra_a_opcao():
    import app as A
    h = A.app.test_client().get("/ia").get_data(as_text=True)
    assert "assVia" in h and "Claude Code" in h and "Codex" in h
