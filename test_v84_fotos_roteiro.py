"""📸 v84_127: marcas que a IA não pode perder + fotos pro roteiro (perguntas e posicionar)."""
import io
import json

import pytest

import adaptar_tts
import dossies as ds
import fotos_roteiro as fr
import marcas_seguras as ms
import revisao_roteiro as rv

ORIG = ("Em 1971 tudo mudou. [I3] John List matou a família em Westfield.\n\n[[INSCREVA]]\n\n"
        "[I5] A casa ficou vazia por semanas. Os vizinhos não notaram nada. [I3] Ele fugiu sem deixar rastros.\n\n"
        "[[VENDA: compre o livro]]")


def test_restaura_marcas_que_a_ia_tirou():
    novo = ("Em 1971, tudo mudou. John List matou a família, em Westfield. A casa ficou vazia por semanas. "
            "Os vizinhos não perceberam nada. [I3] Ele fugiu sem deixar nenhum rastro.")
    t, volta = ms.restaurar(ORIG, novo)
    assert t.count("[I3]") == 2 and "[I5] A casa" in t
    assert "\n[[INSCREVA]]\n" in t and t.strip().endswith("[[VENDA: compre o livro]]")
    assert t.index("[[INSCREVA]]") < t.index("[I5]")
    assert sorted(volta) == sorted(["[I3]", "[[INSCREVA]]", "[I5]", "[[VENDA: compre o livro]]"])
    assert ms.restaurar(ORIG, ORIG) == (ORIG, [])


def test_adaptar_tts_e_revisao_nao_perdem_marcas():
    r = adaptar_tts.ler_resposta(ms.MARCA.sub("", ORIG), ORIG)
    assert r["texto"].count("[I3]") == 2 and "[[VENDA" in r["texto"] and any("🔒" in a for a in r["avisos"])
    d = rv.aplicar(ORIG, json.dumps({"trocas": [{"de": "[I5] A casa ficou vazia", "para": "A casa ficou abandonada"}]}))
    assert "[I5] A casa ficou abandonada" in d["texto"]


def test_frases_e_posicionar():
    f = fr.frases(ORIG)
    assert [x["texto"] for x in f][:2] == ["Em 1971 tudo mudou.", "John List matou a família em Westfield."]
    assert f[1]["midias"] == ["I3"] and not any("compre" in x["texto"] for x in f)
    novo, info = fr.aplicar_posicoes(ORIG, json.dumps({"usos": [{"midia": "I9", "frases": [1, 2, 4]}, {"midia": "X1", "frases": [4]}]}),
                                     {"I3", "I5", "I9"})
    assert novo.startswith("[I9] Em 1971") and "[I9] Os vizinhos" in novo and info["postas"] == 2 and info["ignoradas"] == 2


@pytest.fixture()
def cliente(tmp_path):
    from flask import Flask
    import dossies_rotas
    app = Flask(__name__, template_folder="templates")
    app.config["TESTING"] = True
    dossies_rotas.registrar(app, str(tmp_path))
    fr.registrar(app, str(tmp_path))
    p = ds.criar(str(tmp_path), "John List")
    for k in (3, 5):
        while len(p.get("midias") or []) < k:
            ds.adicionar_midia(p, tipo="foto", descricao=f"foto {len(p.get('midias') or []) + 1}")
    p["resultado"] = ds.ler_resultado(json.dumps({"roteiro": ORIG, "titulos": ["t"]}), p)
    ds.salvar(str(tmp_path), p)
    return app.test_client(), p["id"], str(tmp_path)


def test_fluxo_perguntas_envio_e_posicionar(cliente):
    c, pid, base = cliente
    r = c.post(f"/modelos-video/{pid}/fotos-roteiro/perguntas/prompt", json={})
    assert r.status_code == 200 and "Helen" in r.get_json()["prompt"] or "Roteiro" in r.get_json()["prompt"]
    resp = {"perguntas": [{"tipo": "pessoa", "alvo": "Helen List", "pergunta": "Você tem foto de Helen List?", "vezes": 3},
                          {"tipo": "lugar", "alvo": "Casa de Westfield", "pergunta": "Tem foto da casa?", "ja_tem": ["I5"]}]}
    d = c.post(f"/modelos-video/{pid}/fotos-roteiro/perguntas/ler", json={"texto": json.dumps(resp)}).get_json()
    assert [q["id"] for q in d["perguntas"]] == ["P1", "P2"] and d["perguntas"][1]["ja_tem"] == ["I5"]
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (20, 20)).save(buf, "PNG")
    buf.seek(0)
    r = c.post(f"/modelos-video/{pid}/midia", data={"arquivo": (buf, "helen.png"), "descricao": "Helen List", "pergunta": "P1"},
               content_type="multipart/form-data")
    novo_id = r.get_json()["midia"]["id"]
    est = c.get(f"/modelos-video/{pid}/fotos-roteiro").get_json()
    assert est["enviadas"] == {"P1": [novo_id]}
    pr = c.post(f"/modelos-video/{pid}/fotos-roteiro/posicionar/prompt", json={"modo": "novas"}).get_json()["prompt"]
    assert f"{novo_id}: [pra: Helen List]" in pr and "S1:" in pr
    d = c.post(f"/modelos-video/{pid}/fotos-roteiro/posicionar/ler",
               json={"texto": json.dumps({"usos": [{"midia": novo_id, "frases": [1, 4]}]})}).get_json()
    assert d["postas"] == 2 and d["uso"][novo_id] == 2 and d["pode_desfazer"]
    p = ds.carregar(base, pid)
    assert p["resultado"]["roteiro"].startswith(f"[{novo_id}] Em 1971")
    assert f"[{novo_id}]" not in p["resultado"]["roteiro_final"]  # a voz não lê a marca
    assert sum(1 for m in p["resultado"]["momentos"] if m["midia"] == novo_id) == 2
    assert c.post(f"/modelos-video/{pid}/fotos-roteiro/desfazer", json={}).status_code == 200
    assert ds.carregar(base, pid)["resultado"]["roteiro"] == ORIG


def test_cenas_do_pod_usam_as_fotos_do_modelo():
    import cenas_lote
    cenas = [{"start": 0, "end": 5, "fala": "Em 1971 tudo mudou."}, {"start": 5, "end": 10, "fala": "John List matou a família em"},
             {"start": 10, "end": 15, "fala": "Westfield. A casa ficou vazia por semanas."},
             {"start": 15, "end": 20, "fala": "Os vizinhos não notaram nada. Ele fugiu sem deixar rastros."}]
    momentos = [{"midia": "I3", "trecho": "John List matou a família em Westfield."},
                {"midia": "I5", "trecho": "A casa ficou vazia por semanas."},
                {"midia": "I3", "trecho": "Ele fugiu sem deixar rastros."}]
    assert cenas_lote.cenas_dos_momentos(cenas, momentos) == {1: "I3", 2: "I5", 3: "I3"}
    j = cenas_lote.montar_json(cenas, {}, {0}, "", {1: {"id": "I3", "tipo": "foto"}})
    assert j["segments"][1]["provider"] == "material" and j["segments"][1]["query"] == "I3"
    assert j["segments"][0]["provider"] == "runpod"
