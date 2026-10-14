"""
Testes do cliente do Google Flow. NÃO abrem navegador nenhum nem falam com
o Google: um Playwright falso simula a página (login, painel de configurações,
conversa que acumula mensagens, geração, timeout). O que estes testes garantem
é a LÓGICA em volta — sessão única, configuração do projeto, fila, cache,
recuperação de falhas, modo oculto —, não que o Flow de verdade continue com
os mesmos seletores (isso só se descobre rodando no ar).
"""
import json
import os
import sys
import threading
import time
import types
from datetime import datetime, timedelta

import pytest

_TOOLKIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _TOOLKIT not in sys.path:
    sys.path.insert(0, os.path.abspath(_TOOLKIT))

from googleflow import googleflow_client as gf  # noqa: E402


# ------------------------------ fakes ------------------------------
class FakeResp:
    def __init__(self, ok=True, tipo="image/png", corpo=b"\x89PNG-fake"):
        self.ok = ok
        self.status = 200 if ok else 500
        self.headers = {"content-type": tipo}
        self._corpo = corpo

    def body(self):
        return self._corpo


class FakeRequest:
    def __init__(self, ctx):
        self.ctx = ctx

    def get(self, url):
        self.ctx.baixadas.append(url)
        return FakeResp(ok=url not in self.ctx.cfg.get("urls_com_erro", ()))


class FakeKeyboard:
    def __init__(self, page):
        self.page = page

    def type(self, texto, delay=0):
        self.page.digitado.append(texto)
        self.page.log.append("digitar")

    def press(self, tecla):
        self.page.log.append("esc")
        self.page.dialog_aberto = False


class FakeLocator:
    def __init__(self, page, sel):
        self.page = page
        self.sel = sel
        self.cfg = page.cfg

    def fill(self, texto):
        if self.sel == gf.SEL_GOOGLE_EMAIL:
            self.page.email_preenchido = texto
        elif self.sel == gf.SEL_GOOGLE_SENHA:
            self.page.senha_preenchida = texto
        elif self.sel == gf.SEL_NOVA_SENHA:
            self.page.nova_senha1 = texto
        elif self.sel == gf.SEL_CONFIRMAR_NOVA_SENHA:
            self.page.nova_senha2 = texto

    def is_visible(self):
        if self.sel == gf.SEL_REAUTH_CAPTCHA:
            return bool(self.cfg.get("troca_senha_captcha"))
        return False

    def scroll_into_view_if_needed(self, timeout=None):
        if self.sel == gf.SEL_DIALOGO_FIM_DO_TEXTO and self.page.dialogos_pendentes == 1:
            self.page.dialogo_2_rolado = True

    @property
    def first(self):
        return self

    # -- seletores de botão de configurações (candidatos conhecidos + o do usuário)
    def _eh_botao_config(self):
        return self.sel in gf.SEL_BOTAO_CONFIGURACOES or self.sel in self.cfg.get("botoes_existentes", ())

    def _botao_existe(self):
        existentes = self.cfg.get("botoes_existentes", (gf.SEL_BOTAO_CONFIGURACOES[3],))
        return self.sel in existentes

    def wait_for(self, state="visible", timeout=None):
        if self.sel == gf.SEL_NOVO_PROJETO:
            self.cfg["esperas_login"] = self.cfg.get("esperas_login", 0) + 1
            if self.cfg.get("precisa_login") or self.page.ctx.conta_fake in self.cfg.get("precisa_login_contas", ()):
                # 1ª espera (15s) sempre estoura; a 2ª (janela de login) só passa
                # se o "usuário" logou (login_ok_depois)
                if self.cfg["esperas_login"] % 2 == 1 or not self.cfg.get("login_ok_depois"):
                    raise gf.PWTimeout("botão não apareceu")
            elif self.cfg.get("login_automatico_necessario"):
                # 1ª espera: ainda não logado (é o que dispara o preenchimento automático).
                # espera seguinte: só passa se o preenchimento funcionou.
                if self.cfg["esperas_login"] == 1 or not self.cfg.get("_login_automatico_ok"):
                    raise gf.PWTimeout("login automático não completou")
        elif self.sel == gf.SEL_BOTAO_CRIAR_COM_FLOW:
            if not self.page.pagina_apresentacao:
                raise gf.PWTimeout("botão de apresentação não apareceu")
        elif self.sel in (gf.SEL_GOOGLE_EMAIL, gf.SEL_GOOGLE_SENHA):
            if self.sel in self.cfg.get("campos_google_ausentes", ()):
                raise gf.PWTimeout(f"{self.sel} não apareceu")
        elif self.sel == gf.SEL_DIALOGO_BOASVINDAS:
            if self.page.dialogos_pendentes <= 0:
                raise gf.PWTimeout("diálogo não apareceu")
        elif self.sel == gf.SEL_CHANGELOG_MODAL:
            if not self.page.changelog_visivel:
                raise gf.PWTimeout("changelog não apareceu")
        elif self.sel == gf.SEL_NOVA_SENHA and state == "hidden":
            if not self.page.senha_alterada:
                raise gf.PWTimeout("campo da senha nova continua visível")
        elif self.sel.startswith('flow-menu-item:has-text("'):
            if self.cfg.get("modelo_video_nao_encontrado"):
                raise gf.PWTimeout("item do menu de modelo não apareceu")
        elif self._eh_botao_config():
            if not self._botao_existe():
                raise gf.PWTimeout("botão de configurações não existe")
        elif self.sel == gf.SEL_PAINEL_ROTULO:
            if not self.page.dialog_aberto:
                raise gf.PWTimeout("painel não abriu")
        elif self.sel == gf.SEL_PAINEL and state == "hidden":
            if self.page.dialog_aberto:
                raise gf.PWTimeout("painel continua aberto")

    def click(self, timeout=None):
        page, sel = self.page, self.sel
        if sel == gf.SEL_GOOGLE_EMAIL_PROXIMO:
            page.log.append("google_email_proximo")
        elif sel == gf.SEL_GOOGLE_SENHA_PROXIMO:
            page.log.append("google_senha_proximo")
            page.cfg["_login_automatico_ok"] = bool(
                page.email_preenchido and page.senha_preenchida and not page.cfg.get("bloqueia_login_automatico")
            )
        elif sel == gf.SEL_DIALOGO_BOTAO_PRIMARIO:
            pode_clicar = page.dialogos_pendentes != 1 or not page.cfg.get("dialogo_2_precisa_rolar", True) or page.dialogo_2_rolado
            if pode_clicar and page.dialogos_pendentes > 0:
                page.log.append("dialogo_avancar")
                page.dialogos_pendentes -= 1
        elif sel == gf.SEL_BOTAO_CRIAR_COM_FLOW:
            page.log.append("crie_com_o_flow")
            page.pagina_apresentacao = False
        elif sel == gf.SEL_NOVO_PROJETO:
            page.log.append("novo_projeto")
            if self.cfg.get("projeto_em_nova_aba"):
                page.ctx.new_page()
        elif sel == gf.SEL_CHANGELOG_BOTAO_PRIMARIO:
            page.log.append("changelog_comecar")
            page.changelog_visivel = False
        elif sel == gf.SEL_REAUTH_AVANCAR:
            page.log.append("reauth_avancar")
        elif sel == gf.SEL_ALTERAR_SENHA_BOTAO:
            page.log.append("alterar_senha")
            page.senha_alterada = not page.cfg.get("troca_senha_falha", False)
        elif self._eh_botao_config():
            page.log.append("abrir_config")
            if sel not in self.cfg.get("botoes_errados", ()):
                page.dialog_aberto = True
        elif sel == gf.SEL_CONFIRMAR_NUNCA:
            page.log.append("nunca")
            if not self.cfg.get("nunca_falha"):
                page.settings["confirmar"] = 2
        elif sel == gf.SEL_IMAGENS_X1:
            page.log.append("x1")
            if not self.cfg.get("x1_falha"):
                page.settings["qtd"] = 1
        elif sel == gf.SEL_VIDEO_X1:
            page.log.append("x1_video")
            if not self.cfg.get("x1_video_falha"):
                page.settings["qtd_video"] = 1
        elif sel == gf.SEL_VIDEO_MODELO_BOTAO:
            if self.cfg.get("botao_modelo_video_ausente"):
                raise gf.PWTimeout("botão do modelo de vídeo não apareceu")
            page.log.append("abrir_menu_modelo_video")
        elif sel.startswith('flow-menu-item:has-text("'):
            modelo = sel.split('flow-menu-item:has-text("', 1)[1].rsplit('") button', 1)[0]
            page.log.append("escolher_modelo_video:" + modelo)
            page.settings["modelo_video"] = modelo
        elif sel == gf.SEL_SALVAR_CONFIG:
            page.log.append("salvar")
            if not self.cfg.get("salvar_nao_fecha"):
                page.dialog_aberto = False
        elif sel == gf.SEL_BOTAO_ENVIAR:
            page.enviar()

    def count(self):
        if self.sel == gf.SEL_MSG_USUARIO:
            return self.page.n_usuario
        return self.page.mensagens if self.sel == gf.SEL_MENSAGEM else 0

    def is_checked(self):
        return self.sel == gf.SEL_CONFIRMAR_NUNCA_INPUT and self.page.settings.get("confirmar") == 2

    def get_attribute(self, nome):
        if self.sel == gf.SEL_IMAGENS_X1 and nome == "aria-checked":
            return "true" if self.page.settings.get("qtd") == 1 else "false"
        if self.sel == gf.SEL_VIDEO_X1 and nome == "aria-checked":
            return "true" if self.page.settings.get("qtd_video") == 1 else "false"
        return None


