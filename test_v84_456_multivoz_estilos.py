import multivoz as mv

VOZES = {"wagner_moura": {"slug": "wagner_moura", "nome": "Wagner Moura", "motor": "chatterbox", "cor": "#111"},
         "mabel_cezar_2": {"slug": "mabel_cezar_2", "nome": "Mabel Cezar 2", "motor": "fish_s2", "cor": "#222"},
         "marcio": {"slug": "marcio", "nome": "Marcio", "motor": "chatterbox", "cor": "#333"}}


def test_tags_de_estilo_nao_sao_voz():
    d = mv.dividir("[wagner_moura] [seria] Existem servidores. [dramatica] Você acabou! [mabel_cezar_2] [ironica] Mentira. "
                   "[pausa longa] Eu só estava jogando.", VOZES)
    assert d["desconhecidas"] == []
    w = [f for f in d["falas"] if f["slug"] == "wagner_moura"]
    assert w[0]["ajustes"]["exag"] == 0.5 and w[1]["ajustes"]["exag"] == 0.65  # séria → dramática
    m = [f for f in d["falas"] if f["slug"] == "mabel_cezar_2"][0]
    assert "[ironica]" in m["texto"]  # o Fish S2 lê a instrução entre colchetes
    assert "[seria]" not in w[0]["texto"]  # o Chatterbox não: vira emoção/velocidade


def test_sugestao_de_voz_parecida():
    d = mv.dividir("[Marcio_Seixas] Olá. [ana] oi.", VOZES)
    assert set(d["desconhecidas"]) == {"Marcio_Seixas", "ana"}
    assert mv.sugerir(d["desconhecidas"], VOZES) == {"Marcio_Seixas": "marcio"}


def test_velocidade_e_perfil(monkeypatch):
    d = mv.dividir("[marcio] [dramatica] [velocidade 0.9] Eu só tenho três minutos.", VOZES)
    assert d["desconhecidas"] == [] and d["falas"][0]["ajustes"] == {"exag": 0.65, "cfg": 0.35, "vel": 0.9}
    assert "velocidade" not in d["falas"][0]["texto"]
    assert mv.perfis_das_tags(["Marcio_Seixas", "ana"], ["Marcio_Seixas", "Wagner_Moura"]) == {"Marcio_Seixas": "Marcio_Seixas"}
    assert mv.motor_dos_perfis({"a": {"motor": "fish_s2", "config": {"vozPerfil": "x"}},
                                "b": {"motor": "fish_s2", "config": {"vozPerfil": "y"}},
                                "c": {"motor": "chatterbox", "config": {}}}) == "fish_s2"


def test_roteiro_do_usuario_divide_sem_erro():
    rot = ("[Wagner_Moura] [seria] [pausa longa]\nExistem servidores.\n\n[ironica] Pelo menos.\n\n[Marcio_Seixas] [agressiva] "
           "Vão embora!\n\n[Mabel_Cezar_2] [suspense]\nEu já sei de tudo.\n\n[Marcio_Seixas] [agressiva] [velocidade 1.1]\nWash é o Dart!")
    vozes = dict(VOZES, marcio_seixas={"slug": "marcio_seixas", "nome": "Marcio Seixas", "motor": "chatterbox", "cor": "#444"})
    d = mv.dividir(rot, vozes)
    assert d["desconhecidas"] == []
    assert [f["slug"] for f in d["falas"]] == ["wagner_moura", "wagner_moura", "marcio_seixas", "mabel_cezar_2", "marcio_seixas"]
    assert d["falas"][-1]["ajustes"]["vel"] == 1.1


def test_tags_de_som():
    d = mv.dividir("[marcio] [pigarro] Bem. [tosse] Hum. [respira] Vamos. [mabel_cezar_2] [tosse] Oi [risada]", VOZES)
    assert d["desconhecidas"] == []
    marcio, mabel = d["falas"][0]["texto"], d["falas"][1]["texto"]
    assert "pigarro" not in marcio and "Cof, cof." in marcio and "[" not in marcio  # chatterbox: a leitura do som
    assert "[cough]" in mabel and "[laughing]" in mabel  # Fish S2: a tag em inglês


def test_crash_numa_fala_nao_perde_as_outras(tmp_path, monkeypatch):
    import wave
    monkeypatch.setattr(mv, "por_slug", lambda: VOZES)
    monkeypatch.setattr(mv, "kwargs_da_voz", lambda v: (v["motor"], {"voz": v["slug"]}))
    monkeypatch.setattr(mv, "_wav_padrao", lambda a, b: __import__("shutil").copy(a, b))
    monkeypatch.setattr(mv, "concatenar", lambda arqs, saida, pausas, pasta: open(saida, "wb").write(b"x" * 2000))
    import time as _t
    monkeypatch.setattr(_t, "sleep", lambda s: None)
    feitas, falhou = [], {"n": 0}

    def gerar_fn(motor, texto, saida, **kw):
        if "Terceira" in texto and falhou["n"] < 1:
            falhou["n"] += 1
            raise RuntimeError("O motor de voz travou o processo (código de saída 3221225477)")
        feitas.append(texto)
        open(saida, "wb").write(b"w" * 2000)
    texto = "[marcio] Primeira fala. [mabel_cezar_2] Segunda fala. [marcio] Terceira fala."
    saida = str(tmp_path / "voz.wav")
    r = mv.gerar(texto, saida, "chatterbox", {}, gerar_fn, lambda t, m: t)
    assert r["falas"] == 3 and len(feitas) == 3 and falhou["n"] == 1  # só a 3ª foi refeita
    feitas.clear()
    r2 = mv.gerar(texto, saida, "chatterbox", {}, gerar_fn, lambda t, m: t)  # de novo: tudo vem guardado
    assert r2["reaproveitadas"] == 3 and feitas == []


