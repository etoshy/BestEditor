"""v84_236: 🩹 Corrigir o Flow quando a tela muda — a IA (ou outra IA, pelo prompt) propõe a mudança, ela vai numa CÓPIA
do código do Flow (o original nunca muda), catalogada, testada no HTML do erro e reversível."""
import hashlib
import os
import sys

import pytest

import flow_correcoes as FC

# a caixa de comando REAL do Flow de out/2026 (sem o Agente): o erro "[config_agente] não achei o botão Configurações"
HTML_TELA = """<html><body><flow-project-page><flow-prompt-box class="prompt-box-container"><flow-base-prompt-box>
<div class="base-prompt-box"><div class="prompt-top-row"><flow-rich-text-editor class="prompt-input"><div class="prosemirror-editor">
<div role="textbox" aria-label="O que você quer criar?" contenteditable="true" class="ProseMirror"><p></p></div></div>
</flow-rich-text-editor></div><div class="bottom-controls"><flow-add-menu><button aria-label="Adicionar elementos à caixa de comando"
class="add-menu-trigger">add</button></flow-add-menu><div class="submit-controls"><button aria-label="Gatilho de configurações"
class="mdc-button settings-trigger-button"><span class="settings-summary"> Vídeo · 720p · 8s x1 </span></button>
<flow-generate-icon-button><button type="submit" aria-label="Iniciar geração" class="generate-icon-button">arrow_forward</button>
</flow-generate-icon-button></div></div></div></flow-base-prompt-box></flow-prompt-box></flow-project-page>
<script>window.x = 1</script><svg><path d="M0"/></svg></body></html>"""
MOTIVO = '[config_agente] não achei o botão "Configurações" (ícone tune) do agente.'
DE = """    "agente_config": ('flow-prompt-box .agent-footer-actions button[aria-label="Configurações"], '"""
PARA = """    "agente_config": ('flow-prompt-box button[aria-label="Configurações do agente"], '
                      'flow-prompt-box .agent-footer-actions button[aria-label="Configurações"], '"""


