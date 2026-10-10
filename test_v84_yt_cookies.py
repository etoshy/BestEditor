"""Cookies do YouTube contra o "Sign in to confirm you're not a bot" (yt_cookies.py)."""
import pytest

import yt_cookies

BOT = "\x1b[0;31mERROR:\x1b[0m [youtube] j6zFDqyrAzw: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies"


@pytest.fixture(autouse=True)
def prefs_isoladas(tmp_path, monkeypatch):
    monkeypatch.setattr(yt_cookies, "ARQ_PREFS", str(tmp_path / "p.json"))
    monkeypatch.setattr(yt_cookies, "ARQ_COOKIES", str(tmp_path / "cookies_youtube.txt"))


def test_reconhece_o_bloqueio_e_limpa_as_cores():
    assert yt_cookies.eh_bloqueio(BOT)
    assert "\x1b" not in yt_cookies.limpar(BOT) and "[0;31m" not in yt_cookies.limpar(BOT)
    assert not yt_cookies.eh_bloqueio("HTTP Error 403: Forbidden")


def test_tenta_os_navegadores_e_guarda_o_que_funcionou():
    vistos = []

    def acao(ck):
        vistos.append(ck)
        if ck.get("cookiesfrombrowser") == ("edge",):
            return "ok"
        if ck.get("cookiesfrombrowser"):
            raise RuntimeError("could not find firefox cookies database")
        raise RuntimeError(BOT)
    logs = []
    assert yt_cookies.tentar(acao, logs.append) == "ok"
    assert vistos[0] == {} and vistos[-1] == {"cookiesfrombrowser": ("edge",)}
    assert yt_cookies.prefs()["navegador_que_funcionou"] == "edge"
    assert yt_cookies.opcoes() == {"cookiesfrombrowser": ("edge",)}  # da próxima vez já vai com ele
    assert any("edge" in m for m in logs)


def test_nada_funciona_explica_como_resolver():
    def acao(ck):
        raise RuntimeError(BOT)
    with pytest.raises(yt_cookies.YoutubeBloqueado) as e:
        yt_cookies.tentar(acao)
    assert "Firefox" in str(e.value) and "cookies.txt" in str(e.value)


def test_outro_erro_nao_tenta_navegadores():
    chamadas = []

    def acao(ck):
        chamadas.append(ck)
        raise ValueError("vídeo privado")
    with pytest.raises(ValueError):
        yt_cookies.tentar(acao)
    assert len(chamadas) == 1


def test_arquivo_tem_prioridade():
    yt_cookies.salvar_prefs(navegador="firefox")
    yt_cookies.salvar_arquivo(b"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tx\n")
    assert "cookiefile" in yt_cookies.opcoes()
    with pytest.raises(ValueError):
        yt_cookies.salvar_arquivo(b"lixo")


def test_roteiro_usa_cookies_quando_o_youtube_bloqueia(tmp_path):
    import roteiros_yt

    class Y:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            if not self.opts.get("cookiesfrombrowser"):
                raise RuntimeError(BOT)
            return {"title": "T", "subtitles": {}, "automatic_captions": {}}

    class M:
        YoutubeDL = Y
    with pytest.raises(roteiros_yt.RoteiroError) as e:  # passou do bloqueio (firefox); o vídeo é que não tem legenda
        roteiros_yt.extrair_transcricao("https://youtu.be/x", str(tmp_path), ytdlp_module=M, usar_whisper=False)
    assert "não tem legenda" in str(e.value)
    assert yt_cookies.prefs()["navegador_que_funcionou"] == "firefox"


# ------------------------------------------------------------------ outro jeito quando o yt-dlp é bloqueado
class _YBloqueado:
    """yt-dlp falso: o YouTube bloqueia tudo, menos (opcional) um cliente."""
    libera = None

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def close(self):
        pass

    def extract_info(self, url, download=False):
        cli = ((self.opts.get("extractor_args") or {}).get("youtube") or {}).get("player_client")
        if self.libera and cli == self.libera:
            return {"title": "T", "subtitles": {}, "automatic_captions": {}}
        raise RuntimeError(BOT)


def _alt(**kw):
    import yt_alternativas as real

    class Alt:
        CLIENTES = real.CLIENTES

        @staticmethod
        def legenda_transcript_api(url, pref):
            if "api" in kw:
                return kw["api"]
            raise RuntimeError("IpBlocked")

        @staticmethod
        def legenda_navegador(url, pref, log, headless=True):
            if "nav" in kw:
                return kw["nav"]
            raise RuntimeError("sem navegador")

        @staticmethod
        def audio_pytubefix(url, pasta, log):
            if "audio" in kw:
                return kw["audio"], {"titulo": "Vídeo", "canal": "C", "duracao": 10}
            raise RuntimeError("pytubefix bloqueado")
    return Alt


def _modulo(libera=None):
    class M:
        YoutubeDL = type("Y", (_YBloqueado,), {"libera": libera})
    return M


LINHAS = [{"inicio": 0.0, "fim": 2.0, "texto": "olá mundo"}, {"inicio": 2.0, "fim": 4.0, "texto": "tudo bem"}]


def test_outro_cliente_do_youtube_resolve(tmp_path):
    import roteiros_yt
    with pytest.raises(roteiros_yt.RoteiroError) as e:  # liberou no cliente "tv": chegou a ler o vídeo (sem legenda)
        roteiros_yt.extrair_transcricao("https://youtu.be/abcdefghijk", str(tmp_path), ytdlp_module=_modulo(["tv"]),
                                        usar_whisper=False, alternativas=_alt())
    assert "não tem legenda" in str(e.value)


