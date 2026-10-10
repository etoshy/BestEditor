"""
v84 — aba 📜 Roteiro do YouTube: transcrição do vídeo (legenda ou Whisper) →
IA reescreve + lista as cenas (JSON) → IA traduz / põe tags / acha anúncios e
chamadas (JSON) → roteiro pro Gerador de voz e cenas pro Cortar do YouTube.
Sem rede: um yt-dlp falso.
"""
import json
import os

import pytest

import roteiros_yt as ry


# ------------------------------------------------------------------ yt-dlp falso
class _Resp:
    def __init__(self, txt):
        self.txt = txt

    def read(self):
        return self.txt.encode("utf-8")


def _ytdlp(info, arquivos, baixou=None):
    class YDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            if download:
                caminho = self.opts["outtmpl"].replace("%(ext)s", "m4a")
                open(caminho, "wb").write(b"audio")
                if baixou is not None:
                    baixou.append(caminho)
                return dict(info, ext="m4a")
            return info

        def prepare_filename(self, i):
            return self.opts["outtmpl"].replace("%(ext)s", "m4a")

        def urlopen(self, url):
            return _Resp(arquivos[url])

    return type("M", (), {"YoutubeDL": YDL})


_JSON3 = json.dumps({"events": [
    {"tStartMs": 0, "dDurationMs": 4000, "segs": [{"utf8": "Hoje vamos ver"}, {"utf8": " as cenas mais tensas."}]},
    {"tStartMs": 4000, "dDurationMs": 1, "segs": [{"utf8": "\n"}]},
    {"tStartMs": 5000, "dDurationMs": 9000, "segs": [{"utf8": "Em Cães de Aluguel, o Mr. Blonde dança."}]},
    {"tStartMs": 15000, "dDurationMs": 5000, "segs": [{"utf8": "E depois vem o pior."}]},
]})

_VTT_ROLANDO = """WEBVTT

00:00:00.000 --> 00:00:02.000
hoje vamos

00:00:02.000 --> 00:00:04.000
hoje vamos
<00:00:02.500><c>ver as cenas</c>

00:00:04.000 --> 00:00:06.000
ver as cenas
mais tensas.
"""


class TestTranscricao:
    def test_legenda_manual_no_idioma_do_video_vem_primeiro(self, tmp_path):
        info = {"title": "Top cenas", "channel": "Canal X", "duration": 600, "language": "pt",
                "subtitles": {"en": [{"ext": "json3", "url": "u-en"}], "pt-BR": [{"ext": "json3", "url": "u-pt"}]},
                "automatic_captions": {"pt-orig": [{"ext": "json3", "url": "u-auto"}]}}
        tr = ry.extrair_transcricao("https://youtu.be/x", str(tmp_path), ytdlp_module=_ytdlp(info, {"u-pt": _JSON3}))
        assert tr["fonte"] == "legenda do vídeo" and tr["idioma"] == "pt-BR" and tr["titulo"] == "Top cenas"
        texto = ry.texto_da_transcricao(tr)
        assert texto.startswith("[0:00] Hoje vamos ver as cenas mais tensas.") and "[0:15] E depois vem o pior." in texto

    def test_sem_manual_usa_a_automatica_original(self, tmp_path):
        info = {"title": "t", "automatic_captions": {"en": [{"ext": "vtt", "url": "u-en"}], "ja-orig": [{"ext": "vtt", "url": "u-ja"}]}}
        tr = ry.extrair_transcricao("u", str(tmp_path), ytdlp_module=_ytdlp(info, {"u-ja": _VTT_ROLANDO}))
        assert tr["fonte"] == "legenda automática" and tr["idioma"] == "ja"
        assert ry.texto_da_transcricao(tr, com_tempo=False) == "hoje vamos ver as cenas mais tensas."  # sem a repetição "rolando"

    def test_sem_legenda_usa_o_whisper_e_apaga_o_audio(self, tmp_path):
        baixou = []
        tr = ry.extrair_transcricao("u", str(tmp_path), ytdlp_module=_ytdlp({"title": "t"}, {}, baixou),
                                    whisper_fn=lambda caminho, info=None: (info.update(language="en") or
                                                                           [{"start": 0, "end": 3, "text": "Hello there."}]))
        assert tr["fonte"] == "whisper" and tr["idioma"] == "en" and tr["blocos"][0]["texto"] == "Hello there."
        assert baixou and not os.path.exists(baixou[0])

    def test_sem_legenda_e_sem_whisper_explica(self, tmp_path):
        with pytest.raises(ry.RoteiroError, match="não tem legenda"):
            ry.extrair_transcricao("u", str(tmp_path), ytdlp_module=_ytdlp({"title": "t"}, {}), usar_whisper=False)

    def test_transcricao_colada_com_e_sem_tempo(self):
        com = ry.transcricao_de_texto("0:00 Oi pessoal\ncontinua aqui\n[1:05] Agora a cena do filme.")
        assert com["com_tempo"] and ry.texto_da_transcricao(com).startswith("[0:00] Oi pessoal continua aqui")
        sem = ry.transcricao_de_texto("Primeiro parágrafo.\n\nSegundo parágrafo.")
        assert not sem["com_tempo"] and len(sem["blocos"]) == 2
        assert ry.texto_da_transcricao(sem) == "Primeiro parágrafo.\n\nSegundo parágrafo."


