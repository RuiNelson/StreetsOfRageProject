# Streets of Rage Project

![macOS](https://img.shields.io/badge/macOS-Supported-000000?logo=apple)
![Windows](https://img.shields.io/badge/Windows-Supported-0078D4?logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI%2BPHBhdGggZmlsbD0iI2ZmZiIgZD0iTTAgMGgxMS4ydjExLjJIMHpNMTIuOCAwSDI0djExLjJIMTIuOHpNMCAxMi44aDExLjJWMjRIMHpNMTIuOCAxMi44SDI0VjI0SDEyLjh6Ii8%2BPC9zdmc%2B)
![Linux](https://img.shields.io/badge/Linux-Supported-E95420?logo=linux&logoColor=white)
![PS5](https://img.shields.io/badge/PS5-Supported-003791?logo=playstation)

https://github.com/user-attachments/assets/84983bde-22ba-4627-94a7-a1f49b7dac3b

Welcome to my reverse-engineering and recompilation project for SEGA's
celebrated Mega Drive classic (released as SEGA Genesis in the United States),
*Streets of Rage*.

This is a strictly academic, non-commercial project. If you are looking for a
free copy of the game, this repository is not the place to find one: **it does
not contain copyrighted game material**. The original ROM is deliberately
omitted; you must provide a compatible image that you are legally entitled to
use.

The project brings together several components whose primary purpose is to
recompile Streets of Rage faithfully and make its internals available for
study.

## Main features over the original (all optional)

- **1 Player AI Assist** — play the game in 2P mode, with P1 controlled by you and P2 controlled by a very smart yet human-like AI built for this project. You can even betray the AI at the end. ;)
- **Widescreen 16:9** — the backgrounds and the play arena have both been expanded. Claude did a great job recalculating the enemy logic (such as hiding beyond the edge of the screen).
- **6 action buttons** — in the original, the game had to fit on a 3-button controller; here you also get a shortcut for the back attack (B+C, if you remember), plus dedicated "pick up item" and "throw knife" buttons. That means you no longer pick up an item when you meant to attack the enemy in front of you, or throw the knife by accident.

## Secondary features (all optional)

- **Enemy health display**
- **Persistent high scores between runs**, and you can preset the high-score initials so you don't have to enter them in the game
- **Roll the camera earlier** — in the original, the camera only started to roll once you were past the middle of the screen; with this option enabled, it starts to roll earlier, so you don't accidentally bump into enemies
- **Friend grab keeps weapon** — in the original, you dropped your weapon if a friend accidentally grabbed you, which was unfair
- **Enable the cheat in the menu** — in the original, you needed a second gamepad to enable the cheat; now you don't need to buy extra hardware
- **Pause Menu** — you can forfeit the game in the pause screen

This project is open source and open to improvement suggestions!

## Where to go next

- **I want to play it.** [Build it for Windows, macOS or Linux](docs/BuildingDesktop.md), or
  [for PlayStation 5](docs/BuildingPS5.md). The Builder does all the work on either route; you bring
  the ROM.
- **I have it running.** [Playing](docs/Playing.md) covers the controls, the options, the soundtrack,
  the AI partner and the command line.
- **I want to know how it was done.** The
  [Developer Journey and Project Structure](docs/DeveloperJourney.md) tells the story, from reading
  the machine code to teaching an AI to play.
- **I want to study the game.** [Researching](docs/Researching.md) shows how to read the code, map
  who calls whom and observe the running game.
