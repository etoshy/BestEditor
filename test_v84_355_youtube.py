"""v84_355: 📤 enviar pro YouTube — agenda por canal, envio retomável, capa descartada no erro, pausa no limite."""
import datetime as dt
import json
import os
import time

import curtos as CT
import youtube_envio as YE
from test_v84_320_lote_por_etapa import _app


class R:
    def __init__(self, status, j=None, headers=None):
        self.status_code, self._j, self.headers, self.text = status, j or {}, headers or {}, json.dumps(j or {})

    def json(self):
        return self._j


def _erro(status, reason):
    return R(status, {"error": {"message": reason, "errors": [{"reason": reason}]}})


def _base(tmp_path):
    b = str(tmp_path)
    YE.salvar_cliente(b, json.dumps({"web": {"client_id": "x.apps.googleusercontent.com", "client_secret": "s"}}))
    with YE._TRAVA:
        YE._gravar(b, "contas.json", {"UC1": {"titulo": "Meu canal", "refresh_token": "r", "access_token": "a", "expira": time.time() + 999}})
    YE.salvar_agenda(b, "c1", {"conta": "UC1", "por_dia": 3, "horarios": ["21:00", "12:00", "18:00", "lixo"]})
    with YE._TRAVA:  # a lista do canal "já buscada" (vazia): os testes não vão pra rede
        YE._gravar(b, os.path.join("recentes", "UC1.json"), {"buscado": time.time(), "videos": []})
    return b


def _ts(d, h, m=0):
    return time.mktime(dt.datetime(d.year, d.month, d.day, h, m).timetuple())


def test_agenda_proximos_horarios_livres(tmp_path):
    b = _base(tmp_path)
    a = YE.agenda(b, "c1")
    assert a["horarios"] == ["12:00", "18:00", "21:00"] and a["privacidade"] == "public"
    hoje = dt.date.today()
    agora = _ts(hoje, 13)
    its = [{"pid": f"p{k}", "canal_id": "c1", "nome": f"v{k}"} for k in range(4)]
    novos, pulados = YE.adicionar(b, its, agora=agora)
    amanha = hoje + dt.timedelta(days=1)
    assert [x["slot"] for x in novos] == [_ts(hoje, 18), _ts(hoje, 21), _ts(amanha, 12), _ts(amanha, 18)] and not pulados
    # o mesmo vídeo não entra 2 vezes; canal sem conta é pulado com motivo
    n2, p2 = YE.adicionar(b, [{"pid": "p0", "canal_id": "c1"}, {"pid": "z", "canal_id": "sem", "canal": "Outro"}], agora=agora)
    assert not n2 and len(p2) == 2 and "já está na fila" in p2[0] and "Outro" in p2[1]
    # 1 por dia com um horário só
    YE.salvar_agenda(b, "c1", {"conta": "UC1", "por_dia": 1, "horarios": ["09:30"]})
    assert YE.reagendar(b, "c1", agora=agora) == 4
    qs = sorted(x["slot"] for x in YE.fila(b))
    assert qs == [_ts(hoje + dt.timedelta(days=d), 9, 30) for d in (1, 2, 3, 4)]
    # 3 por dia mas só 1 horário → espalha a cada 3 h
    assert YE.horarios_do_dia(YE.limpar_agenda({"por_dia": 3, "horarios": ["12:00"]})) == ["12:00", "15:00", "18:00"]


def _video(tmp_path, tamanho=20 * 1024 * 1024 + 5):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"\0" * tamanho)
    t = tmp_path / "t.jpg"
    from PIL import Image
    Image.new("RGB", (1280, 720), (200, 30, 30)).save(t)
    return str(v), str(t)