# ------------------------------------------------------------------ modelos e prompt 1
class TestPromptAnalise:
    def _p(self):
        return {"id": "a" * 10, "titulo": "Top cenas", "url": "https://youtu.be/x",
                "transcricao": ry.transcricao_de_texto("0:00 Oi pessoal, como eu disse no vídeo passado\n0:12 Em Cães de Aluguel o Mr. Blonde dança")}

    def test_modelo_padrao_pede_o_que_foi_combinado(self):
        p = ry.prompt_analise(self._p(), ry.obter_modelo("/nao/existe", "reescrever_cenas"), "português do Brasil")
        assert '("Top cenas")' in p
        assert "[0:12] Em Cães de Aluguel" in p and "EQUIVALENTES" in p and "português do Brasil" in p
        assert '"cenas"' in p and '"no_video_original"' in p and '"busca_youtube"' in p
        assert "{transcricao}" not in p

    def test_sem_transcricao_da_erro(self):
        with pytest.raises(ry.RoteiroError):
            ry.prompt_analise({"id": "b" * 10}, ry.MODELOS_FABRICA[0])

    def test_modelos_proprios_e_por_cima_do_de_fabrica(self, tmp_path):
        base = str(tmp_path)
        meu = ry.salvar_modelo(base, "Meu estilo", "Reescreva engraçado: {titulo}")
        assert meu["id"].startswith("meu_") and "{transcricao}" in meu["texto"]  # sem o marcador, ele entra no fim
        ry.salvar_modelo(base, "Padrão (meu)", "Outro texto {transcricao}", "reescrever_cenas")
        ms = {m["id"]: m for m in ry.modelos(base)}
        assert ms["reescrever_cenas"]["nome"] == "Padrão (meu)" and not ms["reescrever_cenas"]["fabrica"]
        ry.excluir_modelo(base, "reescrever_cenas")
        assert ry.obter_modelo(base, "reescrever_cenas")["fabrica"]
        assert ry.obter_modelo(base, meu["id"])["nome"] == "Meu estilo"


# ------------------------------------------------------------------ leitura da análise
_ANALISE = """Claro! Aqui está:
```json
{"titulo": "As cenas mais tensas", "idioma": "pt-BR",
 "roteiro": "Tem cenas que grudam na memória.\\n\\nComo a do Mr. Blonde dançando com a navalha.",
 "cenas": [
  {"obra": "Reservoir Dogs (Cães de Aluguel)", "tipo": "Filme", "ano": 1992, "momento": "Mr. Blonde dança Stuck in the Middle with You",
   "no_video_original": {"inicio": "0:12", "fim": "0:30"}, "trecho_do_roteiro": "Como a do Mr. Blonde", "busca_youtube": "Reservoir Dogs Mr Blonde dance scene", "certeza": "alta"},
  {"obra": "Attack on Titan", "tipo": "anime", "momento": "a queda da muralha", "no_video_original": {"inicio": "lá pelo meio"}},
  {"tipo": "filme"}
 ],
 "removidos": ["\\"como eu disse no vídeo passado\\" — só fazia sentido no canal original"]}
```"""


