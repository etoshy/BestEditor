# 11 · Sons (efeitos sonoros)

Os sons ficam em `assets/sons/<categoria>/<nome>.m4a`. Os de fábrica estão nas categorias transições, variados,
passagem, cinema, impacto, pop, foley, digital, fogo, vento e respiro. Eles aparecem:

- na aba **🔊 Áudios** do Estúdio (ouvir, pôr no cursor, arrastar para a faixa **Sons**);
- como **sons automáticos**:
  - das transições (pela família);
  - das cenas (o som que o template pede);
  - dos destaques (`audio.assets` do estilo);
  - dos quadros editoriais (a tabela `dp_editorial.SONS`, ver o capítulo [18](18-quadros-editoriais.md)).

O site alinha o **pico** do som com o evento: o início da transição, a entrada do take, o impacto do destaque. Por
isso cada som tem o instante do pico guardado.

Lista: `python dp_guia.py listar sons`.

## Sem programar: um comando

```bash
python dp_guia.py som "C:\Downloads\boom grave.mp3" --categoria impactos_meus --nome "Boom grave"
```

O comando:

1. converte para `.m4a` em `assets/sons/impactos_meus/boom_grave.m4a`;
2. **mede** a duração, onde o som começa e onde fica o pico;
3. registra em `assets/darkplanner/extras/sons.json` com o id `impactos_meus/boom_grave`.

Depois reinicie o site, ou clique em 🔄 Reler os extras no 📘 Guia. Aceita mp3, wav, ogg, m4a, mp4… (qualquer coisa
que o ffmpeg lê).

### Usar o som num lugar específico

- **Num destaque seu**: `"audio": {"assets": ["impactos_meus/boom_grave"], "evento": "assentamento"}`
  (ver [05](05-destaques.md)).
- **Numa transição**: no Estúdio, clique no losango → som; ou, no código,
  `dp_sons._TR_ESPECIFICO["dp:minha_transicao"] = "impactos_meus/boom_grave"`.
- **Na timeline**: arraste da aba 🔊 Áudios.
- **Pela IA**: a lista de sons do prompt de edição já inclui os seus.

Dicas para um som que funciona bem:

- curto (0,3–2 s);
- sem silêncio grande no começo;
- volume normalizado (pico perto de −3 dB).

O site mistura os sons com a narração **sem** baixar o volume da voz.

## Com código

- `sons.json` (os de fábrica): `id`, `categoria`, `nome`, `arquivo`, `dur`, `inicio_som`, `pico`, `fim_som`,
  `nivel_db`. Use a função `dp_guia.medir_som()` para calcular.
- `dp_sons.MAPA_DP` traduz os nomes do darkplanner.json (`tpl:wh_cinema_4.mp3`) para os arquivos daqui.
- `_TR_FAMILIA` e `_TR_ESPECIFICO` decidem o som automático das transições.
