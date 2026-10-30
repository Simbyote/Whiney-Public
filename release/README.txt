==============================================================
  SKYRIM MOD PACK - USER GUIDE
==============================================================

Whiney.exe configures Skyrim Special Edition to match
the pack: same mods, same load order, same settings. It also
launches the game through SKSE, records and explains crashes,
checks the setup for problems, and runs a Skyrim Together
server.

A first install takes 30-60 minutes, mostly downloading.


--------------------------------------------------------------
 1. REQUIREMENTS
--------------------------------------------------------------
  [ ] Skyrim Special Edition on Steam, launched once
      (to the main menu, then quit).
  [ ] Vortex (nexusmods.com/app) with Skyrim Special Edition
      set up as a managed game.
  [ ] SKSE, when the Doctor reports it missing.
  [ ] Free disk space: about 3x the size of the mod pack.
  [ ] Steam auto-updates off for Skyrim (game updates break
      SKSE mods): Steam > right-click Skyrim > Properties >
      Updates > "Only update this game when I launch it".

Nexus Premium and Python are not required.


--------------------------------------------------------------
 2. STARTING THE APP
--------------------------------------------------------------
Download Whiney.exe (or its zip, then extract it) from
the shared Drive and run it.

  "Windows protected your PC"  -> More info > Run anyway.
  Removed by antivirus         -> a known false positive for
                                  packaged Python apps; restore
                                  it from quarantine or add an
                                  exception.

If Skyrim is already running when the app starts, it offers
to watch it for crashes.


--------------------------------------------------------------
 3. SECTIONS
--------------------------------------------------------------
HOME
  Install state, game version, SKSE, and the SYNC CODE: a
  short code for the active load order. Matching codes mean
  matching load orders; compare them before multiplayer to
  avoid desyncs. Buttons: Play (SKSE), Play Skyrim Together,
  Install / Update, Run Doctor.
  This guide: "Installation guide" at the top right.
  SETUP CHECK, run at every start: whether the game already
  matches the pack (load order, and every mod file deployed).
  If it matches but the pack was never installed with this
  app, "Use my current setup" skips the install.
  Only the load order differs, and every mod is there?
  "Apply the pack's load order" fixes it in one click (close
  Vortex first). No reinstall needed; yours is kept as .bak.

INSTALL & UPDATE
  Mode: "Full install" (first time) or "Update only" (only
  what changed since the full pack). Start runs these steps:
    1. Check the PC (Doctor's basic checks). If every mod
       is already in the game, it offers to skip straight to
       step 4.
    2. Download the mod pack, unpack it, and prepare one zip
       per mod. Already have the pack file? It's found in
       Downloads automatically, or click "I already have the
       file..." and pick it (e.g. from a USB stick). Either
       way it's checked first, so a wrong file isn't used.
    3. Install in Vortex - the one manual step:
       a. A folder of mod files opens and Vortex starts.
       b. In Vortex, open Mods. In the folder press Ctrl+A and
          drag everything onto "Drop File(s)" (in batches of
          ~20 for large packs).
       c. If Vortex reports a mod as already installed:
          Replace.
       d. Select all > Enable > Deploy.
       e. Close Vortex completely (including the tray icon),
          then click "Done, Vortex is closed".
    4. Set the load order and game settings. The previous
       files are kept as .bak (Manage restores them).
    5. Verify that every plugin reached the game.
  Cancel (next to Start) stops the install at the next safe
  point. An interrupted or cancelled install resumes where
  it stopped: click Start again.

DOCTOR
  Run checks lists every problem found, most severe first.
  Red (FAIL) means the game will crash or the install will
  fail; yellow (WARN) is worth a look. Every card states the
  fix. Checks cover missing masters, load order, the plugin
  limit, game version, SKSE, Address Library, Creation Club
  content, crash logger, pack mods in Vortex, and disk space.
  Copy report / Save report produce the full text report.

Crash Squatch
  Either Play button (here or on Home) launches the game and
  watches it in the background. On a crash or freeze the app
  comes to the front with the most likely mods involved.
  "Watch running game" attaches to a game started elsewhere. History keeps
  the last 50 crashes and freezes; "Copy for <author>" copies
  a report of the selected one.
  With "Crash Logger SSE AE VR" installed (the Doctor flags
  it), reports name the exact mod.

HOST SERVER
  For the player hosting Skyrim Together: start/stop the
  server, copy the address to share, and allow the server
  through Windows Firewall. Connection troubleshooting (port
  forwarding, firewall, CGNAT) is listed at the bottom.

MANAGE
  Save backups and restores (Merge adds a backup's saves
  back; Replace makes the saves folder exactly the backup;
  either way the current saves are backed up first), restoring the original load
  order and INIs, freeing the space used by downloads,
  opening game folders, changing the game or Vortex mods
  folder, and uninstalling the pack.


--------------------------------------------------------------
 4. STARTING THE GAME
--------------------------------------------------------------
  Single-player  -> Play (SKSE). Starts the game through SKSE,
                    which most of the pack's mods need.
  Multiplayer    -> Play Skyrim Together. Starts the Skyrim
                    Together client, then connect to the host's
                    address from Skyrim Together's in-game menu.
                    Needs the Skyrim Together Reborn mod
                    deployed in Vortex; the button is disabled
                    until it is.

  Both are watched by Crash Squatch. A game started any other way
  (Steam, Vortex, SkyrimTogether.exe directly) is not watched
  until Crash Squatch > "Watch running game", and starting from
  Steam skips SKSE, so most mods will not load.

  After the first install: Vortex > Plugins, turn Autosort OFF
  so the pack's load order is kept.


--------------------------------------------------------------
 5. TROUBLESHOOTING
--------------------------------------------------------------
  Game crashes        -> Crash Squatch shows the likely cause;
                         then run the Doctor.
  Install stops       -> the reason is shown. Fix it and click
                         Start again; finished steps are
                         skipped.
  Drive blocks the    -> normal for large files. The file opens
  download               in the browser: click Download (and
                         "Download anyway"), wait for it to
                         finish, then click "It's downloaded".
  "Doesn't match the   -> the download was cut off or is the
  one ... packed"        wrong file; it was deleted. Click Start
                         to download it again. If it repeats,
                         get the latest Whiney.exe from the
                         pack maintainer.
  A mod appears in    -> remove it in Vortex and report its
  Vortex as a .zip       name to the pack maintainer.
  Anything else       -> Doctor > Copy report, and send it to
                         the pack maintainer. Logs are in
                         Downloads\Whiney.

Full removal: Manage > Uninstall pack, then remove the mods in
Vortex (Mods > select > Remove > Deploy).