class TestLerAnalise:
    def test_le_e_normaliza(self):
        an = ry.ler_analise(_ANALISE)
        assert an["titulo"] == "As cenas mais tensas" and "navalha" in an["roteiro"]
        a, b = an["cenas"]  # a 3ª (sem obra nem momento) sai
        assert (a["id"], a["tipo"], a["ano"], a["inicio"], a["fim"], a["certeza"]) == (1, "filme", "1992", "0:12", "0:30", "alta")
        assert b["inicio"] == "" and b["busca_youtube"] == "Attack on Titan a queda da muralha"
        assert len(an["removidos"]) == 1

    def test_json_invalido(self):
        with pytest.raises(ry.RoteiroError):
            ry.ler_analise("não sei")
        with pytest.raises(ry.RoteiroError):
            ry.ler_analise('{"outra": 1}')


# ------------------------------------------------------------------ passo 2
def _projeto_com_analise():
    return {"id": "c" * 10, "url": "https://www.youtube.com/watch?v=abc", "analise": ry.ler_analise(_ANALISE)}


class TestPromptAcoes:
    def test_traduzir_tags_ads_cta(self):
        p = ry.prompt_acoes(_projeto_com_analise(), ["traduzir", "tags", "ads", "cta"], idioma="en")
        assert "TRADUZA" in p and "inglês" in p.lower()
        assert "[laugh] [chuckle] [gasp] [cough] [sigh] [groan] [sniff] [shush] [clear throat]" in p
        assert "[angry] [crying] [dramatic] [fear] [happy] [narration] [sarcastic] [surprised] [whispering] [advertisement]" in p
        assert "INÍCIO da frase" in p and "ANÚNCIO" in p and "CHAMADAS PRA AÇÃO" in p and "[[INSCREVA]]" in p
        assert "1. Reservoir Dogs (Cães de Aluguel) (filme, 1992)" in p and '"roteiro_final"' in p

    def test_sem_cenas_marcar_e_extra(self):
        p = ry.prompt_acoes(_projeto_com_analise(), ["sem_cenas", "marcar_cenas"], extra="tom mais misterioso", cta_no_texto=False)
        assert "SEM mostrar as cenas" in p and "[CENA n]" in p and "tom mais misterioso" in p and "TRADUZA" not in p

    def test_tags_sem_ingles_avisa(self):
        assert "só funcionam com o modelo em INGLÊS" in ry.prompt_acoes(_projeto_com_analise(), ["tags"])

    def test_erros(self):
        with pytest.raises(ry.RoteiroError):
            ry.prompt_acoes({"id": "d" * 10}, ["tags"])
        with pytest.raises(ry.RoteiroError):
            ry.prompt_acoes(_projeto_com_analise(), [])


_RESULTADO = json.dumps({
    "idioma": "en",
    "roteiro_final": "[dramatic] Some scenes stick with you forever.\n\n[CENA 1]\nLike Mr. Blonde dancing with a razor [gasp]. "
                     "Smash that like button if you remember it! [evil laugh] And then it gets worse.",
    "ads": [{"depois_de": "And then it gets worse.", "motivo": "virada"}, {"depois_de": "texto que não existe", "motivo": "x"}],
    "ctas": [{"tipo": "like", "texto": "Smash that like button if you remember it!", "depois_de": "dancing with a razor [gasp]."}],
    "cenas": [{"id": 1, "marcador": "[CENA 1]", "como_ficou": "mostrada"}, {"id": 2, "como_ficou": "removida"}],
    "titulos": ["The Most Tense Scenes"], "gancho": "Some scenes never leave you.",
})


