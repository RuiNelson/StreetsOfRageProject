# AI Play

Detetor de eventos e agente PPO para *Streets of Rage*. Ambos usam a porta
remota do `MegaDriveEnvironment`, arrancam uma campanha de um jogador com
**Blaze** e partilham uma única cópia dos 64 KiB de Work RAM por atualização.

## Detetor de eventos

Iniciar o jogo com limite de execução e a porta remota ativa:

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
os menus através de input real, escolhe Blaze, espera até ela estar jogável e
começa então a observação. A navegação e o detetor partilham a mesma ligação.

Também aceita outra porta, máquina ou frequência:

```bash
python3 -m ai_play --host 127.0.0.1 --port 6969 --poll-hz 5 --character blaze
```

Para observar uma sessão já em curso sem reiniciar:

```bash
python3 -m ai_play --observe-current-game
```

Depois da navegação são feitas aproximadamente cinco atualizações por segundo.
Cada atualização contém uma única leitura
`read_memory(0xFF0000, 0x10000)` e uma leitura do contador de frames. Todos os
discriminadores consomem a mesma cópia local.

### Eventos

| Evento | Sinal |
|---|---|
| `frames_elapsed` | Um ou mais intervalos de 60 VSyncs passaram. |
| `player_energy_lost` | `$FFB832 (p1_health)` diminuiu durante gameplay 1P. |
| `player_life_lost` | `$FFFF20 (p1_lives)` BCD diminuiu durante gameplay 1P. |
| `enemy_defeated` | Um ou mais slots entraram numa transição letal. |
| `level_completed` | Flanco de `$FFFA73`; mantido por diagnóstico, reward zero. |
| `level_increased` | `$FFFF02 (level)` aumentou durante a campanha. |
| `level_decreased` | `$FFFF02 (level)` diminuiu durante a campanha. |
| `game_completed` | Entrada no good ending ou bad ending. |

## Instalar o treino

O Python 3.14 do sistema pode continuar a executar o detetor, mas o stack de ML
fica isolado numa virtualenv Python 3.13:

```bash
uv venv --python python3.13 .venv
uv pip install --python .venv/bin/python -r ai_play/requirements-train.txt
```

O treino exige um Mac com PyTorch MPS disponível. `--train` usa explicitamente
`device="mps"` e termina com erro se Metal não estiver disponível; não existe
fallback silencioso para CPU.

## Treinar

Com um processo do jogo já ativo na porta 6969:

```bash
.venv/bin/python -m ai_play --train
```

O ambiente reinicia o jogo, escolhe Blaze e entra em lockstep antes do primeiro
passo. Um `step_input` remoto aplica o comando, avança exatamente 12 VSyncs e
devolve atomicamente o contador final e os 65 536 bytes de Work RAM. O jogo não
avança enquanto o PPO calcula a ação seguinte.

Também é possível deixar o treino lançar o processo, sempre à velocidade real
de 60 Hz e sem `--turbo`:

```bash
.venv/bin/python -m ai_play --train --launch-games --port 6970
```

Para recolha paralela, cada worker lança um processo na porta
`--port + índice`; com mais de um ambiente é usado `SubprocVecEnv(spawn)`:

```bash
.venv/bin/python -m ai_play \
  --train \
  --launch-games \
  --n-envs 4 \
  --port 6970 \
  --total-timesteps 1000000 \
  --progress-bar
```

Com um ambiente é usado `DummyVecEnv`. Sem `--launch-games`, os processos têm
de já estar ativos nas portas consecutivas. O modelo final é guardado por
omissão em `ai_play/models/ppo_sor.zip`; existem checkpoints periódicos e logs
TensorBoard na mesma diretoria.

O launcher verifica todas as portas antes de criar o modelo. Se alguma já
estiver ocupada, termina imediatamente e sugere o comando `lsof` correspondente.
No macOS, a porta 7000 é frequentemente usada pelo `ControlCenter`/AirPlay.

Para continuar:

```bash
.venv/bin/python -m ai_play --train --resume ai_play/models/ppo_sor.zip
```

### Observação e policy

A observação Gymnasium é:

```text
Box(low=0, high=255, shape=(65536,), dtype=uint8)
```

O extrator `PerceiverLiteExtractor` usa:

1. embedding dos 256 valores possíveis do byte, dimensão 16;
2. embedding absoluto aprendido para cada endereço 68000;
3. Conv1D com kernel/stride 16, reduzindo 65 536 para 4096 tokens de dimensão 64;
4. cross-attention de 128 latents, quatro heads;
5. dois blocos de self-attention apenas sobre os latents;
6. mean pooling e saída de 256 features.

O PPO é on-policy, portanto não mantém um replay buffer com observações RAM.
Usa `log_std_init=-1.0`, minibatches pequenos e a policy completa é treinada no
MPS.

### Ação

A ação contínua é:

```text
Box(
  low=[-1, -1, 0, 0, 0, 0, 0],
  high=[1, 1, 1, 1, 1, 1, 1],
  dtype=float32
)
```

Os valores são `[x, y, raio, A, B, C, Start]`. As coordenadas seguem o ecrã:
`+x` é direita e `+y` é baixo.

- `(x, y)` é quantizado numa das oito direções; diagonais premem duas teclas.
- `raio <= 0.25` descarta toda a combinação como ruído.
- `raio > 0.25` mapeia linearmente para 1–12 frames premidos.
- A, B e C só ativam acima de `0.5`.
- Start só ativa acima de `0.9`.
- Cada passo ocupa sempre 12 frames: mantém a combinação no início e solta-a
  nos frames restantes.

### Rewards e fim do episódio

Os pesos imutáveis estão em `ai_play/weights.py`:

| Sinal | Reward |
|---|---:|
| 60 frames decorridos | `-0.001` |
| cada ponto de energia perdido | `-0.10` |
| cada vida perdida | `-10` |
| inimigo comum derrotado | `+1` |
| boss derrotado | `+10` |
| `level_completed` | `0` |
| nível aumentado | `+50` |
| nível diminuído | `-50` |
| good ending | `+500` |
| bad ending | `-100` |
| ativação de Start | `-0.05` |

Não existe reward de wave nem castigo adicional de game over. O episódio
termina e o jogo é reiniciado depois de três vidas perdidas, ou quando a
campanha é completada. Existe ainda uma truncagem de segurança configurável
por `--max-episode-steps`.

## Testes

Testes sem dependências de treino:

```bash
python3 -m unittest discover -s ai_play/tests -v
```

Suite completa na virtualenv:

```bash
.venv/bin/python -m unittest discover -s ai_play/tests -v
```

Os testes cobrem os eventos, a reutilização dos 64 KiB, ações e thresholds,
rewards, episódio de três vidas, forward do Perceiver e construção da policy
PPO.