def test_lote_um_processo_e_crash_no_meio(tmp_path, monkeypatch):
    monkeypatch.setattr(mv, "por_slug", lambda: VOZES)
    monkeypatch.setattr(mv, "kwargs_da_voz", lambda v: (v["motor"], {"voz": v["slug"]}))
    monkeypatch.setattr(mv, "_wav_padrao", lambda a, b: __import__("shutil").copy(a, b))
    monkeypatch.setattr(mv, "concatenar", lambda arqs, saida, pausas, pasta: open(saida, "wb").write(b"x" * 2000))
    import time as _t
    monkeypatch.setattr(_t, "sleep", lambda s: None)
    chamadas = []

    def lote(itens, on_progresso=None):
        chamadas.append([t for _m, t, _s, _k in itens])
        erros = {}
        for i, (_m, t, saida, _k) in enumerate(itens):
            if len(chamadas) == 1 and i == 1:  # 1ª rodada: o motor cai na 2ª fala
                for j in range(i, len(itens)):
                    erros[j] = "O motor de voz fechou sozinho (código 3221225477 — crash nativo do motor?)."
                break
            open(saida, "wb").write(b"w" * 2000)
            on_progresso(i, None)
        return erros
    texto = "[marcio] Um. [mabel_cezar_2] Dois. [marcio] Três. [mabel_cezar_2] Quatro."
    r = mv.gerar(texto, str(tmp_path / "v.wav"), "chatterbox", {}, None, lambda t, m: t, lote_fn=lote)
    assert r["falas"] == 4 and len(chamadas) == 2
    assert chamadas[0][:2] == ["Um.", "Três."]  # agrupadas por voz (o perfil troca o mínimo)
    assert len(chamadas[1]) == 3  # a 2ª rodada só com as que faltaram


def test_pausas_viram_silencio():
    d = mv.dividir("[marcio] Aviso. [pausa curta] Isto é sátira. [pausa longa] [mabel_cezar_2] Oi. [pausa] Tchau.", VOZES)
    assert [(f["slug"], f.get("pausa_antes"), f["texto"]) for f in d["falas"]] == [
        ("marcio", None, "Aviso."), ("marcio", 0.25, "Isto é sátira."), ("mabel_cezar_2", 1.0, "Oi."), ("mabel_cezar_2", 0.45, "Tchau.")]
    assert all("pausa" not in f["texto"] for f in d["falas"])


def test_pausas_entram_no_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(mv, "por_slug", lambda: VOZES)
    monkeypatch.setattr(mv, "kwargs_da_voz", lambda v: (v["motor"], {"voz": v["slug"]}))
    monkeypatch.setattr(mv, "_wav_padrao", lambda a, b: __import__("shutil").copy(a, b))
    visto = {}
    monkeypatch.setattr(mv, "concatenar", lambda arqs, saida, pausas, pasta: (visto.update(p=pausas), open(saida, "wb").write(b"x" * 2000)))
    mv.gerar("[marcio] Um. [pausa longa] Dois.", str(tmp_path / "v.wav"), "chatterbox", {},
             lambda m, t, s, **k: open(s, "wb").write(b"w" * 2000), lambda t, m: t)
    assert visto["p"][1] == 0.12 + 1.0  # a pausa da mesma voz + o [pausa longa]


def test_pausa_com_numero_e_tag_estranha():
    d = mv.dividir("[marcio] Um. [pausa 3] Dois. [pausa 1,5s] Três. [olhando pro lado] Quatro.", VOZES)
    assert [f.get("pausa_antes") for f in d["falas"]] == [None, 3.0, 1.5]
    assert all("pausa" not in f["texto"] and "[" not in f["texto"] and "olhando" not in f["texto"] for f in d["falas"])
    assert mv._pausa_em_segundos("silêncio 20") == 10.0 and mv._pausa_em_segundos("pausa longa") is None


def test_limpar_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("MULTIVOZ_CACHE_DIR", str(tmp_path / "c"))
    os_ = __import__("os")
    os_.makedirs(tmp_path / "c")
    (tmp_path / "c" / "a.wav").write_bytes(b"x" * 10)
    assert mv.info_cache(str(tmp_path))["falas"] == 1
    assert mv.limpar_cache(str(tmp_path)) == 1 and mv.info_cache(str(tmp_path))["falas"] == 0