class TestLerResultado:
    def test_le_tudo_e_avisa(self):
        r = ry.ler_resultado(_RESULTADO, _projeto_com_analise())
        assert r["idioma"] == "en" and r["tags"] == ["dramatic", "gasp"]
        assert any("[evil laugh]" in a for a in r["avisos"])  # tag que o Turbo não conhece
        assert any("não foi achado" in a for a in r["avisos"])
        assert r["ads"][0]["posicao"] == 1.0 and r["ads"][1]["posicao"] is None
        assert 0 < r["ctas"][0]["posicao"] < 1
        c1, c2 = r["cenas"]
        assert c1["obra"].startswith("Reservoir") and c1["marcador"] == "[CENA 1]" and c2["como_ficou"] == "removida"
        assert r["titulos"] == ["The Most Tense Scenes"] and r["palavras"] > 10

    def test_saidas_pro_gerador_de_voz_e_pro_cortar(self):
        p = _projeto_com_analise()
        p["resultado"] = ry.ler_resultado(_RESULTADO, p)
        voz = ry.roteiro_para_voz(p)
        assert "[CENA 1]" not in voz and "[dramatic]" in voz and "\n\n\n" not in voz
        assert ry.texto_para_cortar(p) == ""  # nenhuma cena com link ainda
        assert ry.texto_para_cortar(p, do_original=True) == "https://www.youtube.com/watch?v=abc 0:12 - 0:30 1. Reservoir Dogs (Cães de Aluguel) — Mr. Blonde dança Stuck in the Middle with You"
        p["resultado"]["cenas"][1].update(link="https://youtu.be/aot", link_inicio="1:00", link_fim="1:20")
        assert ry.texto_para_cortar(p).startswith("https://youtu.be/aot 1:00 - 1:20 2. Attack on Titan")


# ------------------------------------------------------------------ site
@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def test_fluxo_completo_no_site(A):
    c = A.app.test_client()
    r = c.post("/roteiros-yt/novo", data={"texto": "0:00 Oi pessoal\n0:12 Em Cães de Aluguel o Mr. Blonde dança", "titulo": "Teste"})
    pid = r.headers["Location"].rstrip("/").split("/")[-1]
    try:
        html = c.get(f"/roteiros-yt/{pid}").get_data(as_text=True)
        assert "Reescrever o roteiro e listar as cenas" in html and "Tags do Chatterbox Turbo" in html
        assert "📜 Roteiro do YouTube" in c.get("/roteiros-yt").get_data(as_text=True)
        d = c.post(f"/roteiros-yt/{pid}/prompt-analise", json={"modelo_id": "reescrever_cenas", "idioma": "en"}).get_json()
        assert d["ok"] and "[0:12]" in d["prompt"] and "inglês" in d["prompt"].lower()
        assert c.post(f"/roteiros-yt/{pid}/analise", json={"texto": "nada"}).status_code == 400
        d = c.post(f"/roteiros-yt/{pid}/analise", json={"texto": _ANALISE}).get_json()
        assert len(d["analise"]["cenas"]) == 2
        assert c.post(f"/roteiros-yt/{pid}/cena/1", json={"link": "https://youtu.be/rd", "link_inicio": "0:05", "link_fim": "0:20"}).get_json()["ok"]
        d = c.post(f"/roteiros-yt/{pid}/prompt-acoes", json={"acoes": ["traduzir", "tags", "ads"], "idioma": "en"}).get_json()
        assert "TRADUZA" in d["prompt"]
        d = c.post(f"/roteiros-yt/{pid}/resultado", json={"texto": _RESULTADO}).get_json()
        assert d["resultado"]["cenas"][0]["link"] == "https://youtu.be/rd"  # o link escolhido antes continua
        voz = c.get(f"/gerar-voz?roteiro={pid}").get_data(as_text=True)
        assert "Some scenes stick with you forever." in voz and "Chatterbox Turbo" in voz and "[CENA 1]" not in voz
        cortar = c.get(f"/cortar-youtube?roteiro={pid}").get_data(as_text=True)
        assert "https://youtu.be/rd 0:05 - 0:20 1. Reservoir Dogs" in cortar
        assert c.get(f"/roteiros-yt/{pid}/baixar/json").get_json()["resultado"]["idioma"] == "en"
        assert "[CENA 1]" in c.get(f"/roteiros-yt/{pid}/baixar/txt").get_data(as_text=True)
    finally:
        c.post(f"/roteiros-yt/{pid}/excluir")
    assert not os.path.exists(os.path.join(A.BASE_DIR, "roteiros_yt", pid))


