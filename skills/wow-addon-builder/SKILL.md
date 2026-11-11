---
name: wow-addon-builder
description: Use when building a WoW Forever addon.
---

# WoW addon builder

Load this skill when building or fixing a World of Warcraft: Forever addon.

## Workflow

In order: `wow_env` → `wow_api` status (sync if the index is stale) → `wow_new` → write code, looking every call and event up with `wow_api` lookup first → `wow_check` until the verdict is `pass` → `wow_test` → `wow_install` (the user approves the write) → ask the user to `/reload` → `wow_errors` → fix and repeat. Pass `root` when the install is not the default World of Warcraft folder; that call searches only there.

`/wow status` and `hermes wow status` print install, build, and index state without choosing a tool. `hermes wow check <path>` exits non-zero when the verdict is `fail`.

## Forever rules

- Client 1.60.1, `## Interface: 16001`, Lua 5.1, retail Midnight API, not Classic.
- Old globals are gone: use `C_Item.GetItemInfo`, `C_ChatInfo.SendChatMessage`, and `C_UI.Reload`.
- Addons have no network and no file I/O. Game to outside is SavedVariables. Outside to game is a TOC-listed `.lua` file.
- The combat log is closed. Do not read combat data.

## Building blocks

`wow_new` copies from `src/wow_addon_forge/blocks/`: `core`, `log`, `sync`, `trust`, `window`, `bridge`. The name must be a Lua identifier. `dest` must be empty.

## Bridge

An addon opts in with `## X-Forge-Bridge: 1` and `Inbox.lua`. `hermes wow bridge pull --format discord` prints one line per new outbox record. Latency each way is one `/reload` or logout. The plugin holds no Discord credential.

## Policy

Blizzard's addon policy: free, readable code, no advertising, no donation prompts.

## Refusals

No input automation. No memory reading. No gold-bid loot system.