def _hash(caminho):
    with open(caminho, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


@pytest.fixture
def amb(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOW_CORRECOES_DIR", str(tmp_path / "correcoes"))
    dados = tmp_path / "flow_dados"
    (dados / "diagnostico").mkdir(parents=True)
    monkeypatch.setenv("GOOGLEFLOW_DATA_DIR", str(dados))
    diag = "20261022_113301_000001"
    (dados / "diagnostico" / f"{diag}.txt").write_text(f"{MOTIVO}\n\n--- texto da página ---\nO que você quer criar?\nVídeo · 720p", encoding="utf-8")
    (dados / "diagnostico" / f"{diag}_pagina.html").write_text(HTML_TELA, encoding="utf-8")
    from PIL import Image
    Image.new("RGB", (200, 120), (20, 20, 20)).save(dados / "diagnostico" / f"{diag}.png")
    import flow_lote
    monkeypatch.setattr(flow_lote, "reservado", lambda: False)
    yield {"diag": diag, "dir": str(tmp_path / "correcoes")}
    FC._apontar(None)  # o pacote volta pro original


def test_contexto_acha_a_funcao_os_seletores_e_o_html(amb):
    d = FC.diagnostico(amb["diag"])
    assert d["passo"] == "config_agente" and d["motivo"] == MOTIVO
    tr = FC.trecho_do_codigo(d, FC.ORIGINAL)
    nomes = [f["nome"] for f in tr["funcoes"]]
    assert nomes[0] == "configurar_agente" and "ligar_agente" in nomes
    assert "flow_direto.py: S[agente_config]" in tr["seletores"]
    assert any("preparar_projeto" in x or "configurar_agente(" in x for x in tr["chamadas"])
    pr = FC.prompt_outra_ia(amb["diag"])
    for trecho in ("configurar_agente()", "toolkit/googleflow/flow_direto.py", "settings-trigger-button", '"mudancas"',
                   "Gatilho de configurações", "TOLERANTE"):
        assert trecho in pr
    assert "<script" not in pr and "M0" not in pr  # o HTML vai limpo


def test_correcao_vai_na_copia_testa_ativa_e_volta(amb):
    original = os.path.join(FC.ORIGINAL, "flow_direto.py")
    h0 = _hash(original)
    x = FC.criar({"diagnostico": "o Flow tirou o Agente", "causa": "o botão sumiu", "confianca": "media",
                  "mudancas": [{"arquivo": "flow_direto.py", "de": DE, "para": PARA, "motivo": "seletor novo junto do antigo"}],
                  "seletores_esperados": ["flow-prompt-box button.settings-trigger-button", "button[aria-label=\"Iniciar geração\"]"],
                  "observacoes": ""}, amb["diag"], "teste")
    assert _hash(original) == h0  # o original NUNCA muda
    copia = FC.pasta_copia(x["id"])
    assert os.path.isfile(os.path.join(copia, "flow_direto.py")) and os.path.isfile(os.path.join(copia, "googleflow_client.py"))
    assert x["mudancas"][0]["aplicada"] and not x["compilacao"] and "Configurações do agente" in x["diffs"]["flow_direto.py"]
    th = x["testes"]["html"]  # testado sozinho no HTML guardado do erro
    assert [e["achou"] for e in th["esperados"]] == [1, 1] and th["ok"] and x["estado"] == "testada"
    linha = next(l for l in th["linhas"] if l["seletor"] == "flow_direto.py: S[agente_config]")
    assert linha["mudou"] and linha["envolvido"]
    # ✔ ativar: o pacote googleflow carrega da cópia; ↩ volta ao original
    r = FC.ativar(x["id"])
    assert r["agora"]
    import googleflow
    from googleflow import flow_direto as fd
    assert googleflow.__path__[0] == os.path.abspath(copia) and "Configurações do agente" in fd.S["agente_config"]
    assert FC.catalogo()["ativa"] == x["id"]
    # uma 2ª correção é feita EM CIMA da ativa
    y = FC.criar({"diagnostico": "outra", "causa": "", "confianca": "baixa", "seletores_esperados": [], "observacoes": "",
                  "mudancas": [{"arquivo": "flow_direto.py", "de": 'LARGURA_MIN', "para": "x", "motivo": "ambíguo"}]}, amb["diag"], "teste")
    assert y["base"] == x["id"] and y["estado"] == "falhou" and "vezes" in y["mudancas"][0]["erro"]
    with pytest.raises(FC.CorrecaoErro):
        FC.ativar(y["id"])
    with pytest.raises(FC.CorrecaoErro):
        FC.apagar(x["id"])  # está ativa
    FC.ativar(None)
    from googleflow import flow_direto as fd2
    assert googleflow.__path__ == [os.path.abspath(FC.ORIGINAL)] and "Configurações do agente" not in fd2.S["agente_config"]
    c = FC.catalogo()
    assert c["ativa"] is None and FC.item(c, x["id"])["estado"] == "revertida"
    assert [h["o_que"][:2] for h in FC.item(c, x["id"])["historico"]][-2:] == ["✔ ", "↩ "]
    FC.apagar(y["id"])
    assert not os.path.exists(os.path.join(amb["dir"], y["id"]))
    import zipfile, io
    z = zipfile.ZipFile(io.BytesIO(FC.zip_da_correcao(x["id"])))
    assert f"{x['id']}/googleflow/flow_direto.py" in z.namelist() and f"{x['id']}/flow_direto.py.diff" in z.namelist()


def test_resposta_ruim_nao_vira_correcao_valida(amb):
    with pytest.raises(FC.CorrecaoErro):
        FC.criar("isso não é json", amb["diag"], "teste")
    x = FC.criar('```json\n{"diagnostico": "d", "causa": "c", "confianca": "alta", "seletores_esperados": [], "observacoes": "",'
                 ' "mudancas": [{"arquivo": "../../app.py", "de": "a", "para": "b", "motivo": "m"},'
                 ' {"arquivo": "flow_direto.py", "de": "def configurar_agente(", "para": "def configurar_agente((", "motivo": "quebra"}]}\n```',
                 amb["diag"], "teste")
    assert x["estado"] == "falhou" and "fora do que pode" in x["mudancas"][0]["erro"] and x["compilacao"]


def test_ia_do_site_analisa_e_cria(amb, monkeypatch):
    import ia_servico
    visto = {}

    def falsa(recurso, system, conteudo, **kw):
        visto.update(recurso=recurso, n=len(conteudo), texto=conteudo[0]["text"])
        return {"diagnostico": "sem Agente", "causa": "c", "confianca": "alta", "observacoes": "",
                "seletores_esperados": ["flow-prompt-box button.settings-trigger-button"],
                "mudancas": [{"arquivo": "flow_direto.py", "de": DE, "para": PARA, "motivo": "m"}]}
    monkeypatch.setattr(ia_servico, "chamar", falsa)
    x = FC.analisar_ia(amb["diag"])
    assert visto["recurso"] == "flow_correcao" and visto["n"] == 2  # o texto + a foto
    assert "configurar_agente" in visto["texto"] and x["origem"] == "🤖 IA do site" and x["estado"] == "testada"


def test_aba_flow_tem_o_corrigir(amb):
    import app as A
    c = A.app.test_client()
    assert "🩹 Corrigir" in c.get("/flow").get_data(as_text=True)
    d = c.get("/flow/correcoes").get_json()
    assert d["ok"] and d["ativa"] is None
    assert "configurar_agente" in c.get(f"/flow/correcoes/prompt/{amb['diag']}").get_json()["prompt"]