# ------------------------------------------------------------------ 🧹 limpar pro TTS
class TestLimparTTS:
    def test_limpeza_local_tira_o_que_engasga_o_tts(self):
        r = ry.limpar_para_tts("# Título **forte**\n[dramatic] Olha isso 😱🔥!!! Ele disse “nunca” — e foi… [Música] (risos)\n"
                               "Muuuuito estranho [evil laugh] [CENA 2] veja https://x.com/a e @canal #shorts.\n"
                               "Tom & Jerry ™ a 30° hoje​ ok ,  ok {nota} Rocky III")
        t = r["texto"]
        for some in ("😱", "**", "#", "“", "—", "[Música]", "(risos)", "[evil laugh]", "https", "@canal", "™", "{", "​", "!!!"):
            assert some not in t, some
        assert "[dramatic]" in t and "[CENA 2]" in t and "Muito estranho" in t and "Tom e Jerry" in t and "30 graus" in t
        assert "Rocky III" in t  # algarismo romano não é "letra repetida"
        tipos = {m["tipo"] for m in r["mudancas"]}
        assert "emojis" in tipos and "tags desconhecidas entre colchetes" in tipos

    def test_ingles(self):
        assert ry.limpar_para_tts("Tom & Jerry at 30°", "en")["texto"] == "Tom and Jerry at 30 degrees"

    def test_texto_limpo_fica_igual(self):
        r = ry.limpar_para_tts("[whispering] Some scenes stick with you. [sigh] Forever.")
        assert r["texto"] == "[whispering] Some scenes stick with you. [sigh] Forever." and r["mudancas"] == []

    def test_opcao_da_ia_no_passo_3(self):
        assert any(k == "limpar_tts" for k, _n, _d in ry.ACOES)
        p = ry.prompt_acoes(_projeto_com_analise(), ["limpar_tts"])
        assert "À PROVA DE TTS" in p and "palavras escritas errado" in p and "por extenso" in p and "NÃO mexa nas tags" in p

    def test_aplicar_e_desfazer(self):
        p = _projeto_com_analise()
        p["resultado"] = ry.ler_resultado(_RESULTADO, p)
        antes = p["resultado"]["roteiro_final"]
        feito = ry.aplicar_limpeza(p)
        assert "[evil laugh]" not in p["resultado"]["roteiro_final"] and feito["pode_desfazer"]
        assert not any("Chatterbox" in a for a in p["resultado"]["avisos"])
        assert "[evil laugh]" not in ry.roteiro_para_voz(p)
        assert ry.desfazer_limpeza(p) and p["resultado"]["roteiro_final"] == antes and not ry.desfazer_limpeza(p)
        assert any("Chatterbox" in a for a in p["resultado"]["avisos"])


def test_site_limpa_sozinho_quando_a_opcao_foi_marcada_e_pelo_botao(A):
    c = A.app.test_client()
    pid = c.post("/roteiros-yt/novo", data={"texto": "0:00 Oi"}).headers["Location"].rstrip("/").split("/")[-1]
    try:
        c.post(f"/roteiros-yt/{pid}/analise", json={"texto": _ANALISE})
        c.post(f"/roteiros-yt/{pid}/prompt-acoes", json={"acoes": ["traduzir", "limpar_tts"], "idioma": "en"})
        d = c.post(f"/roteiros-yt/{pid}/resultado", json={"texto": _RESULTADO}).get_json()
        assert "[evil laugh]" not in d["resultado"]["roteiro_final"] and d["limpeza"]["mudancas"]
        d = c.post(f"/roteiros-yt/{pid}/limpar-tts", json={"desfazer": True}).get_json()
        assert "[evil laugh]" in d["resultado"]["roteiro_final"]
        d = c.post(f"/roteiros-yt/{pid}/limpar-tts", json={}).get_json()
        assert "[evil laugh]" not in d["resultado"]["roteiro_final"]
        assert "🧹 Limpar pro TTS" in c.get(f"/roteiros-yt/{pid}").get_data(as_text=True)
    finally:
        c.post(f"/roteiros-yt/{pid}/excluir")


