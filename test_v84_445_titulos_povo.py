import metodo_roteiro as m
import thumbs_flow as tf


def test_titulo_academico():
    assert m.titulo_academico("Determinismo e Liberdade: Você Caiu na Armadilha?")
    assert m.titulo_academico("Cultura e Herança: Quem Está Abrindo as Caixas?")
    assert m.titulo_academico("Conhecimento. Ele Se Acumula ou Se Decodifica?")
    assert not m.titulo_academico("Medo. Como desligar isso?")
    assert not m.titulo_academico("Você Não Escolhe Nada")
    assert not m.titulo_academico("Platão Estava Certo Sobre o Instagram")


def test_regras_no_prompt():
    assert "LINGUAGEM DO POVO" in m.bloco_titulos(5)
    assert "PALAVRA DO POVO" in tf.REGRA_ALBERT and "impassivo" in tf.REGRA_ALBERT
    assert "Determinismo e Liberdade" in tf.REGRA_TITULOS_THUMB
    assert m.TITULO_MAX == 50


def test_copiou_exemplo():
    assert m.copiou_exemplo("Você não escolhe nada!")
    assert m.copiou_exemplo("Por Que Ninguém Lê Mais?")
    assert not m.copiou_exemplo("Você Não Escolhe o Que Ama")
    assert "nunca use estes" in tf.REGRA_TITULOS_THUMB
    assert "CARENTE" not in tf.REGRA_ALBERT and "OTÁRIO" not in tf.REGRA_ALBERT


def test_palavra_vazada():
    ctx = "voce finge que leu os classicos e se perde no indice".lower()
    assert tf._palavra_vazada("CARENTE", ctx)
    assert not tf._palavra_vazada("FINGIDO", ctx)
    assert not tf._palavra_vazada("PREGUIÇOSO", ctx)
    assert not tf._palavra_vazada("CARENTE", "a carencia afetiva de quem")
