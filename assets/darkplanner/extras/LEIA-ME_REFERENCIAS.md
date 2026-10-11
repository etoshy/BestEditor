# Extras de referência (filmes, séries e documentários)

São 450 extras no formato do 📘 Guia, em 4 arquivos desta pasta:

| Arquivo | Itens | Tema |
|---|---|---|
| referencias_cinema.json | 50 | efeitos conhecidos (Star Wars, Ken Burns, Mad Max, true crime…) |
| referencias_cinema_2.json | 200 | Tarantino, séries, diretores e documentários |
| referencias_documentarios.json | 100 | documentários conhecidos (BBC, Ken Burns, Errol Morris, Herzog, Senna, Amy, brasileiros…) |
| referencias_aclamados.json | 100 | filmes e séries aclamados (clássicos, Oscar, Cidade de Deus, Sopranos, The Wire…) |

As miniaturas e prévias já estão em `assets/darkplanner/galeria/`.

## Direções

Cada item tem `"direcoes"` (por exemplo `["sys_cinema", "sys_doc_classico"]`). Desde a v84_51 o site usa esse campo:
o item entra sozinho nessas Direções do sistema. Os itens que a Direção já tinha continuam com pelo menos metade
do peso. Detalhes no capítulo 14 do 📘 Guia (`docs/guia/14-direcoes.md`).

O bloco `"_direcoes"` no fim de cada arquivo é só um resumo (o site não lê).

As cenas vêm com `autoEligible: false`: entram na lista de templates das Direções, mas a IA não as usa sozinha.
Mude para `true` quando quiser.

Para tirar um item de uma Direção, apague o id dela no `"direcoes"` do item e reinicie o site.