def test_envio_retomavel_capa_e_descarte(tmp_path, monkeypatch):
    b = _base(tmp_path)
    v, t = _video(tmp_path)
    chamadas = []

    def http(metodo, url, **kw):
        chamadas.append((metodo, url, kw.get("headers", {}).get("Content-Range")))
        if url == YE.URL_UPLOAD:
            corpo = json.loads(kw["data"])
            assert corpo["snippet"]["title"].endswith("#shorts") and "#gatos" in corpo["snippet"]["description"]
            assert corpo["snippet"]["tags"] == ["gatos", "fofos"] and corpo["status"]["selfDeclaredMadeForKids"] is False
            return R(200, headers={"Location": "https://up/sessao"})
        if url == "https://up/sessao":
            ini, fim_tot = kw["headers"]["Content-Range"][6:].split("-")
            fim, tot = map(int, fim_tot.split("/"))
            return R(200, {"id": "VID123"}) if fim + 1 == tot else R(308, headers={"Range": f"bytes=0-{fim}"})
        if url == YE.URL_THUMB:
            return _erro(403, "forbidden")  # canal sem verificação: capa recusada
        raise AssertionError(url)

    monkeypatch.setattr(YE, "HTTP", http)
    YE.salvar_agenda(b, "c1", {"conta": "UC1", "horarios": ["18:00"], "shorts_tag": True})
    YE.adicionar(b, [{"pid": "p1", "canal_id": "c1", "nome": "Gato"}], agora_ja=True)
    meta = lambda pid: {"titulo": "Gato <pula>", "descricao": "desc", "hashtags": ["#gatos", "#fofos", "#gatos"], "video": v, "thumb": t}
    x = YE.rodada(b, meta)
    assert x["estado"] == "enviado" and x["yt_id"] == "VID123" and x["capa"] == "descartada" and "verifique o canal" in x["aviso"]
    puts = [c for c in chamadas if c[0] == "PUT"]
    assert len(puts) == 3 and puts[0][2] == f"bytes 0-{YE.PEDACO - 1}/{os.path.getsize(v)}"
    assert YE.rodada(b, meta) is None  # nada mais na fila


def test_limite_do_canal_pausa_e_volta_pra_fila(tmp_path, monkeypatch):
    b = _base(tmp_path)
    v, t = _video(tmp_path, 100)
    monkeypatch.setattr(YE, "HTTP", lambda m, u, **k: _erro(400, "uploadLimitExceeded"))
    YE.adicionar(b, [{"pid": "p1", "canal_id": "c1"}, {"pid": "p2", "canal_id": "c1"}], agora_ja=True)
    meta = lambda pid: {"titulo": "a", "video": v, "thumb": ""}
    x = YE.rodada(b, meta)
    assert x["estado"] == "na_fila" and "limite de envios" in x["log"][-1]
    assert YE.contas(b)["UC1"]["pausada_ate"] > time.time() + 23 * 3600
    assert YE.rodada(b, meta) is None  # a conta está pausada: ninguém sobe
    assert YE.proximo_da_fila(b, agora=time.time() + 25 * 3600)  # depois da pausa, continua


def test_erros_temporarios_e_token(tmp_path, monkeypatch):
    b = _base(tmp_path)
    v, _ = _video(tmp_path, 100)
    seq = []

    def http(m, u, **k):
        seq.append(u)
        if u == YE.URL_TOKEN:
            return R(200, {"access_token": "novo", "expires_in": 3600})
        if u == YE.URL_UPLOAD:
            return R(401) if seq.count(YE.URL_UPLOAD) == 1 else R(503, {"error": {"message": "backend", "errors": [{"reason": "backendError"}]}})
        raise AssertionError(u)

    monkeypatch.setattr(YE, "HTTP", http)
    YE.adicionar(b, [{"pid": "p1", "canal_id": "c1"}], agora_ja=True)
    x = YE.rodada(b, lambda pid: {"titulo": "a", "video": v})
    assert YE.URL_TOKEN in seq and YE.contas(b)["UC1"]["access_token"] == "novo"  # 401 → renova o token e tenta
    assert x["estado"] == "na_fila" and x["tentativas"] == 1 and x["quando"] > time.time() + 500  # 503 → de novo em 10 min
    # sem o arquivo do vídeo: erro claro
    x2 = YE.enviar_item(b, x, lambda pid: {"titulo": "a", "video": str(tmp_path / "nao.mp4")})
    assert x2["estado"] == "erro" and "não existe" in x2["erro"]