class FakePage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.cfg = ctx.cfg
        self.log = ctx.log
        self.digitado = []
        self.keyboard = FakeKeyboard(self)
        self.fechada = False
        self.dialog_aberto = False
        self.settings = {}
        self.mensagens = 0
        self.email_preenchido = ""
        self.senha_preenchida = ""
        self.dialogos_pendentes = ctx.cfg.get("qtd_dialogos_boasvindas", 0)
        self.dialogo_2_rolado = False
        self.changelog_visivel = ctx.cfg.get("changelog_aparece", False)
        self.pagina_apresentacao = ctx.cfg.get("pagina_apresentacao", False)
        self.nova_senha1 = ""
        self.nova_senha2 = ""
        self.senha_alterada = False
        self.n_usuario = 0       # balões de mensagem DO USUÁRIO na conversa
        self.geracoes = []       # [(indice_da_primeira_mensagem, [urls])]
        self.texto_final = ""
        self.travado = False
        ctx.paginas_criadas.append(self)
        ctx.pages.append(self)

    def enviar(self):
        ctx = self.ctx
        ctx.contador += 1
        n = ctx.contador
        self.log.append("enviar")
        if self.cfg.get("pedido_recusado"):   # o Flow nem aceitou: nenhum balão do usuário aparece
            return
        self.n_usuario += 1
        self.texto_final = "Pronto! Aqui está a imagem."
        if self.cfg.get("estoura_no_pedido") == n:
            self.travado = True
            return
        if self.ctx.conta_fake in self.cfg.get("sem_credito", ()):
            self.texto_final = self.cfg.get("texto_limite", "Você atingiu o limite de créditos.")
            self.geracoes.append((self.mensagens, []))
            self.mensagens += 1
            return
        if self.cfg.get("sem_imagem_no_pedido") == n:
            urls, self.texto_final = [], "Não posso gerar isso."
        else:
            urls = list(self.cfg.get("urls") or [f"https://x/img{n}_{k}.png" for k in range(self.cfg.get("qtd_imagens", 1))])
        self.geracoes.append((self.mensagens, urls))
        self.mensagens += 2

    def goto(self, url, wait_until=None):
        self.ctx.visitadas.append(url)

    def locator(self, sel):
        return FakeLocator(self, sel)

    def wait_for_function(self, script, arg=None, timeout=None, polling=None):
        if arg == gf.SEL_BOTAO_ENVIAR and self.cfg.get("botao_desabilitado"):
            raise gf.PWTimeout("botão de enviar continua desabilitado")
        if arg == gf.SEL_DIALOGO_BOTAO_PRIMARIO:
            precisa_rolar = (self.dialogos_pendentes == 1 and self.cfg.get("dialogo_2_precisa_rolar", True)
                              and not self.dialogo_2_rolado)
            if precisa_rolar:
                raise gf.PWTimeout("botão do diálogo desabilitado")

    def screenshot(self, path=None, **kw):
        with open(path, "wb") as f:
            f.write(b"PNG-fake")

    def evaluate(self, script, arg=None):
        if script == gf.JS_BOTOES:
            return self.cfg.get("botoes", ["Ajuda | ícone: help", "Menu | ícone: menu"])
        if script == gf.JS_AVISOS:
            return self.cfg.get("avisos", "")
        if script == gf.JS_TEXTO_PAGINA:
            return "texto da página de teste"
        assert script == gf.JS_ESTADO
        antes = arg[2]
        if self.travado:
            return {"mensagens": 0, "urls": [], "ultima_e_texto": False, "texto": "", "avisos": self.cfg.get("avisos", "")}
        novas = max(self.mensagens - antes, 0)
        urls = [u for (i, us) in self.geracoes if i >= antes for u in us]
        return {
            "mensagens": novas, "urls": urls,
            "ultima_e_texto": bool(novas) and self.cfg.get("ultima_e_texto", True),
            "texto": self.texto_final if novas else "",
            "avisos": self.cfg.get("avisos", ""),
        }

    def wait_for_load_state(self, *_, **__):
        pass

    def bring_to_front(self):
        pass

    def close(self):
        self.fechada = True
        if self in self.ctx.pages:
            self.ctx.pages.remove(self)


class FakeContext:
    def __init__(self, cfg, kwargs, log):
        self.cfg = cfg
        self.kwargs = kwargs
        self.log = log
        self.pages = []
        self.paginas_criadas = []
        self.visitadas = []
        self.baixadas = []
        self.fechado = False
        self.contador = 0
        self.request = FakeRequest(self)
        self.cookies_adicionados = None
        nome_perfil = os.path.basename(str(kwargs.get("_perfil", "")))
        self.conta_fake = nome_perfil.split("--", 1)[1] if "--" in nome_perfil else "principal"

    def new_page(self):
        return FakePage(self)

    def storage_state(self, path=None):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"cookies": [{"name": "SID", "value": "x", "domain": ".google.com", "path": "/"}]}, f)

    def add_cookies(self, cookies):
        self.cookies_adicionados = cookies

    def close(self):
        self.fechado = True


class FakeBrowserType:
    def __init__(self, pw, nome):
        self.pw = pw
        self.nome = nome

    def launch_persistent_context(self, perfil, **kwargs):
        if self.nome in self.pw.cfg.get("navegadores_quebrados", ()):
            raise RuntimeError(f"{self.nome} não instalado")
        kwargs = dict(kwargs, _perfil=perfil, _tipo=self.nome)
        ctx = FakeContext(self.pw.cfg, kwargs, self.pw.log)
        self.pw.contextos.append(ctx)
        return ctx


def _connect_over_cdp(self, url):
    ctx = FakeContext(self.pw.cfg, {"_perfil": "cdp", "_tipo": "cdp"}, self.pw.log)
    self.pw.contextos.append(ctx)
    return types.SimpleNamespace(contexts=[ctx])


FakeBrowserType.connect_over_cdp = _connect_over_cdp


class FakePlaywright:
    def __init__(self, cfg):
        self.cfg = cfg
        self.contextos = []
        self.log = []
        self.chromium = FakeBrowserType(self, "chromium")
        self.firefox = FakeBrowserType(self, "firefox")
        self.webkit = FakeBrowserType(self, "webkit")


class FakeManager:
    """Faz o papel de `sync_playwright()`. Guarda quantas vezes foi aberto e o
    máximo simultâneo."""
    aberturas = 0
    ativos = 0
    max_ativos = 0
    lock = threading.Lock()

    def __init__(self, cfg, atraso=0.0):
        self.cfg = cfg
        self.atraso = atraso
        self.pw = FakePlaywright(cfg)

    def __enter__(self):
        with FakeManager.lock:
            FakeManager.aberturas += 1
            FakeManager.ativos += 1
            FakeManager.max_ativos = max(FakeManager.max_ativos, FakeManager.ativos)
        if self.atraso:
            time.sleep(self.atraso)
        return self.pw

    def __exit__(self, *a):
        with FakeManager.lock:
            FakeManager.ativos -= 1