# ------------------------------------------------------------------ descrição com capítulos + títulos (v84_29)
def test_prompt_pede_descricao_capitulos_e_titulo_traduzido():
    p = _projeto_com_analise()
    p["titulo"] = "Por que os animes são tão viciantes"
    t = ry.prompt_acoes(p, ["traduzir", "descricao"], idioma="en")
    assert "Título do vídeo original: Por que os animes são tão viciantes" in t
    assert '"capitulos"' in t and '"titulo_original"' in t and "Traduza também o título" in t and "5 TÍTULOS" in t


def test_capitulos_viram_timestamps():
    p = _projeto_com_analise()
    roteiro = " ".join(f"palavra{k}" for k in range(300)) + " segunda parte começa aqui " + " ".join(f"fim{k}" for k in range(300))
    texto = json.dumps({"roteiro_final": roteiro, "titulo_original": "Why anime is so addictive",
                        "titulos": ["A", "B"], "descricao": "Um vídeo sobre animes. #anime",
                        "capitulos": [{"titulo": "Intro", "comeca_em": "palavra0 palavra1"},
                                      {"titulo": "Parte 2", "comeca_em": "segunda parte começa aqui"}]})
    r = ry.ler_resultado(texto, p)
    assert [c["titulo"] for c in r["capitulos"]] == ["Intro", "Parte 2"] and r["capitulos"][0]["segundos"] == 0
    assert 110 <= r["capitulos"][1]["segundos"] <= 130  # ~300 palavras a 150/min = 2:00
    d = ry.descricao_com_capitulos(r)
    assert d.startswith("Um vídeo sobre animes.") and "\n0:00 Intro\n" in d + "\n" and "2:0" in d
    assert r["titulo_original"] == "Why anime is so addictive"


def test_capitulos_com_o_tempo_real_do_audio(tmp_path):
    base = str(tmp_path)
    p = ry.criar_projeto(base, texto="[0:00] oi")
    roteiro = "Começo do vídeo aqui. " + " ".join(["bla"] * 40) + " Agora a segunda parte fala de outra coisa. " + " ".join(["ble"] * 40)
    p["analise"] = {"roteiro": roteiro, "cenas": []}
    p["resultado"] = ry.ler_resultado(json.dumps({"roteiro_final": roteiro, "descricao": "D",
                                                  "capitulos": [{"titulo": "Intro", "comeca_em": "Começo do vídeo aqui"},
                                                                {"titulo": "Parte 2", "comeca_em": "Agora a segunda parte fala"}]}), p)
    ry.salvar_projeto(base, p)
    # o TTS falou devagar: cada palavra 0,8 s (o Whisper devolve as palavras com o tempo)
    palavras = [{"word": w, "start": k * 0.8, "end": k * 0.8 + 0.7} for k, w in enumerate(ry._toks(roteiro))]
    res = ry.aplicar_tempos_do_audio(base, p["id"], palavras, duracao=len(palavras) * 0.8)
    caps = res["capitulos"]
    assert caps[0]["segundos_audio"] == 0.0
    assert abs(caps[1]["segundos_audio"] - 44 * 0.8) < 1.0  # "agora" é a 45ª palavra falada
    assert "0:35 Parte 2" in ry.descricao_com_capitulos(res)
    assert ry.carregar_projeto(base, p["id"])["resultado"]["audio"]["com_palavras"]


