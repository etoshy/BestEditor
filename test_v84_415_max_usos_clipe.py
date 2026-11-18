"""v84_415 — o mesmo clipe (ou a mesma cena) no máximo 3 vezes por vídeo."""
import video_assembler as va


def _c(i, th="t"):
    return {"id": str(i), "thumbnail": f"http://x/{th}.jpg", "url": f"animepexels://clip/{i}"}


def test_repete_no_maximo_3_vezes(monkeypatch):
    monkeypatch.setattr(va, "_dhash_url", lambda u: None)
    t = va.UsedClipsTracker(3)
    escolhidos = [va._escolher_candidato_previa([_c(1), _c(2)], t, "pexels") for _ in range(8)]
    ids = [e["id"] if e else None for e in escolhidos]
    assert ids[:2] == ["1", "2"]  # primeiro os nunca usados
    assert ids.count("1") == 3 and ids.count("2") == 3 and ids[-2:] == [None, None]


def test_mesma_cena_com_outro_id_conta_junto(monkeypatch):
    # 5 clipes diferentes, todos com a MESMA miniatura (o mesmo plano cortado em vários clipes)
    monkeypatch.setattr(va, "_dhash_url", lambda u: 0b1011 << 40)
    t = va.UsedClipsTracker(3)
    cands = [_c(i) for i in range(5)]
    got = [va._escolher_candidato_previa(cands, t, "animepexels_online") for _ in range(5)]
    assert sum(1 for g in got if g) == 3 and got[3] is None


def test_cena_diferente_passa(monkeypatch):
    hs = {"http://x/a.jpg": 0, "http://x/b.jpg": (1 << 64) - 1}
    monkeypatch.setattr(va, "_dhash_url", lambda u: hs.get(u))
    t = va.UsedClipsTracker(3)
    a = va._escolher_candidato_previa([_c(1, "a"), _c(2, "b")], t, "animepexels")
    b = va._escolher_candidato_previa([_c(1, "a"), _c(2, "b")], t, "animepexels")
    assert a["id"] == "1" and b["id"] == "2"  # o 2º trecho pega a outra cena, não o mesmo plano


def test_previas_existentes_contam(monkeypatch):
    import app as A
    monkeypatch.setattr(va, "_dhash_url", lambda u: None)
    t = va.UsedClipsTracker(3)
    pv = [{"ok": True, "result_url": "animepexels://clip/9", "provider": "animepexels"}] * 3
    assert A._registrar_previas_no_tracker(t, pv, []) == 3
    assert t.usos("9", "animepexels") == 3
    assert va._escolher_candidato_previa([_c(9)], t, "animepexels") is None
