# Streets of Rage neural autoplay

Objetivo: uma única política neuronal joga **Blaze, Normal, 1 jogador, Any%**
desde o arranque ou assume uma partida já em curso. Glitches obtidos apenas por
inputs são válidos.

## Regras do agente

- Todos os inputs vêm da rede, incluindo menus, personagem, continuações,
  pontuação e endings.
- Não usar `reach_gameplay.py`, scripts de navegação, escritas em RAM ou estados
  preparados durante a execução final.
- A RAM é a observação principal; framebuffer só entra se a RAM se revelar
  insuficiente.
- Não codificar golpes, combos ou substados sem necessidade. A rede recebe os
  valores e aprende as relações.
- A execução pode ligar-se sem `restart_game()` e agir imediatamente a partir
  do estado observado.

## Ação

A política escolhe o estado bruto do comando e a duração:

- horizontal: esquerda, neutro, direita;
- vertical: cima, neutro, baixo;
- A, B, C e Start: solto ou pressionado;
- duração: 1, 2, 4 ou 8 frames.

Só são excluídos pares fisicamente contraditórios no mesmo eixo. Não existem
máscaras por animação ou listas de ataques válidos.

## Observação inicial

As larguras e significados vêm de
`StreetsOfRageRecompilation/code-analysis/addresses.csv`.

### Blocos brutos

- `0xFFB800..0xFFB87F`: objeto completo do jogador 1/Blaze;
- `0xFFB900..0xFFC8FF`: 32 objetos de gameplay, 128 bytes por slot.

### Estado global selecionado

- `game_state`, `level`, `wave` e `demo_mode`;
- `cam_x`, limites e velocidade da câmara;
- `level_pipeline_state`, `active_progression_entity_count` e
  `end_of_level_flag`;
- dificuldade, modo de jogadores e personagem;
- saúde, vidas, continues e especiais de P1;
- substados de menu, seleção de personagem, introdução e round clear;
- flags e ponteiros do ataque policial e bosses.

Os valores são normalizados, mas não recebem nomes semânticos adicionais. A
observação inclui também um pequeno histórico das observações e ações recentes.

## Recompensa

O dano causado não dá recompensa. A saúde inimiga continua observável para a
rede compreender o combate e para diagnosticar se um especial teve efeito.

### Positiva

- inimigo confirmado como eliminado, independentemente do método;
- boss eliminado;
- vaga avançada;
- ronda concluída;
- jogo concluído.

### Negativa

- cada frame decorrido;
- saúde, vida ou continue perdido por Blaze;
- especial consumido sem morte, dano, mudança útil de estado ou progressão
  durante toda a sequência do especial;
- período prolongado sem eliminação, progressão ou mudança relevante.

Não recompensar score, golpes, dano, armas, pickups ou distância percorrida por
si próprios. A câmara e a posição servem para medir progresso, nunca para
obrigar uma direção e bloquear atalhos ou glitches.

## Confirmação de eliminação

Cada ocupação de um slot é uma entidade distinta. Um slot reutilizado não conta
como a mesma entidade. Uma eliminação é confirmada pela limpeza/substituição de
um inimigo ativo acompanhada por pelo menos um destes sinais:

- saúde chegou a zero ou passou por estado de morte/remoção;
- `active_progression_entity_count` diminuiu;
- boss registado desapareceu;
- `wave` avançou ou `end_of_level_flag` foi ativado;
- ocorreu durante a reação confirmada ao ataque policial.

Um simples desaparecimento fora do ecrã não é automaticamente uma morte. Se um
despawn ou glitch desbloquear a progressão, conta como resultado útil.

## Episódios

- Treino desde o arranque: `restart_game()` e nenhuma outra preparação.
- Continuação: ligar ao processo existente sem reiniciar.
- Falha: campanha sem lives/continues recuperáveis ou limite de frames atingido.
- Sucesso de speedrun: entrada num ending após completar a ronda 8.
- Depois do sucesso, a política pode continuar a controlar o ending; o marco de
  tempo da run permanece a primeira entrada nesse ending.

## Primeira validação

Antes de treinar, um diagnóstico read-only deve confirmar ao vivo:

1. identificação de Blaze, Normal e 1P;
2. ciclo de vida e reutilização dos slots de inimigos;
3. mortes normais, por queda e pelo ataque policial;
4. boss derrotado, avanço de vaga e fim de ronda;
5. ligação a meio de uma partida sem reinício.

Os pesos numéricos da recompensa só serão fixados depois desta validação, para
serem proporcionais às frequências reais dos eventos.
