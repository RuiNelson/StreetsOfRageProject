# Specification for Agents

The agents can be activated or deactivated with a button in the UI at any time.

The main goals is to defeat the enemies as fast as they can, take the least damage, finish the level fast.

## Basics

- must know how to control the three characters and take advantages of their highs/lows
- must calculate "pressure" to call the police special (large number of enemies, low health)
- must handle specifics of the stages
  - try not to fall in stage 4
  - know it's an elevator in stage 7 and not fall from it
  - know they have to move left in stage 8
  - know to handle Mr. X dialog (always choose "NO")
- pick up weapons and items
- be steady when the police special is in action or the game is paused

## Combat

Must know how to all the moves.

Must have handle the various enemies AIs, including bosses, handle multiple enemies at the same time.

Read the game code for understanding the AIs and beat them.

Position themselves in a least perilous position.

## Two player interaction

The agents must be able to play the game alone, but must also be able to play the game cooperatively with another agent or with an human.

- be able to do the move that only two player can do (grapple/jump/attack mid-air)
- don't be greedy in life and special attack items, let the other player take them if the other player has less health
- get weapons from the floor if a better weapons is found, don't wait for the other player to pick up them

