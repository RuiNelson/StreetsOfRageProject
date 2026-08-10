# AI Goals

Este documento caracteriza os próimos passos na evolução do sistema de IA.

O documento elabora uma lista de objetivos para a próxima versão da IA.

Estes objetivos serão avaliados por um humano e marcados como completos quando o estiverem.

## A IA deve perseguir inimigos

A IA deve detetar quando tem inimigos e deve proceder a produzir `WalkToNearEnemy`. Tratar inimigos próximos vai ser mais urgente que ir ter com inimigos mais longínquos, decisão que vai ser tomada pela atribuição de emergência a `WalkToNearEnemy` inferior àquele atribuído a ataques a inimigos mais próximos.

A execução deste token deve ser cuidada tendo em conta que:

- o personagem não pode atacar o inimigo a cima ou abaixo dele, tem de estar mais ou menos em linha horizontal com ele
- o personagem não se deve aproximar mais do aquilo que é o suficente para atacar o inimigo, dependendo da sua arma (se tiver uma equipada) e da sua capacidade de dar murros, que é específica para cada personagem
- ao se mover verticalmente, a personagem deve ter cuidado para não entrar diretamente no raio de ação do inimigo

### Estado atual

* não funcional