def test_capitulos_sem_palavras_usa_a_duracao(tmp_path):
    base = str(tmp_path)
    p = ry.criar_projeto(base, texto="[0:00] oi")
    roteiro = " ".join(["a"] * 50) + " virada aqui " + " ".join(["b"] * 48)
    p["analise"] = {"roteiro": roteiro, "cenas": []}
    p["resultado"] = ry.ler_resultado(json.dumps({"roteiro_final": roteiro, "capitulos": [{"titulo": "I", "comeca_em": "a a"}, {"titulo": "II", "comeca_em": "virada aqui"}]}), p)
    ry.salvar_projeto(base, p)
    res = ry.aplicar_tempos_do_audio(base, p["id"], [], duracao=200.0)
    assert 95 <= res["capitulos"][1]["segundos_audio"] <= 105


def test_tirar_experiencias_pessoais_e_citacoes_a_outros_videos():
    import roteiros_yt as ry
    p = {"transcricao": {"blocos": [{"inicio": 0, "texto": "como eu falei no vídeo passado"}]}, "titulo": "T"}
    modelo = ry.MODELOS_FABRICA[0]
    com = ry.prompt_analise(p, modelo)
    assert "vídeo passado" in com and "experiências" in com.lower()
    assert "Sem experiências anteriores" not in ry.prompt_analise(p, modelo, sem_experiencias=False)
    p["analise"] = {"roteiro": "Texto.", "cenas": []}
    assert "REMOVA do roteiro" in ry.prompt_acoes(p, ["sem_experiencias"])
    assert "REMOVA do roteiro" not in ry.prompt_acoes(p, ["tags"])


def test_historico_das_opcoes_o_que_fazer_com_o_roteiro(A):
    """As escolhas do passo "O que fazer com o roteiro" ficam guardadas: projeto
    novo já abre marcado igual à última vez, e dá pra voltar a combinações antigas."""
    import roteiros_yt as ry
    base = A.BASE_DIR
    arq = ry._arquivo_opcoes(base)
    antes = open(arq, encoding="utf-8").read() if os.path.exists(arq) else None
    c = A.app.test_client()
    p = ry.criar_projeto(base, texto="[0:00] oi")
    novo = None
    try:
        if os.path.exists(arq):
            os.remove(arq)
        p["analise"] = {"roteiro": "Texto.", "cenas": []}
        ry.salvar_projeto(base, p)
        c.post(f"/roteiros-yt/{p['id']}/prompt-analise", json={"modelo_id": "reescrever_cenas", "idioma": "es", "sem_experiencias": False})
        assert c.post(f"/roteiros-yt/{p['id']}/prompt-acoes", json={"acoes": ["tags", "ads"], "idioma": "en", "cta_no_texto": True}).status_code == 200
        assert c.post(f"/roteiros-yt/{p['id']}/prompt-acoes", json={"acoes": ["traduzir", "descricao"], "idioma": "es", "extra": "tom sério"}).status_code == 200
        d = ry.opcoes_usadas(base)
        assert d["ultima"]["acoes"] == ["traduzir", "descricao"] and len(d["historico"]) == 2
        assert d["historico"][1]["acoes"] == ["tags", "ads"] and "(es)" in d["historico"][0]["rotulo"]
        # repetir a mesma combinação não duplica, só sobe pro topo
        c.post(f"/roteiros-yt/{p['id']}/prompt-acoes", json={"acoes": ["tags", "ads"], "idioma": "en"})
        assert [h["acoes"] for h in ry.opcoes_usadas(base)["historico"]] == [["tags", "ads"], ["traduzir", "descricao"]]
        novo = ry.criar_projeto(base, texto="[0:00] outro")
        h = c.get(f"/roteiros-yt/{novo['id']}").get_data(as_text=True)
        assert 'value="tags" checked' in h and 'value="ads" checked' in h and 'value="traduzir" checked' not in h
        assert 'value="es" selected>roteiro em' in h and 'id="semExperiencias" style="width:auto;" >' in h
        assert "histAcoes" in h and "Usar de novo" in h
        c.delete("/roteiros-yt/opcoes-usadas")
        assert ry.opcoes_usadas(base)["historico"] == []
    finally:
        for q in (p, novo):
            if q:
                c.post(f"/roteiros-yt/{q['id']}/excluir")
        if antes is None:
            if os.path.exists(arq):
                os.remove(arq)
        else:
            open(arq, "w", encoding="utf-8").write(antes)