def test_oauth_e_rotas(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    b = str(tmp_path)
    assert "Credencial do Google" in cl.get("/youtube").get_data(as_text=True)
    assert cl.post("/youtube/cliente", json={"json": "{}"}).status_code == 400
    assert cl.post("/youtube/cliente", json={"json": json.dumps({"installed": {"client_id": "a.apps.googleusercontent.com", "client_secret": "z"}})}).get_json()["tipo"] == "installed"
    r = cl.get("/youtube/conectar")
    loc = r.headers["Location"]
    assert loc.startswith(YE.URL_AUTH) and "access_type=offline" in loc and "youtube.upload" in loc
    from urllib.parse import parse_qs, urlparse
    st = parse_qs(urlparse(loc).query)["state"][0]

    def http(m, u, **k):
        if u == YE.URL_TOKEN:
            assert k["data"]["redirect_uri"] == "http://localhost/youtube/oauth"
            return R(200, {"access_token": "a", "refresh_token": "r", "expires_in": 3600})
        return R(200, {"items": [{"id": "UCx", "snippet": {"title": "Canal X"}}]})

    monkeypatch.setattr(YE, "HTTP", http)
    assert "erro=" in cl.get("/youtube/oauth?code=c&state=falso").headers["Location"]
    assert "conectado" in cl.get(f"/youtube/oauth?code=c&state={st}").headers["Location"]
    assert YE.contas(b)["UCx"]["titulo"] == "Canal X"
    # agenda + adicionar da lista do Link (só os prontos)
    c = CT.criar_canal(b, "Gatos") if hasattr(CT, "criar_canal") else None
    cid = (c or {}).get("id") or "c9"
    cl.post(f"/youtube/agenda/{cid}", json={"conta": "UCx", "horarios": ["10:00"]})
    p = CT.criar(b, cid, "t", modelo="comentario")
    j = cl.post("/youtube/fila/adicionar", json={"ids": [p["id"], "naoexiste"]}).get_json()
    assert not j["novos"] and any("pronto" in x for x in j["pulados"]) and any("não achei" in x for x in j["pulados"])
    vid = tmp_path / "pronto.mp4"
    vid.write_bytes(b"0")
    q = CT.carregar(b, p["id"])
    q["exportado"] = {"arquivo": str(vid)}
    CT.salvar(b, q)
    j = cl.post("/youtube/fila/adicionar", json={"ids": [p["id"]]}).get_json()
    assert len(j["novos"]) == 1, j
    est = cl.get("/youtube/estado").get_json()
    iid = est["fila"][0]["id"]
    assert cl.post(f"/youtube/fila/{iid}/cancelar").get_json()["fila"][0]["estado"] == "cancelado"
    assert cl.post(f"/youtube/fila/{iid}/tirar").get_json()["fila"] == []
    html = cl.get("/curtos/link").get_data(as_text=True)
    assert 'data-selyt="agenda"' in html and "overflow-anchor: none" in html


def _http_canal(vids):
    """Um canal falso: uploads com os vídeos dados (inclusive agendados)."""
    def http(m, u, **k):
        if u == YE.URL_CANAIS:
            return R(200, {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}, "statistics": {"subscriberCount": "120", "videoCount": "9"}}]})
        if u.endswith("/playlistItems"):
            return R(200, {"items": [{"contentDetails": {"videoId": v["id"]}} for v in vids]})
        if u.endswith("/videos"):
            return R(200, {"items": [{"id": v["id"], "snippet": {"title": v["t"], "publishedAt": v["pub"]},
                                      "status": dict({"privacyStatus": v.get("priv", "public")}, **({"publishAt": v["at"]} if v.get("at") else {})),
                                      "statistics": {"viewCount": str(v.get("views", 0))}, "contentDetails": {"duration": "PT45S"}} for v in vids]})
        raise AssertionError(u)
    return http


