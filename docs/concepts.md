# Concepts

> The terms the code and docs use, explained once. Grouped by where they come
> from: the game, the modding tools, multiplayer, and this project.

---

## The game's plugins

**Plugin.** A `.esp`, `.esm` or `.esl` file in `Data\`: records (items, NPCs, places) a mod adds or changes. The game loads them in order; when two change the same record, the later one wins.

**Master / ESM.** A plugin other plugins can depend on. A plugin is a master if its extension is `.esm`/`.esl` **or** its header has the ESM flag (`0x1`); a flagged `.esp` counts. The game loads all masters before all regular plugins, keeping their relative order (`doctor.active_load_order`).

**Light plugin / ESL.** A plugin flagged `0x200`, or named `.esl`. Light plugins share one load-order slot (`0xFE`), so they don't count toward the limit.

**Plugin limit.** The load-order index is one byte: 254 full plugins (`0x00`–`0xFD`), with `0xFE` for light plugins and `0xFF` for forms the game creates at runtime. Over 254, the game crashes or silently drops plugins (`doctor.FULL_PLUGIN_LIMIT`).

**Masters list.** Each plugin's header names the masters it needs (`MAST` fields). A missing master crashes the game at startup; a master loading *after* its dependent is also invalid.

**TES4 header.** The first record in every plugin: `TES4`, data size, flags, then fields. A field over 64 KB is preceded by an `XXXX` field holding its real size (`doctor.read_plugin_header`).

**Official masters.** `Skyrim.esm`, `Update.esm` and the three DLC masters: always loaded first, listed or not.

**plugins.txt / loadorder.txt.** In `%LOCALAPPDATA%\Skyrim Special Edition`. `plugins.txt` is the active load order: one plugin per line, `*` in front means enabled, `#` lines are comments. The app copies the pack's version in during install (backing up the player's as `.bak`).

**Creation Club (CC) / Anniversary Edition.** Bethesda's paid content. `Skyrim.ccc` lists CC plugins; they load right after the official masters. Many CC files missing usually means the player doesn't own the Anniversary upgrade.

**INIs.** `Skyrim.ini` and `SkyrimCustom.ini` (shared through the pack) and `SkyrimPrefs.ini` (per-PC graphics, never shared), in `Documents\My Games\Skyrim Special Edition`.

---

## Modding tools

**SKSE (Skyrim Script Extender).** Extends the game so DLL plugins can load. Started through `skse64_loader.exe`; a game started from Steam skips it. Each SKSE build matches exactly one game version (`skse64_1_6_1170.dll` = game 1.6.1170).

**SKSE plugin.** A DLL in `Data\SKSE\Plugins\`. Most need the **Address Library** (`versionlib-<game version>.bin`), which tells them where game functions are in that exact version.

**Game version.** Read from `SkyrimSE.exe`'s version resource (`1.6.1170.0`). Steam updates change it and break SKSE until SKSE and its plugins update, hence "only update when I launch it".

**Vortex.** Nexus Mods' mod manager. Mods are installed into a **staging folder** (one folder per mod, named `<mod name>-<Nexus id>-<version>-<timestamp>`) and **deployed** into `Data\` as links. The app can't drive Vortex, so the player drags the prepared zips in.

**Crash logger.** An SKSE plugin (Crash Logger SSE, Trainwreck) that writes a log with the call stack and the records involved when the game crashes. Without one, Crash Squatch only has the Windows event log's "faulting module".

**ENB.** A graphics injector (`d3d11.dll` plus `enbseries.ini`/`enblocal.ini`). `d3d11.dll` alone may be ReShade.

---

## Multiplayer

**Skyrim Together Reborn.** The multiplayer mod. Every player must load the same plugins in the same order, or the game state desyncs.

**Sync code.** `XXXX-XXXX`, the first 8 hex digits of a SHA-1 of the enabled plugins in order, lowercased (`skyrim.sync_code`). Same code = same load order.

**CGNAT (carrier-grade NAT).** The ISP shares one public address between customers; the router's WAN address is in `100.64.0.0/10`. Port forwarding can't work then; the host needs a VPN-style tunnel or another host.

---

## This project

**Kit folder.** The repo root on the maintainer's PC: the `.bat` files, `pack_config.json`, the manifests (`paths.KIT_DIR`).

**Full pack / update pack.** `modpack.tar.gz` holds every mod. `modpack_update.tar.gz` holds every mod added or changed since the last full pack (cumulative), with `_update_info.json` listing added, changed and removed.

**Manifest.** `pack_manifest.json`: a fingerprint per mod (file names, sizes, modified times) from the last full pack, and the archive's SHA-256. The update diff compares against it.

**Checksum.** The SHA-256 of an archive, recorded by the packer (`pack_manifest.json`, `last_update.json`) and baked into the exe by `build.bat` (`base_sha256`, `update_sha256` in `requirements.json`). The installer refuses a download that doesn't match, so the exe and the files on Drive must come from the same pack run.

**Snapshot / `_packinfo`.** What `build.bat` records from the maintainer's PC and bakes into the exe: `plugins.txt`, `loadorder.txt`, the shared INIs, and `requirements.json` (game version, SKSE runtime, CC files, ENB, mod list, pack dates and checksums).

**Deployment inventory.** `_packinfo/files.json`, written by `build.bat`: for each pack mod, the files Vortex deployed from it into the maintainer's game folder (`Data/...`, or the game folder itself for SKSE- and ENB-type mods). Recorded from what is actually deployed, so files Vortex leaves out and disabled mods don't count. The Doctor, the installer's final check and Home's setup check compare players' game folders with it. Files the game itself writes into a mod's folder (`skyrim.RUNTIME_DIRS`: Skyrim Together's cache) are never recorded or checked.

**Install marker.** `installed.json` in the work folder: which full pack and update the player installed. Compared with `requirements.json` to show Install / Update ready / Installed.

**`_MEIPASS`.** Where a PyInstaller one-file exe unpacks its bundled data at runtime (`paths.BUNDLE_DIR`).
