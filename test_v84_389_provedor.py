"""v84_389: a IA errou o "provider" (pôs a busca nele) → não derruba o JSON inteiro."""
import json

import prompt_builder as pb


def test_consertar():
    v = {"animepexels_online", "material"}
    assert pb.consertar_provedor("anime daily life friends", "friends laughing", v) == ("animepexels_online", "friends laughing")
    assert pb.consertar_provedor("anime daily life friends", "", v) == ("animepexels_online", "anime daily life friends")
    assert pb.consertar_provedor("friends laughing", "animepexels_online", v) == ("animepexels_online", "friends laughing")
    assert pb.consertar_provedor("Anime Pexels Online", "x", v) == ("animepexels_online", "x")
    assert pb.consertar_provedor("material", "I3", v) == ("material", "I3")
    assert pb.consertar_provedor("pexels", "x", {"material"}) == ("pexels", "x")  # só material: erro normal


def test_json_com_item_errado_passa():
    itens = [{"start": 0, "end": 5, "provider": "animepexels_online", "query": "school"},
             {"start": 5, "end": 10, "provider": "anime daily life friends", "query": "friends walking"}]
    r = pb.parse_ai_response(json.dumps(itens), valid_providers=["animepexels_online", "material"], total_duration=10)
    assert [s.provider for s in r.segments] == ["animepexels_online", "animepexels_online"]
    assert r.segments[1].query.startswith("friends walking")
