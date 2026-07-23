# AI Play — detetor de eventos

Primeiro componente da AI: observa uma sessão humana de *Streets of Rage* em
modo de um jogador através da porta remota do `MegaDriveEnvironment` e escreve
os eventos na consola em formato JSON Lines.

## Como executar

Num terminal, iniciar o jogo com um limite de execução e a porta remota ativa:

```bash
cd StreetsOfRageRecompilation
timeout -k 3 3600 ./build/sor --runSor --silent --rom rom/SOR.bin
```

Na raiz de `StreetsOfRageProject`, iniciar o detetor:

```bash
python3 -m ai_play
```

Por omissão, o detetor reutiliza
`StreetsOfRageRecompilation/tools/reach_gameplay.py`: reinicia o jogo, percorre
os menus através de input real, escolhe **Blaze**, espera até ela estar jogável
e começa então a observação. A navegação e o detetor partilham a mesma ligação
remota.

O cliente procura automaticamente
`MegaDriveEnvironment/python/src/megadrive_remote`. Também aceita outra porta,
máquina ou frequência:

```bash
python3 -m ai_play --host 127.0.0.1 --port 6969 --poll-hz 4 --character blaze
```

Para observar uma sessão que já esteja em curso, sem reiniciar ou navegar nos
menus:

```bash
python3 -m ai_play --observe-current-game
```

Interromper o detetor com `Ctrl-C`. Depois de Blaze ficar jogável, o detetor
deixa de enviar comandos e apenas observa a sessão humana.

## Modelo de polling

Depois da navegação inicial, são feitas aproximadamente quatro atualizações por
segundo. Cada atualização contém:

1. Uma única chamada `read_memory(0xFF0000, 0x10000)`, que copia os 64 KiB
   completos de Work RAM.
2. Uma leitura do contador remoto de frames, que não reside na Work RAM.

Todos os eventos atuais e futuros devem ser discriminados sobre a mesma cópia
local de RAM. Não devem ser acrescentadas leituras remotas de endereços RAM
individuais ao ciclo de polling.

## Eventos

| Evento | Sinal |
|---|---|
| `frames_elapsed` | Um ou mais intervalos de 60 VSyncs passaram. Intervalos em atraso são agregados num evento. |
| `player_energy_lost` | `$FFB832 (p1_health)` diminuiu durante gameplay 1P; inclui a quantidade. |
| `player_life_lost` | `$FFFF20 (p1_lives)` BCD diminuiu durante gameplay 1P. |
| `enemy_defeated` | Um ou mais slots de combatentes entraram numa transição letal entre snapshots. Nos inimigos comuns, compara o byte alto do estado em `+$30`; o byte baixo `+$31` contém flags que mudam durante a morte. Inclui quantidade, slots, tipos e energia. |
| `level_completed` | Flanco ascendente de `$FFFA73 (end_of_level_flag)`. |
| `level_increased` | `$FFFF02 (level)` aumentou durante a campanha, normalmente quando o round-clear avança para o nível seguinte; inclui nível anterior, novo nível e quantidade. |
| `level_decreased` | `$FFFF02 (level)` diminuiu durante a campanha; os números apresentados são 1–8. Isto também cobre o recuo da campanha que pode ocorrer no encontro final. |
| `game_completed` | Entrada no good ending (`game_state $24/$26`) ou bad ending (`$1C/$1E`). |

Exemplo de saída:

```json
{"event": "player_energy_lost", "frame": 912, "amount": 8, "before": 80, "after": 72}
{"event": "enemy_defeated", "frame": 1044, "count": 2, "enemies": [{"slot": 3, "type": "0x20", "name": "Garcia", "health_before": 8, "health_after": 0}, {"slot": 5, "type": "0x24", "name": "Signal", "health_before": 6, "health_after": -2}]}
```

## Testes

```bash
python3 -m unittest discover -s ai_play/tests -v
python3 -m py_compile ai_play/__init__.py ai_play/__main__.py ai_play/event_detector.py
```

Os testes verificam, entre outros casos, que cada snapshot usa exatamente uma
leitura dos 64 KiB completos de Work RAM e que várias derrotas observadas na
mesma atualização são agregadas.

Os pesos acordados para a reward do agente estão centralizados no objeto
imutável `DEFAULT_WEIGHTS`, em `ai_play/weights.py`. O peso de
`level_completed` é explicitamente zero; o avanço da campanha é recompensado
por `level_increased`.