def _iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_v84_356_ultimos_videos_e_agenda_respeita_o_canal(tmp_path, monkeypatch):
    b = _base(tmp_path)
    YE.salvar_agenda(b, "c1", {"conta": "UC1", "por_dia": 1, "horarios": ["18:00"]})
    hoje = dt.date.today()
    amanha, depois = hoje + dt.timedelta(days=1), hoje + dt.timedelta(days=2)
    agora = _ts(hoje, 10)
    vids = [{"id": "A", "t": "Gato pula o muro #shorts", "pub": _iso(_ts(hoje, 8)), "views": 900},  # já saiu 1 hoje (à mão)
            {"id": "B", "t": "Cachorro surfa", "pub": _iso(agora - 86400 * 2), "views": 100},
            {"id": "C", "t": "Agendado no Studio", "pub": _iso(agora - 3600), "priv": "private", "at": _iso(_ts(amanha, 18, 20))}]
    monkeypatch.setattr(YE, "HTTP", _http_canal(vids))
    r = YE.recentes(b, "UC1", forcar=True)
    assert [v["id"] for v in r["videos"]][0] == "C" and r["inscritos"] == 120 and r["videos"][0]["duracao"] == 45
    assert YE.dicas(r["videos"], agora=time.time() + 2 * 86400)["top"][0]["id"] == "A"  # (vídeo com menos de 6 h ainda não conta)
    novos, pulados = YE.adicionar(b, [{"pid": "p1", "canal_id": "c1", "nome": "Novo vídeo"},
                                      {"pid": "p2", "canal_id": "c1", "nome": "GATO pula o muro"}], agora=agora)
    # v84_361: o de hoje saiu às 08:00 (fora do horário) → não ocupa as 18:00 de hoje; amanhã o agendado das 18:20 ocupa as 18:00
    assert [x["slot"] for x in novos] == [_ts(hoje, 18)]
    n2, _ = YE.adicionar(b, [{"pid": "p9", "canal_id": "c1", "nome": "Outro"}], agora=agora)
    assert n2[0]["slot"] == _ts(depois, 18)
    assert "já tem um vídeo com esse título" in pulados[0]
    rr = YE._ler_recentes(b, "UC1")
    rr["dicas"] = YE.dicas(rr["videos"], agora=time.time() + 2 * 86400)
    with YE._TRAVA:
        YE._gravar(b, os.path.join("recentes", "UC1.json"), rr)
    ctx = YE.contexto_titulos(b, "c1")
    assert "Gato pula o muro" in ctx and "never copy" in ctx
    import curtos_comentario as CC
    p = {"canal_id": "c1"}
    monkeypatch.setattr(CC, "CONTEXTO_TITULOS", lambda base, p: YE.contexto_titulos(base, p.get("canal_id")))
    assert "PERFORMED BEST" in CC._contexto_titulos(b, p)