def test_bloqueado_usa_youtube_transcript_api(tmp_path):
    import roteiros_yt
    r = roteiros_yt.extrair_transcricao("https://youtu.be/abcdefghijk", str(tmp_path), ytdlp_module=_modulo(),
                                        alternativas=_alt(api={"linhas": LINHAS, "lang": "pt", "auto": True}))
    assert r["fonte"] == "legenda automática" and "olá mundo" in r["blocos"][0]["texto"]


def test_bloqueado_usa_o_navegador(tmp_path):
    import roteiros_yt
    logs = []
    r = roteiros_yt.extrair_transcricao("https://youtu.be/abcdefghijk", str(tmp_path), ytdlp_module=_modulo(), on_log=logs.append,
                                        alternativas=_alt(nav={"linhas": LINHAS, "lang": "en", "auto": False, "titulo": "Meu vídeo", "canal": "X", "duracao": 4}))
    assert r["fonte"] == "legenda do vídeo" and r["titulo"] == "Meu vídeo" and any("navegador" in m for m in logs)


def test_bloqueado_sem_legenda_baixa_audio_com_pytubefix(tmp_path):
    import roteiros_yt
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"x")
    r = roteiros_yt.extrair_transcricao("https://youtu.be/abcdefghijk", str(tmp_path), ytdlp_module=_modulo(),
                                        alternativas=_alt(nav={"linhas": [], "lang": None, "auto": None, "titulo": "V"}, audio=str(audio)),
                                        whisper_fn=lambda c, info: [{"start": 0, "end": 1, "text": "fala"}])
    assert r["fonte"] == "whisper" and r["blocos"][0]["texto"] == "fala"


def test_tudo_bloqueado_explica(tmp_path):
    import roteiros_yt
    with pytest.raises(roteiros_yt.RoteiroError) as e:
        roteiros_yt.extrair_transcricao("https://youtu.be/abcdefghijk", str(tmp_path), ytdlp_module=_modulo(), alternativas=_alt())
    m = str(e.value)
    assert "Mostrar transcrição" in m and "youtube-transcript-api" in m and "pytubefix" in m


def test_le_legenda_em_xml_e_vtt():
    import yt_alternativas as a
    assert a.linhas_de_texto('<transcript><text start="1.5" dur="2">Oi &amp; tchau</text></transcript>')[0]["texto"] == "Oi & tchau"
    assert a.linhas_de_texto('<timedtext><body><p t="1000" d="500">ola</p></body></timedtext>')[0]["inicio"] == 1.0
    assert a.video_id("https://www.youtube.com/watch?v=rsiJID4W7bA&t=3") == "rsiJID4W7bA"
    assert a.video_id("https://youtu.be/rsiJID4W7bA") == "rsiJID4W7bA"


def test_erro_estranho_de_outro_cliente_nao_para(tmp_path):
    """"The page needs to be reloaded" num cliente alternativo: segue pros outros caminhos."""
    import roteiros_yt

    class Y(_YBloqueado):
        def extract_info(self, url, download=False):
            if (self.opts.get("extractor_args") or {}).get("youtube"):
                raise RuntimeError("ERROR: [youtube] rsiJID4W7bA: The page needs to be reloaded.")
            raise RuntimeError(BOT)

    class M:
        YoutubeDL = Y
    r = roteiros_yt.extrair_transcricao("https://youtu.be/abcdefghijk", str(tmp_path), ytdlp_module=M,
                                        alternativas=_alt(api={"linhas": LINHAS, "lang": "pt", "auto": False}))
    assert r["fonte"] == "legenda do vídeo"


def test_qualquer_erro_do_ytdlp_tenta_os_outros_caminhos(tmp_path):
    import roteiros_yt

    class Y(_YBloqueado):
        def extract_info(self, url, download=False):
            raise RuntimeError("ERROR: [youtube] x: The page needs to be reloaded.")

    class M:
        YoutubeDL = Y
    r = roteiros_yt.extrair_transcricao("https://youtu.be/abcdefghijk", str(tmp_path), ytdlp_module=M,
                                        alternativas=_alt(nav={"linhas": LINHAS, "lang": "pt", "auto": True, "titulo": "V"}))
    assert r["blocos"]


def test_escolher_em_quais_chamadas_o_clipe_entra(tmp_path):
    import os
    import app as A
    A.app.config["TESTING"] = True
    clipe = tmp_path / "venda.mp4"
    clipe.write_bytes(b"x")
    os.makedirs(A._job_dir("ch-esc"), exist_ok=True)
    cs = [{"id": f"v{k}", "chamada": True, "tipo": "venda", "insertion_point": 10.0 * k, "resolved_path": str(clipe) if k == 0 else None,
           "description": "Venda", "audio_mode": "pause"} for k in range(3)]
    A._JOBS["ch-esc"] = {"job_id": "ch-esc", "status": "pronto_para_editar", "pending_segments": [], "cutaway_suggestions": cs}
    c = A.app.test_client()
    d = c.post("/job/ch-esc/chamadas/escolher", json={"tipo": "venda", "ligadas": ["v1", "v2"]}).get_json()
    assert d["com_clipe"] == 2
    assert cs[0]["resolved_path"] is None and cs[0]["desligada"] and cs[2]["resolved_path"] == str(clipe)