@pytest.fixture(autouse=True)
def ambiente(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLEFLOW_DATA_DIR", str(tmp_path / "flow_dados"))
    monkeypatch.setattr(gf, "PAUSA_APOS_NOVO_PROJETO_S", 0)
    monkeypatch.setattr(gf, "PAUSA_POLLING_S", 0.01)
    monkeypatch.setattr(gf, "ESTAVEL_S", 0.05)
    monkeypatch.setattr(gf, "GRACA_SEM_IMAGEM_S", 0.05)
    FakeManager.aberturas = 0
    FakeManager.ativos = 0
    FakeManager.max_ativos = 0
    gf.encerrar_sessao()
    yield
    gf.encerrar_sessao()


def _cliente(cfg=None, flow_cfg=None, atraso=0.0):
    flow_cfg = flow_cfg if flow_cfg is not None else {}
    managers = []

    def fabrica():
        m = FakeManager(flow_cfg, atraso=atraso)
        managers.append(m)
        return m

    c = gf.GoogleFlowClient(site_cfg=cfg if cfg is not None else {}, playwright_factory=fabrica)
    c._managers = managers
    return c


def _pw(c, i=0):
    return c._managers[i].pw


# ------------------------------ montar_prompt ------------------------------
def test_prompt_ganha_verbo_e_proporcao():
    assert gf.montar_prompt("um gato correndo") == "gere a imagem de um gato correndo proporção 16x9"


def test_prompt_que_ja_e_um_comando_nao_ganha_outro_verbo():
    assert gf.montar_prompt("Gere a imagem de um gato", "9x16") == "Gere a imagem de um gato proporção 9x16"
    assert gf.montar_prompt("create a cat picture") == "create a cat picture proporção 16x9"


def test_prompt_que_ja_tem_proporcao_nao_duplica():
    assert gf.montar_prompt("gere um gato proporção 1x1") == "gere um gato proporção 1x1"
    assert gf.montar_prompt("gere um gato 9x16", "16x9") == "gere um gato 9x16"


def test_prompt_vazio_da_erro():
    with pytest.raises(gf.GoogleFlowError):
        gf.montar_prompt("   ")


def test_proporcao_segue_a_orientacao_do_site():
    assert gf.proporcao_para_orientacao("16:9") == "16x9"
    assert gf.proporcao_para_orientacao("9:16") == "9x16"
    assert gf.proporcao_para_orientacao(None) == "16x9"


def test_chave_ignora_maiusculas_e_espacos_extras():
    assert gf.chave_do_prompt("Gere  um GATO") == gf.chave_do_prompt("gere um gato")
    assert gf.chave_do_prompt("gere um gato") != gf.chave_do_prompt("gere um cão")


# ------------------------------ geração básica ------------------------------
def test_gera_baixa_e_devolve_fotos_com_a_interface_dos_bancos_de_foto():
    c = _cliente()
    fotos = c.search_photos_all("um gato correndo")
    assert len(fotos) == 1  # x1
    f = fotos[0]
    assert os.path.exists(f.local_path)
    assert f.sizes["tiny"].startswith(gf.URL_PREFIXO_IMAGENS)
    assert f.id and f.description.startswith("gere a imagem de um gato")
    assert f.author == "Google Flow (IA)"


def test_varias_imagens_na_mesma_geracao_sao_todas_devolvidas():
    c = _cliente(flow_cfg={"qtd_imagens": 2})
    assert len(c.search_photos_all("um gato")) == 2


def test_pedido_enviado_ao_flow_tem_verbo_e_proporcao_da_orientacao():
    c = _cliente(cfg={"orientation": "9:16"})
    c.search_photos_all("uma cidade futurista")
    pagina = _pw(c).contextos[0].paginas_criadas[-1]
    assert pagina.digitado == ["gere a imagem de uma cidade futurista proporção 9x16"]


def test_registra_no_imagens_json():
    c = _cliente(flow_cfg={"qtd_imagens": 2})
    c.search_photos_all("um gato")
    dados = json.loads(gf.arquivo_json().read_text(encoding="utf-8"))
    assert len(dados) == 2
    assert all(d["prompt"].startswith("gere a imagem de um gato") and d["chave"] for d in dados)


def test_mesmo_pedido_nao_gera_de_novo_usa_o_cache():
    c = _cliente()
    c.search_photos_all("um gato")
    c.search_photos_all("um gato")
    c.search_photos_all("UM  gato")  # mesma chave (caixa/espaços não importam)
    assert FakeManager.aberturas == 1
    assert _pw(c).log.count("enviar") == 1


def test_cache_ignora_arquivo_que_sumiu_do_disco():
    c = _cliente(flow_cfg={"qtd_imagens": 2})
    fotos = c.search_photos_all("um gato")
    os.remove(fotos[0].local_path)
    assert len(c.search_photos_all("um gato")) == 1  # só a que ainda existe; não regenera à toa


def test_falha_ao_baixar_uma_imagem_nao_derruba_as_outras():
    c = _cliente(flow_cfg={"qtd_imagens": 2, "urls": ["https://x/i1.png", "https://x/i2.png"], "urls_com_erro": ("https://x/i1.png",)})
    assert len(c.search_photos_all("um gato")) == 1


def test_todas_as_imagens_falhando_ao_baixar_da_erro():
    c = _cliente(flow_cfg={"urls": ["https://x/i1.png"], "urls_com_erro": ("https://x/i1.png",)})
    with pytest.raises(gf.GoogleFlowError, match="baixar"):
        c.search_photos_all("um gato")


# ------------------------------ UMA sessão, UMA conversa ------------------------------
def test_varias_imagens_usam_o_mesmo_navegador_e_a_mesma_conversa():
    c = _cliente()
    for tema in ("um gato", "um cachorro", "um pássaro"):
        c.search_photos_all(tema)
    assert FakeManager.aberturas == 1                      # um Playwright
    assert len(_pw(c).contextos) == 1                       # um navegador
    ctx = _pw(c).contextos[0]
    assert len(ctx.paginas_criadas) == 1                    # uma página/projeto
    assert _pw(c).log.count("novo_projeto") == 1
    assert _pw(c).log.count("salvar") == 1                  # configurou uma vez só
    assert len(ctx.paginas_criadas[0].digitado) == 3        # os 3 pedidos, na mesma conversa
    assert not ctx.fechado                                  # continua aberto pros próximos


def test_a_configuracao_acontece_depois_do_novo_projeto_e_antes_do_primeiro_pedido():
    c = _cliente()
    c.search_photos_all("um gato")
    log = _pw(c).log
    assert log[:6] == ["novo_projeto", "abrir_config", "nunca", "x1", "x1_video", "salvar"]
    assert log.index("digitar") > log.index("salvar")


def test_configuracao_deixa_nunca_e_x1_marcados_e_o_painel_fechado():
    c = _cliente()
    c.search_photos_all("um gato")
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert pagina.settings == {"confirmar": 2, "qtd": 1, "qtd_video": 1}
    assert pagina.dialog_aberto is False


def test_seletor_do_usuario_e_tentado_primeiro():
    c = _cliente(cfg={"flow_seletor_configuracoes": "button.minha-engrenagem"},
                 flow_cfg={"botoes_existentes": ("button.minha-engrenagem",)})
    c.search_photos_all("um gato")
    assert "abrir_config" in _pw(c).log


def test_candidato_que_abre_o_painel_errado_e_descartado_e_o_proximo_e_tentado():
    cand = gf.SEL_BOTAO_CONFIGURACOES
    c = _cliente(flow_cfg={"botoes_existentes": (cand[0], cand[3]), "botoes_errados": (cand[0],)})
    c.search_photos_all("um gato")
    log = _pw(c).log
    assert log.count("abrir_config") == 2 and "esc" in log
    assert _pw(c).contextos[0].paginas_criadas[0].settings == {"confirmar": 2, "qtd": 1, "qtd_video": 1}


def test_seletor_agent_panel_sem_prompt_box_nao_existe_mais_na_lista():
    # bug real encontrado por inspeção do HTML que o usuário mandou: não
    # existe elemento com a classe EXATA "agent-panel" no Flow real, só
    # "agent-panel-prompt-box" -- um seletor CSS de classe exige bater o
    # nome inteiro, então ".agent-panel button:has(...)" nunca casava com
    # nada. Confirma que o texto errado sumiu e o certo está no lugar.
    lista = " | ".join(gf.SEL_BOTAO_CONFIGURACOES)
    assert ".agent-panel button" not in lista
    assert ".agent-panel-prompt-box button" in lista


def test_seletor_escopado_no_agent_footer_actions_vem_primeiro_e_e_tentado_sem_descartes():
    # o botão de configurações confirmado pelo usuário fica dentro de
    # .agent-footer-actions -- esse candidato tem que vir ANTES dos
    # genéricos (aria-label*="onfigura" sem escopo, que também bateria
    # com outras engrenagens da tela, tipo a de configurações gerais da
    # conta na barra superior) pra evitar abrir o painel errado à toa.
    assert gf.SEL_BOTAO_CONFIGURACOES[0].startswith(".agent-footer-actions")
    assert gf.SEL_BOTAO_CONFIGURACOES[1].startswith(".agent-footer-actions")

    cand = gf.SEL_BOTAO_CONFIGURACOES
    c = _cliente(flow_cfg={"botoes_existentes": (cand[0],)})
    c.search_photos_all("um gato")
    log = _pw(c).log
    assert log.count("abrir_config") == 1  # achou de primeira, sem precisar descartar nenhum
    assert "esc" not in log


def test_sem_achar_o_botao_o_erro_lista_os_botoes_da_tela_e_diz_o_que_fazer():
    c = _cliente(flow_cfg={"botoes_existentes": (), "botoes": ["Ajuda | ícone: help", "Engrenagem xyz | ícone: tune2"]})
    with pytest.raises(gf.GoogleFlowError) as exc:
        c.search_photos_all("um gato")
    msg = str(exc.value)
    assert "Engrenagem xyz" in msg and "Seletor do botão de configurações" in msg
    assert "digitar" not in _pw(c).log  # não gerou nada às cegas


def test_configurar_projeto_desligado_pula_o_passo():
    c = _cliente(cfg={"flow_configurar_projeto": False})
    assert len(c.search_photos_all("um gato")) == 1
    log = _pw(c).log
    assert "abrir_config" not in log and "nunca" not in log


def test_nunca_nao_marcado_da_erro_em_vez_de_travar_as_geracoes():
    c = _cliente(flow_cfg={"nunca_falha": True})
    with pytest.raises(gf.GoogleFlowError, match="Nunca"):
        c.search_photos_all("um gato")
    assert "digitar" not in _pw(c).log


def test_x1_nao_marcado_da_erro():
    c = _cliente(flow_cfg={"x1_falha": True})
    with pytest.raises(gf.GoogleFlowError, match="x1"):
        c.search_photos_all("um gato")


def test_painel_que_nao_fecha_ao_salvar_da_erro():
    c = _cliente(flow_cfg={"salvar_nao_fecha": True})
    with pytest.raises(gf.GoogleFlowError, match="configurando o projeto"):
        c.search_photos_all("um gato")


def test_depois_de_uma_falha_de_configuracao_o_proximo_pedido_recomeca_num_projeto_novo():
    flow_cfg = {"nunca_falha": True}
    c = _cliente(flow_cfg=flow_cfg)
    with pytest.raises(gf.GoogleFlowError):
        c.search_photos_all("um gato")
    flow_cfg["nunca_falha"] = False
    assert len(c.search_photos_all("um gato")) == 1
    assert _pw(c).log.count("novo_projeto") == 2
    assert len(_pw(c).contextos) == 1          # o navegador foi mantido
    assert _pw(c).contextos[0].paginas_criadas[0].fechada


def test_projeto_que_abre_em_nova_aba_fecha_a_inicial_e_gera_na_nova():
    c = _cliente(flow_cfg={"projeto_em_nova_aba": True})
    c.search_photos_all("um gato")
    inicial, projeto = _pw(c).contextos[0].paginas_criadas[:2]
    assert inicial.fechada and inicial.digitado == []
    assert projeto.digitado and projeto.settings == {"confirmar": 2, "qtd": 1, "qtd_video": 1}


# ------------------------------ falhas no meio ------------------------------
def test_geracao_que_estoura_o_tempo_da_erro_e_a_proxima_recomeca_em_projeto_novo():
    c = _cliente(cfg={"flow_timeout_seconds": 1}, flow_cfg={"estoura_no_pedido": 2})
    c.search_photos_all("primeiro")
    with pytest.raises(gf.GoogleFlowError, match="Tempo esgotado"):
        c.search_photos_all("segundo")
    assert len(c.search_photos_all("terceiro")) == 1
    assert _pw(c).log.count("novo_projeto") == 2       # recomeçou depois da falha
    assert len(_pw(c).contextos) == 1                   # sem reabrir o navegador
    assert FakeManager.aberturas == 1


def test_resposta_sem_imagem_da_erro_com_o_texto_do_flow_e_nao_devolve_a_imagem_do_pedido_anterior():
    c = _cliente(flow_cfg={"sem_imagem_no_pedido": 2})
    primeira = c.search_photos_all("primeiro")
    with pytest.raises(gf.GoogleFlowError, match="Não posso gerar isso"):
        c.search_photos_all("segundo")
    assert len(primeira) == 1
    assert len(c.search_photos_all("terceiro")) == 1


def test_url_ja_vista_na_conversa_nao_e_aceita_de_novo():
    # o Flow "devolve" sempre a mesma imagem => a 2ª geração seria uma imagem velha
    c = _cliente(flow_cfg={"urls": ["https://x/fixa.png"]})
    c.search_photos_all("primeiro")
    with pytest.raises(gf.GoogleFlowError, match="sem gerar imagem"):
        c.search_photos_all("segundo")


def test_termina_pela_estabilidade_quando_imagem_e_texto_vem_na_mesma_mensagem():
    # com x1 a última mensagem pode não ser "só texto"; a imagem apareceu e nada mudou => pronto
    c = _cliente(flow_cfg={"ultima_e_texto": False})
    assert len(c.search_photos_all("um gato")) == 1


# ------------------------------ modo oculto / login ------------------------------
def test_por_padrao_roda_oculto_com_viewport_definido():
    c = _cliente(cfg={})
    c.search_photos_all("um gato")
    kw = _pw(c).contextos[0].kwargs
    assert kw["headless"] is True
    assert kw["viewport"] == {"width": 1366, "height": 900}
    assert "no_viewport" not in kw


def test_navegador_visivel_quando_a_config_manda():
    c = _cliente(cfg={"browser_visible": True})
    c.search_photos_all("um gato")
    kw = _pw(c).contextos[0].kwargs
    assert kw["headless"] is False and kw["no_viewport"] is True


def test_trocar_oculto_por_visivel_reabre_o_navegador_e_fecha_o_antigo():
    c = _cliente(cfg={"browser_visible": False})
    c.search_photos_all("um gato")
    c.cfg["browser_visible"] = True
    c.search_photos_all("um cachorro")
    assert FakeManager.aberturas == 2
    antigo, novo = _pw(c, 0).contextos[0], _pw(c, 1).contextos[0]
    assert antigo.fechado and antigo.kwargs["headless"] is True
    assert novo.kwargs["headless"] is False


def test_oculto_sem_login_da_erro_orientando_a_logar_e_nao_espera_5_minutos():
    c = _cliente(cfg={"browser_visible": False}, flow_cfg={"precisa_login": True})
    with pytest.raises(gf.GoogleFlowLoginRequired, match="OCULTO"):
        c.search_photos_all("um gato")
    assert _pw(c).contextos[0].fechado
    assert c._managers[0].cfg["esperas_login"] == 1  # só a espera curta, sem a de 5 min


def test_depois_de_erro_de_login_o_proximo_pedido_tenta_de_novo_com_navegador_novo():
    flow_cfg = {"precisa_login": True}
    c = _cliente(cfg={"browser_visible": False}, flow_cfg=flow_cfg)
    with pytest.raises(gf.GoogleFlowLoginRequired):
        c.search_photos_all("um gato")
    flow_cfg["precisa_login"] = False       # o usuário fez login pelo botão
    assert len(c.search_photos_all("um gato")) == 1
    assert len(_pw(c).contextos) == 2


def test_visivel_sem_login_espera_o_usuario_logar_e_segue():
    c = _cliente(cfg={"browser_visible": True}, flow_cfg={"precisa_login": True, "login_ok_depois": True})
    assert len(c.search_photos_all("um gato")) == 1


def test_visivel_e_ninguem_loga_da_erro_de_login():
    c = _cliente(cfg={"browser_visible": True}, flow_cfg={"precisa_login": True, "login_ok_depois": False})
    with pytest.raises(gf.GoogleFlowLoginRequired, match="Tempo esgotado"):
        c.search_photos_all("um gato")


def test_login_interativo_abre_janela_visivel_mesmo_com_config_oculta_e_salva_sessao():
    c = _cliente(cfg={"browser_visible": False})
    assert c.login_interativo() is True
    ctx = _pw(c).contextos[0]
    assert ctx.kwargs["headless"] is False and ctx.fechado
    assert gf.arquivo_sessao().exists()


def test_login_interativo_fecha_antes_a_sessao_de_geracao_que_usa_o_mesmo_perfil():
    c = _cliente(cfg={"browser_visible": False})
    c.search_photos_all("um gato")
    geracao = _pw(c).contextos[0]
    assert not geracao.fechado
    c.login_interativo()
    assert geracao.fechado


def test_login_interativo_que_ninguem_completa_da_erro():
    c = _cliente(flow_cfg={"precisa_login": True, "login_ok_depois": False})
    with pytest.raises(gf.GoogleFlowLoginRequired):
        c.login_interativo()


# ------------------------------ navegador / sessão em disco ------------------------------
def test_sessao_e_salva_e_restaurada_quando_o_navegador_reabre():
    c = _cliente()
    c.search_photos_all("um gato")
    assert gf.arquivo_sessao().exists()
    gf.encerrar_sessao()
    c.search_photos_all("um cachorro")
    ctx2 = _pw(c, 1).contextos[0]
    assert ctx2.cookies_adicionados and ctx2.cookies_adicionados[0]["name"] == "SID"


def test_encerrar_sessao_fecha_o_navegador():
    c = _cliente()
    c.search_photos_all("um gato")
    ctx = _pw(c).contextos[0]
    gf.encerrar_sessao()
    assert ctx.fechado


def test_navegador_fecha_sozinho_quando_fica_ocioso_e_reabre_no_proximo_pedido(monkeypatch):
    monkeypatch.setattr(gf, "OCIOSO_S", 0.2)
    c = _cliente()
    c.search_photos_all("um gato")
    ctx = _pw(c).contextos[0]
    fim = time.time() + 5
    while not ctx.fechado and time.time() < fim:
        time.sleep(0.05)
    assert ctx.fechado
    assert len(c.search_photos_all("um cachorro")) == 1
    assert FakeManager.aberturas == 2


def test_auto_com_todos_os_navegadores_quebrados_lista_o_que_falhou():
    c = _cliente(flow_cfg={"navegadores_quebrados": ("chromium", "firefox", "webkit")})
    with pytest.raises(gf.GoogleFlowError, match="Nenhum navegador"):
        c.search_photos_all("um gato")


def test_auto_cai_pro_firefox_quando_o_chromium_esta_quebrado():
    c = _cliente(flow_cfg={"navegadores_quebrados": ("chromium",)})
    assert len(c.search_photos_all("um gato")) == 1
    assert _pw(c).contextos[0].kwargs["_tipo"] == "firefox"


def test_navegador_escolhido_e_exe_customizado():
    c = _cliente(cfg={"flow_navegador": "edge"})
    c.search_photos_all("um gato")
    kw = _pw(c).contextos[0].kwargs
    assert kw["channel"] == "msedge" and kw["_perfil"].endswith("edge")

    c2 = _cliente(cfg={"flow_exe": "C:\\brave\\brave.exe"})
    c2.search_photos_all("outro gato")
    kw2 = _pw(c2).contextos[0].kwargs
    assert kw2["executable_path"] == "C:\\brave\\brave.exe" and kw2["_perfil"].endswith("custom")


def test_navegador_desconhecido_da_erro():
    c = _cliente(cfg={"flow_navegador": "netscape"})
    with pytest.raises(gf.GoogleFlowError, match="desconhecido"):
        c.search_photos_all("um gato")


def test_playwright_que_nao_abre_propaga_o_erro_pra_quem_pediu():
    def fabrica_quebrada():
        raise RuntimeError("playwright quebrado")

    c = gf.GoogleFlowClient(site_cfg={}, playwright_factory=fabrica_quebrada)
    with pytest.raises(RuntimeError, match="playwright quebrado"):
        c.search_photos_all("um gato")


# ------------------------------ download / fila ------------------------------
def test_download_photo_copia_pra_pasta_de_trabalho(tmp_path):
    c = _cliente()
    foto = c.search_photos_all("um gato")[0]
    destino = c.download_photo(foto, output_dir=str(tmp_path / "trabalho"))
    assert os.path.exists(destino) and os.path.dirname(destino) == str(tmp_path / "trabalho")
    assert os.path.exists(foto.local_path)  # o original (cache) continua lá


def test_download_photo_de_arquivo_inexistente_da_erro(tmp_path):
    c = _cliente()
    foto = c.search_photos_all("um gato")[0]
    os.remove(foto.local_path)
    with pytest.raises(gf.GoogleFlowError):
        c.download_photo(foto, output_dir=str(tmp_path))


def test_pedidos_simultaneos_entram_em_fila_no_mesmo_navegador_e_na_mesma_conversa():
    c = _cliente(atraso=0.05)
    erros, resultados = [], []

    def _gera(texto):
        try:
            resultados.append(c.search_photos_all(texto))
        except Exception as e:  # noqa: BLE001
            erros.append(e)

    threads = [threading.Thread(target=_gera, args=(f"gato {i}",)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not erros and len(resultados) == 5
    assert FakeManager.aberturas == 1 and FakeManager.max_ativos == 1
    ctx = _pw(c).contextos[0]
    assert len(_pw(c).contextos) == 1 and len(ctx.paginas_criadas) == 1
    assert sorted(ctx.paginas_criadas[0].digitado) == sorted(f"gere a imagem de gato {i} proporção 16x9" for i in range(5))


def test_mesmo_pedido_em_threads_simultaneas_gera_uma_vez_so():
    c = _cliente(atraso=0.05)
    threads = [threading.Thread(target=c.search_photos_all, args=("o mesmo gato",)) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert _pw(c).log.count("enviar") == 1


def test_sem_playwright_instalado_da_erro_de_instalacao(monkeypatch):
    monkeypatch.setattr(gf, "PLAYWRIGHT_DISPONIVEL", False)
    with pytest.raises(gf.GoogleFlowError, match="pip install playwright"):
        gf.GoogleFlowClient(site_cfg={})


def test_session_close_nao_quebra():
    _cliente().session.close()  # ClientFactory.close_all() chama isso


def test_timeout_da_geracao_vem_da_config():
    assert _cliente(cfg={"flow_timeout_seconds": 120}).timeout_geracao_s == 120
    assert _cliente(cfg={}).timeout_geracao_s == gf.TIMEOUT_GERACAO_S
    assert _cliente(cfg={"flow_timeout_seconds": "lixo"}).timeout_geracao_s == gf.TIMEOUT_GERACAO_S


# ============================ VÁRIAS CONTAS ============================
def _logada(conta):
    p = gf.arquivo_sessao(conta)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}", encoding="utf-8")


def _estado(conta):
    return {c["nome"]: c for c in gf.listar_contas()}[conta]


def test_detecta_limite_em_portugues_e_ingles_e_nao_confunde_recusa_comum():
    assert gf.texto_indica_limite("Você atingiu o limite de créditos.")
    assert gf.texto_indica_limite("You have run out of credits")
    assert gf.texto_indica_limite("Daily limit reached")
    assert gf.texto_indica_limite("Cota excedida")
    assert not gf.texto_indica_limite("Não posso gerar imagens de pessoas reais.")
    assert not gf.texto_indica_limite("")


def test_mensagem_real_do_flow_confirmada_pelo_usuario_e_detectada():
    # "Você chegou ao limite de uso. Tente de novo mais tarde." (classe .error-text)
    assert gf.texto_indica_limite("Você chegou ao limite de uso. Tente de novo mais tarde.")
    assert ".error-text" in gf.SEL_AVISOS


def test_palavras_extras_do_usuario_entram_na_deteccao():
    assert not gf.texto_indica_limite("Sua reserva zerou")
    assert gf.texto_indica_limite("Sua reserva zerou", "zerou")
    assert gf.texto_indica_limite("Sua reserva acabou", "zerou; ACABOU")


def test_sem_nada_cadastrado_existe_so_a_conta_principal():
    assert [c["nome"] for c in gf.listar_contas()] == ["principal"]


def test_adicionar_listar_e_remover_conta():
    gf.adicionar_conta("maria@gmail.com")
    gf.adicionar_conta("joao")
    assert gf.nomes_das_contas() == ["principal", "maria@gmail.com", "joao"]
    gf.remover_conta("joao")
    assert gf.nomes_das_contas() == ["principal", "maria@gmail.com"]


@pytest.mark.parametrize("nome", ["", "  ", "tem espaço", "a/b", "x" * 61, "../fora"])
def test_nome_de_conta_invalido(nome):
    with pytest.raises(gf.GoogleFlowError, match="inválido"):
        gf.adicionar_conta(nome)


def test_conta_duplicada_ou_reservada_e_rejeitada_sem_diferenciar_maiusculas():
    gf.adicionar_conta("Maria")
    for nome in ("maria", "MARIA", "principal", "Principal"):
        with pytest.raises(gf.GoogleFlowError, match="Já existe"):
            gf.adicionar_conta(nome)


def test_principal_nao_pode_ser_removida_e_conta_inexistente_da_erro():
    with pytest.raises(gf.GoogleFlowError, match="principal"):
        gf.remover_conta("principal")
    with pytest.raises(gf.GoogleFlowError, match="não encontrada"):
        gf.remover_conta("fantasma")
    with pytest.raises(gf.GoogleFlowError, match="não encontrada"):
        gf.marcar_esgotada("fantasma")


def test_conta_esgotada_volta_sozinha_depois_do_prazo():
    gf.adicionar_conta("b")
    t0 = datetime(2026, 9, 28, 10, 0, 0)
    gf.marcar_esgotada("b", horas=24, agora=t0)
    by = {c["nome"]: c for c in gf.listar_contas(agora=t0 + timedelta(hours=1))}
    assert by["b"]["esgotada"] and by["b"]["esgotada_ate"] == "2026-09-29T10:00:00"
    assert not {c["nome"]: c for c in gf.listar_contas(agora=t0 + timedelta(hours=25))}["b"]["esgotada"]


def test_liberar_conta_e_remover_limpam_o_estado_de_esgotada():
    gf.adicionar_conta("b")
    gf.marcar_esgotada("b")
    assert _estado("b")["esgotada"]
    gf.liberar_conta("b")
    assert not _estado("b")["esgotada"]
    gf.marcar_esgotada("b")
    gf.remover_conta("b")
    gf.adicionar_conta("b")
    assert not _estado("b")["esgotada"]


def test_perfil_da_principal_e_o_de_sempre_e_o_das_outras_tem_sufixo():
    assert gf.perfil_da_conta("chrome").endswith("chrome")
    assert gf.perfil_da_conta("chrome", "b").endswith("chrome--b")
    assert gf.arquivo_sessao().name == "sessao.json"
    assert gf.arquivo_sessao("b").name == "sessao--b.json"
    assert gf.perfil_da_conta("chrome", "a@b.com").endswith("chrome--a@b.com")


def test_escolha_pula_esgotadas_e_prefere_quem_ja_tem_login():
    gf.adicionar_conta("b")
    gf.adicionar_conta("c")
    _logada("c")
    assert gf.escolher_conta_disponivel() == "c"          # b e principal nunca logaram
    _logada("principal")
    assert gf.escolher_conta_disponivel() == "principal"  # ordem da lista entre as logadas
    gf.marcar_esgotada("principal")
    assert gf.escolher_conta_disponivel() == "c"
    gf.marcar_esgotada("c")
    assert gf.escolher_conta_disponivel() == "b"          # ninguém logado livre: cai na 1ª livre


def test_todas_esgotadas_diz_quando_cada_uma_volta():
    gf.adicionar_conta("b")
    gf.marcar_esgotada("principal")
    gf.marcar_esgotada("b")
    with pytest.raises(gf.GoogleFlowSemContas, match="atingiram o limite") as exc:
        gf.escolher_conta_disponivel()
    assert "'principal' volta em" in str(exc.value) and "'b' volta em" in str(exc.value)


# -------- a troca de conta durante a geração --------
def test_limite_atingido_troca_de_conta_e_refaz_o_mesmo_pedido():
    gf.adicionar_conta("b")
    _logada("principal")
    _logada("b")
    c = _cliente(flow_cfg={"sem_credito": {"principal"}})
    fotos = c.search_photos_all("um gato")
    assert len(fotos) == 1                                   # o pedido NÃO se perdeu
    ctxs = _pw(c).contextos
    assert len(ctxs) == 2 and ctxs[0].fechado and not ctxs[1].fechado
    assert ctxs[0].conta_fake == "principal" and ctxs[1].conta_fake == "b"
    assert _estado("principal")["esgotada_imagem"] and not _estado("b")["esgotada_imagem"]
    assert ctxs[1].paginas_criadas[0].settings == {"confirmar": 2, "qtd": 1, "qtd_video": 1}   # projeto novo, já configurado


def test_depois_da_troca_os_proximos_pedidos_seguem_na_nova_conta_sem_reabrir():
    gf.adicionar_conta("b")
    _logada("principal")
    _logada("b")
    c = _cliente(flow_cfg={"sem_credito": {"principal"}})
    c.search_photos_all("um gato")
    c.search_photos_all("um cachorro")
    c.search_photos_all("um pássaro")
    assert len(_pw(c).contextos) == 2
    assert len(_pw(c).contextos[1].paginas_criadas[0].digitado) == 3


def test_percorre_varias_contas_ate_achar_uma_com_limite():
    for n in ("b", "c"):
        gf.adicionar_conta(n)
    for n in ("principal", "b", "c"):
        _logada(n)
    c = _cliente(flow_cfg={"sem_credito": {"principal", "b"}})
    assert len(c.search_photos_all("um gato")) == 1
    assert [x.conta_fake for x in _pw(c).contextos] == ["principal", "b", "c"]
    assert _estado("principal")["esgotada_imagem"] and _estado("b")["esgotada_imagem"] and not _estado("c")["esgotada_imagem"]


def test_todas_as_contas_esgotadas_da_erro_claro_e_nao_abre_navegador_a_toa():
    gf.adicionar_conta("b")
    _logada("principal")
    _logada("b")
    c = _cliente(flow_cfg={"sem_credito": {"principal", "b"}})
    with pytest.raises(gf.GoogleFlowSemContas, match="atingiram o limite"):
        c.search_photos_all("um gato")
    abertos = len(_pw(c).contextos)
    with pytest.raises(gf.GoogleFlowSemContas):
        c.search_photos_all("outro pedido")
    assert len(_pw(c).contextos) == abertos                  # nem tentou abrir de novo


def test_so_com_a_conta_principal_o_limite_da_erro_de_sem_contas_e_marca_a_conta():
    _logada("principal")
    c = _cliente(flow_cfg={"sem_credito": {"principal"}})
    with pytest.raises(gf.GoogleFlowSemContas, match="'principal' volta em"):
        c.search_photos_all("um gato")
    assert _estado("principal")["esgotada_imagem"]


def test_conta_marcada_como_esgotada_a_mao_e_pulada_ja_na_abertura():
    gf.adicionar_conta("b")
    _logada("principal")
    _logada("b")
    gf.marcar_esgotada("principal")
    c = _cliente()
    c.search_photos_all("um gato")
    assert [x.conta_fake for x in _pw(c).contextos] == ["b"]


def test_horas_ate_liberar_vem_da_config():
    gf.adicionar_conta("b")
    _logada("principal")
    _logada("b")
    c = _cliente(cfg={"flow_horas_ate_liberar": 2}, flow_cfg={"sem_credito": {"principal"}})
    antes = datetime.now()
    c.search_photos_all("um gato")
    ate = datetime.fromisoformat(_estado("principal")["imagem_ate"])
    assert timedelta(hours=1, minutes=59) < ate - antes < timedelta(hours=2, minutes=1)


def test_mensagem_de_limite_diferente_so_troca_de_conta_com_a_palavra_extra():
    gf.adicionar_conta("b")
    _logada("principal")
    _logada("b")
    flow_cfg = {"sem_credito": {"principal"}, "texto_limite": "Sua reserva zerou"}
    c = _cliente(flow_cfg=flow_cfg)
    with pytest.raises(gf.GoogleFlowError, match="sem gerar imagem"):   # não reconhecido como limite
        c.search_photos_all("um gato")
    assert not _estado("principal")["esgotada"]

    gf.encerrar_sessao()
    c2 = _cliente(cfg={"flow_palavras_limite": "zerou"}, flow_cfg=flow_cfg)
    assert len(c2.search_photos_all("um gato")) == 1                     # agora reconhece e troca
    assert _estado("principal")["esgotada_imagem"]


def test_conta_sem_login_no_modo_oculto_avisa_qual_conta_precisa_de_login():
    gf.adicionar_conta("b")
    _logada("principal")     # b nunca logou
    c = _cliente(cfg={"browser_visible": False},
                 flow_cfg={"sem_credito": {"principal"}, "precisa_login_contas": {"b"}})
    with pytest.raises(gf.GoogleFlowLoginRequired, match="Conta 'b'") as exc:
        c.search_photos_all("um gato")
    assert "OCULTO" in str(exc.value)


def test_no_modo_cdp_nao_troca_de_conta():
    gf.adicionar_conta("b")
    _logada("principal")
    _logada("b")
    c = _cliente(cfg={"flow_navegador": "cdp"}, flow_cfg={"sem_credito": {"principal"}})
    with pytest.raises(gf.GoogleFlowLimitReached):
        c.search_photos_all("um gato")
    assert len(_pw(c).contextos) == 1
    assert not _estado("principal")["esgotada"] and not _estado("b")["esgotada"]


def test_login_interativo_de_outra_conta_usa_o_perfil_e_a_sessao_dela():
    gf.adicionar_conta("b")
    c = _cliente()
    assert c.login_interativo(conta="b") is True
    ctx = _pw(c).contextos[0]
    assert ctx.conta_fake == "b" and ctx.fechado and ctx.kwargs["_perfil"].endswith("--b")
    assert gf.arquivo_sessao("b").exists() and not gf.arquivo_sessao().exists()


# ============ o Flow não aceita o pedido / avisos na tela / diagnóstico ============
def test_pedido_que_o_flow_nao_aceita_da_erro_claro_com_o_aviso_da_tela():
    c = _cliente(flow_cfg={"pedido_recusado": True, "avisos": "Algo deu errado. Tente de novo."})
    with pytest.raises(gf.GoogleFlowError, match="não aceitou o pedido") as exc:
        c.search_photos_all("um gato")
    assert "Algo deu errado" in str(exc.value)


def test_aviso_de_limite_ao_recusar_o_pedido_vira_limite_e_troca_de_conta():
    gf.adicionar_conta("b")
    _logada("principal")
    _logada("b")
    # a conta principal recusa o pedido com um aviso de limite; a "b" funciona
    c = _cliente(flow_cfg={"sem_credito_recusa": {"principal"}})
    original = FakePage.enviar

    def enviar(self):
        if self.ctx.conta_fake in self.cfg.get("sem_credito_recusa", ()):
            self.log.append("enviar")
            self.cfg["avisos"] = "Você atingiu o limite diário de gerações."
            return
        self.cfg["avisos"] = ""
        original(self)

    FakePage.enviar = enviar
    try:
        assert len(c.search_photos_all("um gato")) == 1
    finally:
        FakePage.enviar = original
    assert [x.conta_fake for x in _pw(c).contextos] == ["principal", "b"]
    assert _estado("principal")["esgotada_imagem"]


def test_botao_de_enviar_desabilitado_da_erro_com_o_aviso():
    c = _cliente(flow_cfg={"botao_desabilitado": True, "avisos": "Sem créditos"})
    with pytest.raises(gf.GoogleFlowSemContas, match="Última mensagem do Flow: .*Sem créditos"):
        c.search_photos_all("um gato")


def test_botao_de_enviar_desabilitado_sem_aviso_conhecido_da_erro_generico():
    c = _cliente(flow_cfg={"botao_desabilitado": True})
    with pytest.raises(gf.GoogleFlowError, match="desabilitado"):
        c.search_photos_all("um gato")


def test_aviso_de_limite_na_tela_sem_nenhuma_resposta_no_chat_e_detectado_na_hora():
    # o agente nunca responde (nem erro), mas um toast avisa do limite: não espera os 5 minutos
    c = _cliente(cfg={"flow_timeout_seconds": 60}, flow_cfg={"estoura_no_pedido": 1, "avisos": "Cota diária excedida"})
    inicio = time.time()
    with pytest.raises(gf.GoogleFlowSemContas, match="Última mensagem do Flow: .*Cota diária excedida"):
        c.search_photos_all("um gato")
    assert time.time() - inicio < 5


def test_timeout_sem_aviso_de_limite_mostra_o_aviso_que_estiver_na_tela():
    c = _cliente(cfg={"flow_timeout_seconds": 1}, flow_cfg={"estoura_no_pedido": 1, "avisos": "Carregando..."})
    with pytest.raises(gf.GoogleFlowError, match="Aviso na tela: Carregando"):
        c.search_photos_all("um gato")


def test_falha_salva_diagnostico_com_captura_e_texto_da_pagina():
    c = _cliente(flow_cfg={"pedido_recusado": True})
    with pytest.raises(gf.GoogleFlowError, match="diagnóstico salvo em") as exc:
        c.search_photos_all("um gato")
    pasta = gf.pasta_dados() / "diagnostico"
    txts = [t for t in pasta.glob("*.txt") if not t.name.endswith("_html.txt")]
    assert len(txts) == 1 and list(pasta.glob("*.png"))
    assert "não aceitou o pedido" in txts[0].read_text(encoding="utf-8")
    assert "texto da página de teste" in txts[0].read_text(encoding="utf-8")
    assert str(txts[0].with_suffix("")) in str(exc.value)


def test_diagnostico_mantem_so_os_20_mais_recentes():
    class Pag:
        def screenshot(self, path=None, **kw):
            open(path, "wb").write(b"x")

        def evaluate(self, script):
            return "t"

    for i in range(25):
        gf.salvar_diagnostico(Pag(), f"falha {i}")
        time.sleep(0.002)
    pasta = gf.pasta_dados() / "diagnostico"
    assert len([t for t in pasta.glob("*.txt") if not t.name.endswith("_html.txt")]) == 20
    assert len(list(pasta.glob("*_html.txt"))) == 20  # o HTML de cada diagnóstico sai junto com ele


def test_diagnostico_nunca_levanta_erro_mesmo_com_pagina_quebrada():
    class Quebrada:
        def screenshot(self, **kw):
            raise RuntimeError("página fechada")

        def evaluate(self, *a):
            raise RuntimeError("página fechada")

    assert gf.salvar_diagnostico(Quebrada(), "falha") is not None   # ainda guarda o motivo


def test_erro_de_login_nao_gera_diagnostico():
    c = _cliente(cfg={"browser_visible": False}, flow_cfg={"precisa_login": True})
    with pytest.raises(gf.GoogleFlowLoginRequired):
        c.search_photos_all("um gato")
    assert not (gf.pasta_dados() / "diagnostico").exists()


# ============================ LOGIN AUTOMÁTICO ============================
class FakeKeyring:
    """Substitui o pacote `keyring` de verdade nos testes (um dict em memória)."""
    def __init__(self):
        self.dados = {}

    def set_password(self, servico, conta, senha):
        self.dados[(servico, conta)] = senha

    def get_password(self, servico, conta):
        return self.dados.get((servico, conta))

    def delete_password(self, servico, conta):
        self.dados.pop((servico, conta), None)


@pytest.fixture
def fake_keyring(monkeypatch):
    modulo = FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", modulo)
    return modulo


def test_conta_pode_ter_email_opcional_pro_login_automatico():
    gf.adicionar_conta("maria", email="maria@gmail.com")
    gf.adicionar_conta("joao")
    por_nome = {c["nome"]: c for c in gf.listar_contas()}
    assert por_nome["maria"]["email"] == "maria@gmail.com"
    assert por_nome["joao"]["email"] == ""
    assert por_nome["principal"]["email"] == ""


def test_email_invalido_ao_adicionar_ou_editar():
    with pytest.raises(gf.GoogleFlowError, match="E-mail"):
        gf.adicionar_conta("x", email="sem-arroba")
    gf.adicionar_conta("b")
    with pytest.raises(gf.GoogleFlowError, match="E-mail"):
        gf.definir_email("b", "sem-arroba")


def test_definir_email_atualiza_conta_existente():
    gf.adicionar_conta("b")
    gf.definir_email("b", "b@gmail.com")
    assert {c["nome"]: c for c in gf.listar_contas()}["b"]["email"] == "b@gmail.com"


def test_definir_email_de_conta_inexistente_da_erro():
    with pytest.raises(gf.GoogleFlowError, match="não encontrada"):
        gf.definir_email("fantasma", "x@y.com")


def test_definir_email_da_principal_agora_funciona_como_qualquer_outra_conta():
    gf.definir_email("principal", "eu@gmail.com")
    assert {c["nome"]: c for c in gf.listar_contas()}["principal"]["email"] == "eu@gmail.com"


def test_sem_keyring_instalado_nao_ha_senha_salva_e_nao_quebra(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)  # simula ausência do pacote
    import builtins
    real_import = builtins.__import__

    def fake_import(nome, *a, **kw):
        if nome == "keyring":
            raise ImportError("no module")
        return real_import(nome, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert gf.keyring_disponivel() is False
    assert gf.obter_senha("qualquer") is None
    gf.remover_senha("qualquer")  # não pode levantar erro
    with pytest.raises(gf.GoogleFlowError, match="keyring"):
        gf.salvar_senha("qualquer", "123")


def test_salvar_obter_e_remover_senha_via_keyring(fake_keyring):
    assert gf.keyring_disponivel() is True
    assert gf.obter_senha("maria") is None
    gf.salvar_senha("maria", "minhasenha123")
    assert gf.obter_senha("maria") == "minhasenha123"
    assert fake_keyring.dados == {(gf.SERVICO_KEYRING, "maria"): "minhasenha123"}
    gf.remover_senha("maria")
    assert gf.obter_senha("maria") is None


def test_senha_nunca_vai_pro_contas_json(fake_keyring):
    gf.adicionar_conta("maria", email="maria@gmail.com")
    gf.salvar_senha("maria", "supersecreta")
    conteudo = gf.arquivo_contas().read_text(encoding="utf-8")
    assert "supersecreta" not in conteudo


def test_listar_contas_informa_se_tem_senha_salva(fake_keyring):
    gf.adicionar_conta("maria")
    assert {c["nome"]: c for c in gf.listar_contas()}["maria"]["tem_senha_salva"] is False
    gf.salvar_senha("maria", "x")
    assert {c["nome"]: c for c in gf.listar_contas()}["maria"]["tem_senha_salva"] is True


def test_remover_conta_esquece_a_senha_salva(fake_keyring):
    gf.adicionar_conta("maria")
    gf.salvar_senha("maria", "x")
    gf.remover_conta("maria")
    assert gf.obter_senha("maria") is None


def test_login_automatico_preenche_email_senha_e_confirma():
    c = _cliente(flow_cfg={"login_automatico_necessario": True})
    assert c.login_automatico("principal", "eu@gmail.com", "minhasenha") is True
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert pagina.email_preenchido == "eu@gmail.com"
    assert pagina.senha_preenchida == "minhasenha"
    log = _pw(c).log
    assert log.index("google_email_proximo") < log.index("google_senha_proximo")


def test_login_automatico_usa_o_perfil_da_conta_informada():
    gf.adicionar_conta("b")
    c = _cliente(flow_cfg={"login_automatico_necessario": True})
    c.login_automatico("b", "b@gmail.com", "senha")
    assert _pw(c).contextos[0].conta_fake == "b"
    assert gf.arquivo_sessao("b").exists() and not gf.arquivo_sessao().exists()


def test_ja_logada_login_automatico_nao_mexe_nos_campos():
    c = _cliente()  # sem "login_automatico_necessario": já está logada
    assert c.login_automatico("principal", "eu@gmail.com", "minhasenha") is True
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert pagina.email_preenchido == "" and "google_email_proximo" not in _pw(c).log


def test_login_automatico_fecha_a_janela_no_final_como_o_manual():
    c = _cliente(flow_cfg={"login_automatico_necessario": True})
    c.login_automatico("principal", "eu@gmail.com", "minhasenha")
    assert _pw(c).contextos[0].fechado


def test_senha_errada_ou_bloqueio_do_google_deixa_erro_claro_com_diagnostico():
    c = _cliente(flow_cfg={"login_automatico_necessario": True, "bloqueia_login_automatico": True,
                            "avisos": "Senha incorreta."})
    with pytest.raises(gf.GoogleFlowLoginRequired, match="verificação em duas etapas") as exc:
        c.login_automatico("principal", "eu@gmail.com", "senhaerrada")
    assert "Senha incorreta" in str(exc.value) and "diagnóstico salvo em" in str(exc.value)
    pasta = gf.pasta_dados() / "diagnostico"
    assert list(pasta.glob("*.txt"))


def test_campo_de_email_que_nao_aparece_e_tratado_como_falha_de_login():
    c = _cliente(flow_cfg={"login_automatico_necessario": True, "campos_google_ausentes": {gf.SEL_GOOGLE_EMAIL}})
    with pytest.raises(gf.GoogleFlowLoginRequired):
        c.login_automatico("principal", "eu@gmail.com", "senha")


def test_login_automatico_nao_funciona_no_modo_cdp():
    c = _cliente(cfg={"flow_navegador": "cdp"})
    with pytest.raises(gf.GoogleFlowError, match="cdp"):
        c.login_automatico("principal", "eu@gmail.com", "senha")
    assert c._managers == []  # nem chegou a abrir o playwright


def test_login_automatico_libera_a_sessao_de_geracao_que_usa_o_mesmo_perfil():
    c = _cliente()
    c.search_photos_all("um gato")
    geracao = _pw(c).contextos[0]
    assert not geracao.fechado
    c.login_automatico("principal", "eu@gmail.com", "senha")
    assert geracao.fechado


# ============ seletores reais confirmados + caixas de boas-vindas do Flow ============
def test_login_automatico_vai_direto_pra_pagina_de_login_do_google():
    c = _cliente(flow_cfg={"login_automatico_necessario": True})
    c.login_automatico("principal", "eu@gmail.com", "minhasenha")
    visitadas = _pw(c).contextos[0].visitadas
    assert gf.GOOGLE_LOGIN_URL in visitadas
    assert visitadas.index(gf.GOOGLE_LOGIN_URL) < visitadas.index(gf.FLOW_URL_POS_LOGIN)


def test_login_automatico_usa_os_seletores_reais_confirmados():
    assert gf.SEL_GOOGLE_EMAIL == "#identifierId"
    assert gf.SEL_GOOGLE_SENHA == 'input[name="Passwd"]'
    assert "Avançar" in gf.SEL_GOOGLE_EMAIL_PROXIMO and "Avançar" in gf.SEL_GOOGLE_SENHA_PROXIMO


def test_dialogos_de_boas_vindas_sao_dispensados_automaticamente():
    c = _cliente(flow_cfg={"qtd_dialogos_boasvindas": 2, "dialogo_2_precisa_rolar": True})
    fotos = c.search_photos_all("um gato")
    assert len(fotos) == 1
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert pagina.dialogos_pendentes == 0
    assert pagina.dialogo_2_rolado is True
    assert _pw(c).log.count("dialogo_avancar") == 2
    # os diálogos são dispensados ANTES de clicar em "Novo projeto"
    assert _pw(c).log.index("dialogo_avancar") < _pw(c).log.index("novo_projeto")


def test_sem_dialogo_nenhum_nao_muda_nada_no_fluxo_normal():
    c = _cliente()  # qtd_dialogos_boasvindas não definido = 0 (padrão)
    assert len(c.search_photos_all("um gato")) == 1
    assert "dialogo_avancar" not in _pw(c).log


def test_segundo_dialogo_so_avanca_depois_de_rolar_ate_o_fim():
    c = _cliente(flow_cfg={"qtd_dialogos_boasvindas": 2, "dialogo_2_precisa_rolar": True,
                            "campos_google_ausentes": ()})
    fotos = c.search_photos_all("um gato")
    assert len(fotos) == 1  # mesmo com a exigência de rolar, o site consegue passar (rola sozinho)
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert pagina.dialogo_2_rolado is True


def test_login_automatico_tambem_passa_pelos_dialogos_de_boas_vindas():
    c = _cliente(flow_cfg={"login_automatico_necessario": True, "qtd_dialogos_boasvindas": 2})
    assert c.login_automatico("principal", "eu@gmail.com", "minhasenha") is True
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert pagina.dialogos_pendentes == 0


def test_dialogo_que_nunca_aparece_nao_atrasa_nem_quebra_o_fluxo():
    # qtd_dialogos_boasvindas=0 é o padrão -- confirma que search_photos_all
    # continua funcionando normalmente sem nenhum log de diálogo
    c = _cliente(flow_cfg={"qtd_dialogos_boasvindas": 0})
    assert len(c.search_photos_all("um gato")) == 1
    assert "dialogo_avancar" not in _pw(c).log


# ============ aviso de novidades da versão (depois de "Novo projeto") ============
def test_changelog_e_dispensado_automaticamente():
    c = _cliente(flow_cfg={"changelog_aparece": True})
    assert len(c.search_photos_all("um gato")) == 1
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert pagina.changelog_visivel is False
    assert "changelog_comecar" in _pw(c).log
    # aparece DEPOIS de clicar em "Novo projeto", antes de qualquer coisa na conversa
    log = _pw(c).log
    assert log.index("novo_projeto") < log.index("changelog_comecar") < log.index("digitar")


def test_sem_changelog_nao_muda_nada():
    c = _cliente()  # changelog_aparece = False (padrão)
    assert len(c.search_photos_all("um gato")) == 1
    assert "changelog_comecar" not in _pw(c).log


def test_changelog_e_caixas_de_boas_vindas_juntos_na_mesma_sessao():
    c = _cliente(flow_cfg={"changelog_aparece": True, "qtd_dialogos_boasvindas": 2})
    assert len(c.search_photos_all("um gato")) == 1
    log = _pw(c).log
    # boas-vindas vêm ANTES do clique em "Novo projeto"; o changelog vem DEPOIS
    assert log.index("dialogo_avancar") < log.index("novo_projeto") < log.index("changelog_comecar")


def test_changelog_no_projeto_que_abre_em_nova_aba():
    c = _cliente(flow_cfg={"changelog_aparece": True, "projeto_em_nova_aba": True})
    assert len(c.search_photos_all("um gato")) == 1
    projeto = _pw(c).contextos[0].paginas_criadas[1]  # a aba nova é quem recebe o changelog
    assert projeto.changelog_visivel is False


# ============================ TROCA DE SENHA ============================
def test_gerar_senha_aleatoria_tem_10_caracteres_so_minusculas_e_numeros():
    import string
    for _ in range(20):
        senha = gf.gerar_senha_aleatoria()
        assert len(senha) == 10
        assert all(c in string.ascii_lowercase + string.digits for c in senha)


def test_gerar_senha_aleatoria_aceita_outro_tamanho_e_nao_repete():
    assert len(gf.gerar_senha_aleatoria(16)) == 16
    senhas = {gf.gerar_senha_aleatoria() for _ in range(50)}
    assert len(senhas) == 50  # não repetiu nenhuma


def test_troca_senha_ja_logada_com_reauth_confirma_e_salva(fake_keyring):
    gf.adicionar_conta("b", email="b@gmail.com")
    c = _cliente(flow_cfg={"campos_google_ausentes": {gf.SEL_GOOGLE_EMAIL}})  # já logada, só reauth
    nova = c.trocar_senha("b", "senhaatual123")
    assert len(nova) == 10
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert pagina.senha_preenchida == "senhaatual123"  # reauth com a senha ATUAL
    assert pagina.nova_senha1 == pagina.nova_senha2 == nova
    assert pagina.senha_alterada is True
    assert gf.obter_senha("b") == nova  # já foi salva


def test_troca_senha_usa_a_senha_informada_em_vez_de_gerar(fake_keyring):
    gf.adicionar_conta("b", email="b@gmail.com")
    c = _cliente(flow_cfg={"campos_google_ausentes": {gf.SEL_GOOGLE_EMAIL}})
    nova = c.trocar_senha("b", "senhaatual123", nova_senha="minhaescolhida1")
    assert nova == "minhaescolhida1"
    assert gf.obter_senha("b") == "minhaescolhida1"


def test_troca_senha_faz_login_quando_precisa_usando_o_email_cadastrado(fake_keyring):
    gf.adicionar_conta("b", email="b@gmail.com")
    c = _cliente()  # SEL_GOOGLE_EMAIL visível por padrão no fake => precisa logar
    c.trocar_senha("b", "senhaatual123")
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert pagina.email_preenchido == "b@gmail.com"
    log = _pw(c).log
    assert log.index("google_email_proximo") < log.index("alterar_senha")


def test_troca_senha_sem_email_cadastrado_da_erro_quando_precisa_logar():
    gf.adicionar_conta("b")  # sem e-mail
    c = _cliente()
    with pytest.raises(gf.GoogleFlowError, match="não tem e-mail cadastrado"):
        c.trocar_senha("b", "senhaatual123")


def test_troca_senha_pula_reauth_quando_nao_aparece(fake_keyring):
    gf.adicionar_conta("b", email="b@gmail.com")
    c = _cliente(flow_cfg={"campos_google_ausentes": {gf.SEL_GOOGLE_EMAIL, gf.SEL_GOOGLE_SENHA}})
    nova = c.trocar_senha("b", "senhaatual123")
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert "reauth_avancar" not in _pw(c).log  # não teve reauth pra avançar
    assert pagina.senha_alterada is True
    assert gf.obter_senha("b") == nova


def test_troca_senha_com_captcha_para_e_nao_tenta_resolver():
    gf.adicionar_conta("b", email="b@gmail.com")
    c = _cliente(flow_cfg={"campos_google_ausentes": {gf.SEL_GOOGLE_EMAIL}, "troca_senha_captcha": True})
    with pytest.raises(gf.GoogleFlowError, match="captcha") as exc:
        c.trocar_senha("b", "senhaatual123")
    assert "diagnóstico salvo em" in str(exc.value)
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert pagina.nova_senha1 == ""  # nem chegou a preencher a senha nova
    assert gf.obter_senha("b") is None  # nada foi salvo


def test_troca_senha_que_falha_da_erro_claro_com_diagnostico_e_nao_salva(fake_keyring):
    gf.adicionar_conta("b", email="b@gmail.com")
    c = _cliente(flow_cfg={"campos_google_ausentes": {gf.SEL_GOOGLE_EMAIL}, "troca_senha_falha": True})
    with pytest.raises(gf.GoogleFlowError, match="[Nn]ão consegui confirmar") as exc:
        c.trocar_senha("b", "senhaatualerrada")
    assert "diagnóstico salvo em" in str(exc.value)
    assert gf.obter_senha("b") is None  # nada foi salvo -- não sabemos se a senha antiga ainda vale


def test_troca_senha_fecha_a_janela_no_final(fake_keyring):
    gf.adicionar_conta("b", email="b@gmail.com")
    c = _cliente(flow_cfg={"campos_google_ausentes": {gf.SEL_GOOGLE_EMAIL}})
    c.trocar_senha("b", "senhaatual123")
    assert _pw(c).contextos[0].fechado


def test_troca_senha_nao_funciona_no_modo_cdp():
    gf.adicionar_conta("b", email="b@gmail.com")
    c = _cliente(cfg={"flow_navegador": "cdp"})
    with pytest.raises(gf.GoogleFlowError, match="cdp"):
        c.trocar_senha("b", "senhaatual123")
    assert c._managers == []


def test_troca_senha_da_conta_principal_nao_precisa_de_email(fake_keyring):
    # a principal não tem e-mail cadastrável -- só funciona quando já está logada
    c = _cliente(flow_cfg={"campos_google_ausentes": {gf.SEL_GOOGLE_EMAIL}})
    nova = c.trocar_senha("principal", "senhaatual123")
    assert gf.obter_senha("principal") == nova


# ============ configuração padrão de vídeo (quantidade x1 + modelo) ============
def test_video_x1_e_marcado_junto_com_o_de_imagem():
    c = _cliente()
    c.search_photos_all("um gato")
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert pagina.settings["qtd_video"] == 1


def test_x1_video_nao_marcado_da_erro_claro():
    c = _cliente(flow_cfg={"x1_video_falha": True})
    with pytest.raises(gf.GoogleFlowError, match='vídeos "x1"'):
        c.search_photos_all("um gato")


def test_modelo_de_video_e_escolhido_quando_configurado():
    c = _cliente(cfg={"flow_modelo_video": "Veo 3.1 - Lite"})
    c.search_photos_all("um gato")
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert pagina.settings.get("modelo_video") == "Veo 3.1 - Lite"
    log = _pw(c).log
    assert log.index("abrir_menu_modelo_video") < log.index("escolher_modelo_video:Veo 3.1 - Lite") < log.index("salvar")


def test_sem_modelo_configurado_nao_mexe_no_seletor_de_modelo():
    c = _cliente(cfg={"flow_modelo_video": ""})
    c.search_photos_all("um gato")
    assert "abrir_menu_modelo_video" not in _pw(c).log
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert "modelo_video" not in pagina.settings


def test_outro_modelo_pode_ser_escolhido():
    c = _cliente(cfg={"flow_modelo_video": "Veo 3.1 - Quality"})
    c.search_photos_all("um gato")
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert pagina.settings.get("modelo_video") == "Veo 3.1 - Quality"


def test_botao_do_modelo_ausente_nao_trava_a_configuracao_inteira():
    c = _cliente(cfg={"flow_modelo_video": "Veo 3.1 - Lite"}, flow_cfg={"botao_modelo_video_ausente": True})
    assert len(c.search_photos_all("um gato")) == 1  # segue em frente e salva mesmo assim
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert pagina.settings == {"confirmar": 2, "qtd": 1, "qtd_video": 1}  # sem "modelo_video": não conseguiu escolher
    assert pagina.dialog_aberto is False  # ainda assim salvou e fechou o painel


def test_modelo_nao_encontrado_no_menu_nao_trava_a_configuracao_inteira():
    c = _cliente(cfg={"flow_modelo_video": "Modelo Que Não Existe Mais"}, flow_cfg={"modelo_video_nao_encontrado": True})
    assert len(c.search_photos_all("um gato")) == 1
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert "modelo_video" not in pagina.settings
    assert pagina.dialog_aberto is False


# ============ página de apresentação (flow.google.com/about) ============
def test_pagina_de_apresentacao_e_passada_automaticamente():
    c = _cliente(flow_cfg={"pagina_apresentacao": True})
    assert len(c.search_photos_all("um gato")) == 1
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert pagina.pagina_apresentacao is False
    log = _pw(c).log
    assert log.index("crie_com_o_flow") < log.index("novo_projeto")


def test_sem_pagina_de_apresentacao_nao_muda_nada():
    c = _cliente()  # pagina_apresentacao=False (padrão)
    assert len(c.search_photos_all("um gato")) == 1
    assert "crie_com_o_flow" not in _pw(c).log


def test_pagina_de_apresentacao_tambem_e_passada_no_login_automatico():
    c = _cliente(flow_cfg={"login_automatico_necessario": True, "pagina_apresentacao": True})
    assert c.login_automatico("principal", "eu@gmail.com", "minhasenha") is True
    pagina = _pw(c).contextos[0].paginas_criadas[0]
    assert pagina.pagina_apresentacao is False
    assert "crie_com_o_flow" in _pw(c).log


def test_pagina_de_apresentacao_e_passada_no_login_manual():
    c = _cliente(cfg={"browser_visible": True}, flow_cfg={"precisa_login": True, "login_ok_depois": True, "pagina_apresentacao": True})
    assert len(c.search_photos_all("um gato")) == 1
    assert "crie_com_o_flow" in _pw(c).log