def test_v84_357_preenche_os_buracos_e_acha_o_padrao(tmp_path, monkeypatch):
    b = _base(tmp_path)
    YE.salvar_agenda(b, "c1", {"conta": "UC1", "por_dia": 3, "horarios": ["06:00", "12:00", "20:00"]})
    hoje = dt.date.today()
    d = [hoje + dt.timedelta(days=k) for k in range(4)]
    agora = _ts(hoje, 5)
    # no YouTube: agendados hoje e amanhã às 06:00 (faltam os das 12 e das 20)
    vids = [{"id": "H", "titulo": "hoje 6", "quando": _ts(d[0], 6), "agendado": _ts(d[0], 6), "privacidade": "private"},
            {"id": "A", "titulo": "amanha 6", "quando": _ts(d[1], 6, 2), "agendado": _ts(d[1], 6, 2), "privacidade": "private"}]
    with YE._TRAVA:
        YE._gravar(b, os.path.join("recentes", "UC1.json"), {"buscado": time.time(), "videos": vids})
    novos, _ = YE.adicionar(b, [{"pid": f"p{k}", "canal_id": "c1", "nome": f"v{k}"} for k in range(5)], agora=agora)
    assert [x["slot"] for x in novos] == [_ts(d[0], 12), _ts(d[0], 20), _ts(d[1], 12), _ts(d[1], 20), _ts(d[2], 6)]
    g = YE.grade(b, "c1", dias=3, agora=agora)
    assert [c["estado"] for c in g["dias"][0]["casas"]] == ["agendado", "fila", "fila"]
    assert [c["estado"] for c in g["dias"][2]["casas"]] == ["fila", "livre", "livre"] and g["proximo"] == _ts(d[2], 12)
    # o padrão: 10 dias saindo ~06:00, ~12:00 e ~20:00
    hist = []
    for k in range(1, 11):
        dia = hoje - dt.timedelta(days=k)
        hist += [{"quando": _ts(dia, 6, k % 3)}, {"quando": _ts(dia, 11, 55)}, {"quando": _ts(dia, 20, 5)}]
    hist.append({"quando": _ts(hoje - dt.timedelta(days=4), 15, 0)})  # um fora do costume não vira horário
    p = YE.padrao(hist, agora=agora)
    assert p["horarios"] == ["06:00", "11:55", "20:05"] and p["por_dia"] == 3
    assert YE.padrao([{"quando": agora - 100}], agora=agora)["horarios"] == []


def test_v84_358_sobe_ja_e_o_youtube_publica_no_horario(tmp_path, monkeypatch):
    b = _base(tmp_path)  # agenda sem 'modo' salvo → padrão é o YouTube agendar
    assert YE.agenda(b, "c1")["modo"] == "youtube"
    v, _ = _video(tmp_path, 100)
    hoje = dt.date.today()
    agora = time.time()
    novos, _ = YE.adicionar(b, [{"pid": "p1", "canal_id": "c1"}, {"pid": "p2", "canal_id": "c1"}])
    assert all(x["publicar"] and x["quando"] <= time.time() and x["slot"] > agora for x in novos)
    assert novos[1]["slot"] > novos[0]["slot"]  # cada um no seu horário
    corpos = []

    def http(m, u, **k):
        if u == YE.URL_UPLOAD:
            corpos.append(json.loads(k["data"]))
            return R(200, headers={"Location": "https://up/s"})
        return R(200, {"id": f"V{len(corpos)}"})

    monkeypatch.setattr(YE, "HTTP", http)
    meta = lambda pid: {"titulo": pid, "video": v}
    x1, x2 = YE.rodada(b, meta), YE.rodada(b, meta)  # os dois sobem JÁ, um atrás do outro
    assert x1["estado"] == x2["estado"] == "enviado" and x1["agendado_yt"]
    st = corpos[0]["status"]
    assert st["privacyStatus"] == "private" and YE._iso_ts(st["publishAt"]) == novos[0]["slot"]
    # o próximo vídeo não pega o horário dos que já subiram agendados
    n3, _ = YE.adicionar(b, [{"pid": "p3", "canal_id": "c1"}])
    assert n3[0]["slot"] not in (novos[0]["slot"], novos[1]["slot"]) and n3[0]["slot"] > novos[1]["slot"]
    # modo antigo: o site sobe na hora (público)
    YE.salvar_agenda(b, "c1", {"conta": "UC1", "horarios": ["12:00"], "modo": "site"})
    n4, _ = YE.adicionar(b, [{"pid": "p4", "canal_id": "c1"}], agora=_ts(hoje, 10))
    assert not n4[0]["publicar"] and n4[0]["quando"] == n4[0]["slot"]
    assert "publishAt" not in YE.corpo_video({"titulo": "a"}, YE.agenda(b, "c1"), 0)["status"]


