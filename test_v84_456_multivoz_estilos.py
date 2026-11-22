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
