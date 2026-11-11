"""v84_383: respostas grandes da IA por streaming + erro de verdade na tela."""
import json

import ia_servico as ia


class _Resp:
    def __init__(self, linhas, status=200):
        self.linhas, self.status_code = linhas, status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self, decode_unicode=True):
        return iter(self.linhas)

    def json(self):
        return {"error": {"message": "invalid x-api-key"}}


def _ev(d):
    return "data: " + json.dumps(d)


def test_stream_monta_a_resposta(monkeypatch):
    import requests
    pedido = {}
    linhas = ["event: message_start", _ev({"type": "message_start", "message": {"usage": {"input_tokens": 900}}}),
              _ev({"type": "content_block_delta", "delta": {"type": "text_delta", "text": '{"cenas": ['}}),
              _ev({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "1, 2]}"}}),
              _ev({"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 12}}), ""]
    monkeypatch.setattr(requests, "post", lambda url, **k: pedido.update(k) or _Resp(linhas))
    st, corpo = ia._transporte({"max_tokens": 64000, "messages": []}, "sk-ant-x", 900)
    assert st == 200 and corpo["content"][0]["text"] == '{"cenas": [1, 2]}' and corpo["stop_reason"] == "end_turn"
    assert corpo["usage"] == {"input_tokens": 900, "output_tokens": 12} and pedido["json"]["stream"] is True


def test_stream_erro_no_meio_e_erro_http(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "post", lambda url, **k: _Resp([_ev({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})]))
    assert ia._transporte({"max_tokens": 64000}, "k", 900)[0] == 529
    monkeypatch.setattr(requests, "post", lambda url, **k: _Resp([], status=401))
    st, corpo = ia._transporte({"max_tokens": 64000}, "k", 900)
    assert st == 401 and "invalid" in corpo["error"]["message"]


def test_ultimo_erro():
    ia._RECENTES.append({"quando": 0, "recurso": "roteiros", "ok": False, "erro": "a resposta passou do tamanho máximo"})
    assert "tamanho máximo" in ia.ultimo_erro("roteiros")