def test_v84_359_atrasados_nao_saem_todos_de_uma_vez(tmp_path, monkeypatch):
    b = _base(tmp_path)
    YE.salvar_agenda(b, "c1", {"conta": "UC1", "por_dia": 3, "horarios": ["06:00", "12:00", "20:00"]})
    hoje = dt.date.today()
    agora = _ts(hoje, 13)
    # itens antigos (v84_357: sem 'publicar'), marcados pra 06:00 e 12:00 de hoje — o site estava fechado
    with YE._TRAVA:
        YE._gravar(b, "fila.json", [
            {"id": "a", "pid": "p1", "canal_id": "c1", "conta": "UC1", "nome": "A", "quando": _ts(hoje, 6), "estado": "na_fila", "tentativas": 0, "log": []},
            {"id": "b", "pid": "p2", "canal_id": "c1", "conta": "UC1", "nome": "B", "quando": _ts(hoje, 12), "estado": "na_fila", "tentativas": 0, "log": []},
            {"id": "c", "pid": "p3", "canal_id": "c1", "conta": "UC1", "nome": "C", "quando": _ts(hoje + dt.timedelta(days=1), 6), "estado": "na_fila", "tentativas": 0, "log": []},
            {"id": "d", "pid": "p4", "canal_id": "c1", "conta": "UC1", "nome": "D", "quando": agora - 7200, "slot": agora - 7200, "ja": True,
             "publicar": False, "estado": "na_fila", "tentativas": 0, "log": []}])
    assert YE.ajustar_atrasados(b, agora) == 3
    f = {x["id"]: x for x in YE.fila(b)}
    assert f["a"]["slot"] == _ts(hoje, 20) and f["b"]["slot"] == _ts(hoje + dt.timedelta(days=1), 12)
    assert f["c"]["slot"] == _ts(hoje + dt.timedelta(days=1), 6)  # o que não passou fica no horário dele
    assert all(f[k]["publicar"] and f[k]["quando"] <= agora for k in "abc")  # sobem já, com a data marcada
    assert "passou" in f["a"]["log"][-1]
    assert f["d"]["slot"] == agora - 7200 and not f["d"]["publicar"]  # 'subir já' não mexe
    corpos = []
    monkeypatch.setattr(YE, "HTTP", lambda m, u, **k: (corpos.append(json.loads(k["data"])) or R(200, headers={"Location": "https://s"})) if u == YE.URL_UPLOAD else R(200, {"id": "V"}))
    v, _ = _video(tmp_path, 100)
    x = dict(f["c"], slot=time.time() + 5 * 3600)  # (o relógio de verdade: a data marcada precisa estar no futuro)
    YE.enviar_item(b, x, lambda pid: {"titulo": pid, "video": v})
    assert corpos[0]["status"]["privacyStatus"] == "private" and YE._iso_ts(corpos[0]["status"]["publishAt"]) == int(x["slot"])


def test_v84_361_programado_fora_do_horario_nao_ocupa(tmp_path):
    b = _base(tmp_path)
    YE.salvar_agenda(b, "c1", {"conta": "UC1", "por_dia": 3, "horarios": ["06:00", "12:00", "20:00"]})
    hoje = dt.date.today()
    agora = _ts(hoje, 5)
    # programados no Studio às 09:00, 15:00 e 17:00 (fora dos seus horários) + um às 12:10 (esse ocupa o das 12)
    vids = [{"id": k, "titulo": k, "quando": _ts(hoje, h, m), "agendado": _ts(hoje, h, m), "privacidade": "private"}
            for k, h, m in (("a", 9, 0), ("b", 15, 0), ("c", 17, 0), ("d", 12, 10))]
    with YE._TRAVA:
        YE._gravar(b, os.path.join("recentes", "UC1.json"), {"buscado": time.time(), "videos": vids})
    novos, _ = YE.adicionar(b, [{"pid": f"p{k}", "canal_id": "c1", "nome": f"v{k}"} for k in range(3)], agora=agora)
    assert [x["slot"] for x in novos] == [_ts(hoje, 6), _ts(hoje, 20), _ts(hoje + dt.timedelta(days=1), 6)]
    g = YE.grade(b, "c1", dias=1, agora=agora)["dias"][0]
    assert [c["estado"] for c in g["casas"]] == ["fila", "agendado", "fila"] and g["fora_do_horario"] == 3
