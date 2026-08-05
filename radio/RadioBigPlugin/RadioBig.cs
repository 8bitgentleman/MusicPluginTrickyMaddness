using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using HarmonyLib;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Threading;
using UnityEngine;

namespace RadioBigTM
{
    // Radio Big — the "full takeover" companion plugin.
    //
    // Tricky Madness has DISABLED Unity audio and is Wwise-only, so custom music
    // can't come out of the game (see ssx/MUSIC_MOD_RE.md). Instead an external
    // Python player (radio/radio_server.py) owns the music + DJ voice, and this
    // plugin is the thin bridge: it MUTES the game's own ~8 music events (SFX are
    // left alone), and forwards course start/end (and later gameplay beats) to the
    // player over a localhost socket. All pacing/selection lives in Python.
    //
    // Lifecycle mapping:
    //   LevelManager.Start           -> START <level name>   (race: intro -> song)
    //   LevelManager.Finish          -> FINISH               ("FINISHED" on screen)
    //   Play_00_Menu posted          -> MENU                 (lobby loops + banter)
    // Music-event suppression and the menu signal ride the same
    // AkSoundEngine.PostEvent(string, GameObject) choke point the game posts music
    // from — verified in Assembly-CSharp as the single music entry point.
    // VERSION: keep this in sync with radio_server.py's VERSION const. This one is
    // the load-bearing copy — BepInEx logs it on plugin load, so it's what a bug
    // reporter's LogOutput.log shows. (The player's copy only appears in the HELLO
    // reply, which this plugin never reads, so it's cosmetic — but sync it anyway.)
    [BepInPlugin("com.mtv.radiobig", "Radio Big", "1.2.0")]
    public class Plugin : BaseUnityPlugin
    {
        internal static Plugin Instance;
        internal static ManualLogSource Log;

        internal static ConfigEntry<bool> masterEnable;
        internal static ConfigEntry<bool> suppressGameMusic;
        internal static ConfigEntry<bool> verbose;
        internal static ConfigEntry<string> serverHost;
        internal static ConfigEntry<int> serverPort;
        internal static ConfigEntry<bool> autoLaunchPlayer;

        internal static ConfigEntry<bool> enableSsx3;
        internal static ConfigEntry<bool> enableTricky;
        internal static ConfigEntry<bool> enableOnTour;

        internal static string CurrentLevelName;
        internal static RadioClient Client;
        internal static Process PlayerProc;   // the bundled player, if we launched it
        internal static string CmdFile;       // command spool the player tails (file transport)

        // The game's music events (posted on MenuManager.musicPlayer). Muting
        // exactly these hands the music slot to Radio Big while leaving every SFX
        // event untouched. Play_00_Menu doubles as our return-to-menu signal.
        internal const string MenuEvent = "Play_00_Menu";
        internal static readonly HashSet<string> MusicEvents =
            new HashSet<string>(StringComparer.Ordinal)
        {
            "Play_00_Menu", "Play_01_White_Powder", "Play_03_APEX", "Play_04_LSD",
            "Play_05_Shellshock", "Play_11_Psychic_Damage", "Play_13_Amnesia",
            "Play_14_Back_To_Life",
        };

        private void Awake()
        {
            Instance = this;
            Log = Logger;
            // Survive scene loads. Deduced from the logs (2026-07-19): OnDestroy was
            // firing on the menu->race scene change, NOT at quit — it disposed the
            // command-file handle and KILLED the player process right as a race began,
            // which is what left every playtest silent (socket AND file, all builds).
            // Pinning the plugin GameObject across scenes stops the spurious teardown.
            DontDestroyOnLoad(gameObject);

            masterEnable = Config.Bind("General", "Enabled", true,
                "Master switch for Radio Big.");
            suppressGameMusic = Config.Bind("General", "SuppressGameMusic", true,
                "Mute the game's own music events so Radio Big owns the music slot. " +
                "SFX are never affected. Turn off to hear both (debugging).");
            verbose = Config.Bind("General", "VerboseLogging", false,
                "Log every event forwarded to the radio player.");
            serverHost = Config.Bind("Server", "Host", "127.0.0.1",
                "Host the Radio Big player (radio_server.py) listens on.");
            serverPort = Config.Bind("Server", "Port", 48757,
                "Port the Radio Big player listens on (must match radio_server.py).");
            autoLaunchPlayer = Config.Bind("Server", "AutoLaunchPlayer", true,
                "Launch the bundled Radio Big player automatically with the game. " +
                "Turn off if you run the player yourself (run_radio.sh, dev).");

            // Per-soundtrack switches. Turning one off removes its songs from the
            // shuffle; the remaining soundtracks' shares are renormalised by the
            // player, so the radio does not go quiet in proportion. DJ Atomika
            // keeps presenting regardless of which games' music is on.
            enableSsx3 = Config.Bind("Sources", "SSX3", true,
                "Play the SSX 3 soundtrack.");
            enableTricky = Config.Bind("Sources", "Tricky", true,
                "Play the SSX Tricky soundtrack.");
            enableOnTour = Config.Bind("Sources", "OnTour", true,
                "Play the SSX On Tour soundtrack (only if its audio is installed).");

            // Transport = a shared command file (NOT a socket). The game's Unity
            // Mono under wine (CrossOver) never delivered our localhost datagrams to
            // the player despite the send succeeding and the transport working in
            // every standalone wine repro — an unreproducible Unity-Mono-under-wine
            // socket black hole (see radio/ notes: 7 dead socket playtests). The
            // filesystem is shared by both wine processes and touches none of that:
            // the plugin appends verbs here, the player tails them. Truncate per
            // launch so the player never replays a previous session's STARTs.
            string dllDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
            CmdFile = Path.Combine(dllDir, "RadioBig", "radio.cmd");
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(CmdFile));
                File.WriteAllText(CmdFile, "");
            }
            catch (Exception e) { Logger.LogWarning($"[Radio] could not reset command file: {e.Message}"); }

            if (masterEnable.Value && autoLaunchPlayer.Value)
                LaunchPlayer();

            Client = new RadioClient(CmdFile, Log, () => verbose.Value);
            Client.Start();
            Client.Send("HELLO");

            new Harmony("com.mtv.radiobig").PatchAll(typeof(Patches));
            // Transport tag in the load line so a log unambiguously identifies which
            // build is live (we chased a lot of look-alike failures before this).
            Logger.LogInfo($"Radio Big loaded [file]. Music slot -> external player via {CmdFile}");
        }

        // Detect the platform family so we pick the matching frozen player. Mono's
        // OSVersion.Platform reports Unix for BOTH mac and linux, so we split those
        // by a filesystem tell (mac has /System/Library). "windows" | "mac" | "linux".
        private static string PlatformKey()
        {
            if (Path.DirectorySeparatorChar == '\\' ||
                Environment.OSVersion.Platform == PlatformID.Win32NT)
                return "windows";
            return Directory.Exists("/System/Library") ? "mac" : "linux";
        }

        // Spawn the frozen player that ships next to this DLL. One release tree
        // carries every OS's freeze; we launch the one matching the host:
        //   plugins/RadioBigTM.dll
        //   plugins/RadioBig/players/<windows|mac-arm64|linux>/RadioBigPlayer[.exe]  (+ _internal)
        //   plugins/RadioBig/assets/{dj,ssx3,tricky}
        // (The legacy flat plugins/RadioBig/player/ is still honored as a fallback.)
        // How the player stops, in order of reliability: (1) it watches our PID
        // (--gamepid) and exits the instant the game process dies — the only signal
        // that works under wine, where Unity never fires OnApplicationQuit; (2) on a
        // native/graceful quit OnApplicationQuit also sends an explicit QUIT for an
        // immediate stop; (3) the managed-grace timer (command file quiet 30 s) is a
        // last-ditch backstop. No orphan survives a quit on any target.
        private static void LaunchPlayer()
        {
            try
            {
                string dir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
                string root = Path.Combine(dir, "RadioBig");
                string assets = Path.Combine(root, "assets");

                // Candidate player dirs, most-specific first, ending in the legacy
                // flat layout. Only dirs that match the host OS are worth probing —
                // a mac can't run RadioBigPlayer.exe even though the file is present.
                string plat = PlatformKey();
                var dirs = new List<string>();
                if (plat == "windows") dirs.Add(Path.Combine(root, "players", "windows"));
                else if (plat == "mac") { dirs.Add(Path.Combine(root, "players", "mac-arm64"));
                                          dirs.Add(Path.Combine(root, "players", "mac")); }
                else dirs.Add(Path.Combine(root, "players", "linux"));
                dirs.Add(Path.Combine(root, "player"));   // legacy flat fallback

                // PyInstaller names the binary "RadioBigPlayer.exe" on Windows,
                // "RadioBigPlayer" on mac/linux — probe both within each dir.
                string exe = null, playerDir = null;
                foreach (string d in dirs)
                {
                    foreach (string name in new[] { "RadioBigPlayer.exe", "RadioBigPlayer" })
                    {
                        string cand = Path.Combine(d, name);
                        if (File.Exists(cand)) { exe = cand; playerDir = d; break; }
                    }
                    if (exe != null) break;
                }
                if (exe == null)
                {
                    Log.LogInfo($"[Radio] auto-launch skipped: no bundled {plat} player under " +
                                $"{Path.Combine(root, "players")} (run it from source, or this is a dev build).");
                    return;
                }
                // Pass the audio root BOTH as a CLI arg and an env var. Under wine
                // (CrossOver) an inherited env var may not reach the child, leaving
                // the player with an empty library -> game music muted but the radio
                // silent. The CLI arg survives that; the env var is kept for the
                // native path. Quote it — the path contains "Program Files (x86)".
                bool haveAssets = Directory.Exists(assets);
                // File transport: the player tails --cmdfile (host/port unused now).
                // --gamepid is the RELIABLE quit signal: the player watches our PID
                // and exits the instant the game dies. Under wine, Unity never fires
                // OnApplicationQuit (verified in the logs), so no in-game quit event
                // ever reaches the player — but the process going away is unmissable,
                // and the player + game share a PID namespace (spawned child) on both
                // native macOS and wine, so the watch resolves on either target.
                int gamePid = Process.GetCurrentProcess().Id;
                string args = $"--managed --gamepid {gamePid} --cmdfile \"{Plugin.CmdFile}\"";
                if (haveAssets) args += $" --assets \"{assets}\"";
                // Passed by argv, not env: env vars do not reliably reach a
                // wine-spawned child (same reason --assets is an arg). Always
                // sent, even when everything is on, so the player's log states
                // the effective set rather than leaving it to be inferred.
                var srcs = new System.Collections.Generic.List<string>();
                if (enableSsx3.Value) srcs.Add("ssx3");
                if (enableTricky.Value) srcs.Add("tricky");
                if (enableOnTour.Value) srcs.Add("sxot");
                if (srcs.Count == 0)
                    Log.LogWarning("[Sources] every soundtrack is switched off — " +
                                   "the DJ will talk but no music will play.");
                args += $" --sources \"{string.Join(",", srcs.ToArray())}\"";
                Log.LogInfo(haveAssets
                    ? $"[Radio] assets -> {assets}"
                    : $"[Radio] WARNING: assets dir not found at {assets} — the player " +
                      "will fall back to its bundled search; radio may be silent.");

                var psi = new ProcessStartInfo
                {
                    FileName = exe,
                    Arguments = args,
                    UseShellExecute = false,
                    WorkingDirectory = playerDir,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                };
                if (haveAssets)
                    psi.EnvironmentVariables["RADIO_BIG_ASSETS"] = assets;

                // CRITICAL: the game boots via BepInEx/Doorstop, which exports
                // DYLD_INSERT_LIBRARIES=libdoorstop.dylib (a BARE relative name —
                // run_bepinex.sh cd's into the doorstop dir first). A child spawned
                // here inherits that var but runs from playerDir, so dyld can't find
                // the dylib and HARD-KILLS the player at load, before Python starts.
                // The player is plain Python — it must never have doorstop injected.
                // Strip the injection vars (mac + linux) from the child's env.
                foreach (string v in new[] { "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH",
                                             "LD_PRELOAD", "LD_LIBRARY_PATH" })
                    psi.EnvironmentVariables.Remove(v);

                // The player is otherwise a black box when game-spawned (its stdout
                // goes nowhere), so tee both streams to a log next to the DLL. This
                // is how we see pygame/asset failures that only bite under launch.
                PlayerProc = Process.Start(psi);
                string plog = Path.Combine(dir, "RadioBig", "player.log");
                var writer = new StreamWriter(plog, false) { AutoFlush = true };
                PlayerProc.OutputDataReceived += (s, e) => { if (e.Data != null) writer.WriteLine(e.Data); };
                PlayerProc.ErrorDataReceived  += (s, e) => { if (e.Data != null) writer.WriteLine(e.Data); };
                PlayerProc.BeginOutputReadLine();
                PlayerProc.BeginErrorReadLine();
                Log.LogInfo($"[Radio] launched bundled player (pid {PlayerProc.Id}); log -> {plog}");
            }
            catch (Exception e)
            {
                Log.LogWarning($"[Radio] could not auto-launch player: {e.Message}. " +
                               "Start it manually (run_radio.sh) or check permissions.");
            }
        }

        private void OnDestroy()
        {
            // This fires on Tricky Madness's scene transitions, NOT just at quit —
            // proven in the logs, and DontDestroyOnLoad did not stop it. So we must
            // tear down NOTHING here: calling Client.Stop() killed the keepalive thread
            // mid-race, the player's managed grace then lapsed, and the music cut out
            // ~30 s into the level (and never returned, because the player had exited
            // by the time we got back to the menu). The static client and its keepalive
            // thread deliberately OUTLIVE this MonoBehaviour; they die with the game
            // process at a real quit, at which point the player self-exits on its grace
            // timer. Log only — do not stop the client, do not kill the player.
            Log.LogInfo("[Radio] OnDestroy fired (ignored — client keeps running across scenes).");
        }

        // The RELIABLE quit signal. Unlike OnDestroy (which fires on every scene
        // change), Unity raises OnApplicationQuit only when the game is actually
        // exiting — so here, and ONLY here, we tell the player to stop. Send QUIT so
        // it fades out and exits cleanly right now instead of leaving it to the 30 s
        // managed-grace backstop (which is why a quit felt like an uncontrollable
        // orphan: the player was reaped abruptly with the game, never told to stop).
        // The write is synchronous and flushed on this thread, so QUIT reaches the
        // file before the process dies; Stop() then closes our handle. The grace timer
        // remains the backstop for a hard kill, where OnApplicationQuit never fires.
        private void OnApplicationQuit()
        {
            try
            {
                Client?.Send("QUIT");
                Client?.Stop();
                Log.LogInfo("[Radio] OnApplicationQuit -> QUIT sent, client stopped.");
            }
            catch (Exception e) { Log.LogWarning($"[Radio] OnApplicationQuit error: {e.Message}"); }
        }

        internal static void Verbose(string msg)
        {
            if (verbose != null && verbose.Value) Log.LogInfo(msg);
        }
    }

    internal static class Patches
    {
        // Learn the level about to load (same reliable point the music plugin uses;
        // catches custom mod maps too).
        [HarmonyPatch(typeof(MenuManager), "LoadScene")]
        [HarmonyPrefix]
        private static void LoadScene_Prefix(LevelEntry levelEntry)
        {
            Plugin.CurrentLevelName = levelEntry.name;
        }

        // Course start -> tell the player to begin a race broadcast.
        [HarmonyPatch(typeof(LevelManager), "Start")]
        [HarmonyPostfix]
        private static void LevelManagerStart_Postfix()
        {
            if (Plugin.masterEnable == null || !Plugin.masterEnable.Value) return;
            string name = Plugin.CurrentLevelName ?? "";
            Plugin.Client.Send("START " + name);
            Plugin.Verbose($"[Radio] START {name}");
        }

        // Heat finished -> outro fires immediately (the "FINISHED" moment), so it
        // never bleeds into the next race. LevelManager.Finish() is the single
        // per-heat finish coroutine (gated on the player's Snowboarder.Finished()),
        // not a per-racer call — verified in Assembly-CSharp.
        [HarmonyPatch(typeof(LevelManager), "Finish")]
        [HarmonyPostfix]
        private static void LevelManagerFinish_Postfix()
        {
            if (Plugin.masterEnable == null || !Plugin.masterEnable.Value) return;
            Plugin.Client.Send("FINISH");
            Plugin.Verbose("[Radio] FINISH");
        }

        // Single choke point for BOTH jobs: suppress the game's music, and use the
        // menu track's post as the "back at the menu" signal (-> END). Returning
        // false skips the original PostEvent; __result is the Wwise playing id, so
        // hand back AK_INVALID_PLAYING_ID (0). SFX events fall straight through.
        [HarmonyPatch(typeof(AkSoundEngine), "PostEvent",
            new Type[] { typeof(string), typeof(UnityEngine.GameObject) })]
        [HarmonyPrefix]
        private static bool PostEvent_Prefix(string in_pszEventName, ref uint __result)
        {
            if (Plugin.masterEnable == null || !Plugin.masterEnable.Value) return true;
            if (in_pszEventName == null) return true;

            if (in_pszEventName == Plugin.MenuEvent)
            {
                // Booting into / returning to the lobby -> menu broadcast.
                Plugin.Client.Send("MENU");
                Plugin.Verbose("[Radio] MENU");
            }

            if (Plugin.suppressGameMusic.Value && Plugin.MusicEvents.Contains(in_pszEventName))
            {
                __result = 0u;     // AK_INVALID_PLAYING_ID
                return false;      // swallow the game's music, keep SFX
            }
            return true;
        }
    }

    // Background command writer: the Unity main thread only ever enqueues a verb;
    // the worker appends it to the shared command file so game frames never block on
    // I/O. Transport is a FILE, not a socket — see the note in Awake: the game's
    // Unity Mono under wine silently swallowed every localhost datagram we sent
    // (7 dead socket playtests, transport proven working in every standalone wine
    // repro). The filesystem is shared by both wine processes and sidesteps the
    // whole wine-networking / Unity-Mono socket layer. A bounded backlog keeps an
    // early START alive until the player has opened the file.
    internal class RadioClient
    {
        private readonly ManualLogSource _log;
        private readonly Func<bool> _verbose;
        private readonly string _cmdFile;
        private readonly object _writeLock = new object();  // serialises the two writers
        private Thread _keepalive;
        private volatile bool _running;
        // One long-lived append handle for the whole session (FileShare.ReadWrite so
        // the player keeps tailing concurrently). Opened once, up front, off the game
        // thread's first touch — never re-opened.
        private FileStream _fs;
        private StreamWriter _sw;
        // Time since the last write, shared by both writers to drive the keepalive.
        private readonly System.Diagnostics.Stopwatch _sinceSend =
            System.Diagnostics.Stopwatch.StartNew();
        // Keepalive: append a PING if we've been idle this long, so the player's
        // managed grace never lapses during a quiet menu. During play the real events
        // reset it, so the keepalive only matters at idle.
        private const int KeepAliveMs = 5000;

        public RadioClient(string cmdFile, ManualLogSource log, Func<bool> verbose)
        {
            _cmdFile = cmdFile; _log = log; _verbose = verbose;
        }

        public void Start()
        {
            lock (_writeLock) { if (!TryOpenHandle()) return; }
            _running = true;
            _keepalive = new Thread(KeepAliveLoop)
                { IsBackground = true, Name = "RadioBigKeepAlive" };
            _keepalive.Start();
        }

        // (Re)open the persistent append handle. Caller holds _writeLock.
        private bool TryOpenHandle()
        {
            try
            {
                _fs = new FileStream(_cmdFile, FileMode.Append, FileAccess.Write,
                                     FileShare.ReadWrite);
                _sw = new StreamWriter(_fs, new UTF8Encoding(false));
                return true;
            }
            catch (Exception e)
            {
                _log.LogWarning($"[Radio] could not open command file: {e.GetType().Name}: {e.Message}");
                _sw = null; _fs = null;
                return false;
            }
        }

        public void Stop()
        {
            _running = false;
            lock (_writeLock)
            {
                try { _sw?.Dispose(); _fs?.Dispose(); } catch { }
                _sw = null; _fs = null;
            }
            _log.LogInfo("[Radio] client stopped (command handle closed).");
        }

        // Called on the GAME thread from the Harmony patches, and writes RIGHT THERE,
        // synchronously. This is the crux of the whole fix: every prior design queued
        // the line for a background thread to write, but under the game's Unity Mono
        // on wine the GC suspends managed threads at each scene load and wine never
        // resumes a *waiting* one — so the sender thread went permanently dead the
        // instant the first real command (MENU/START, always mid scene-load) arrived,
        // and no game event ever reached the player (dead across BOTH socket and file
        // transports, identical signature). The game thread is the one wine always
        // resumes, and the write is a microsecond local append, so we just do it here.
        public void Send(string line)
        {
            if (string.IsNullOrEmpty(line)) return;
            lock (_writeLock)
            {
                // Self-heal: if a spurious OnDestroy (scene change) disposed the handle,
                // reopen it and keep writing. The command stream must outlive the
                // plugin's MonoBehaviour — losing it mid-race is what silenced the mod.
                if (_sw == null && !TryOpenHandle()) return;
                try
                {
                    AppendLine(line);
                    _sinceSend.Restart();
                    if (_verbose()) _log.LogInfo($"[Radio] wrote: {line}");
                }
                catch (Exception e)
                {
                    if (_verbose())
                        _log.LogWarning($"[Radio] write error ({line}): {e.GetType().Name}: {e.Message}");
                }
            }
        }

        // Keepalive ONLY. If this background thread gets GC-suspended-and-abandoned at
        // a scene load (see Send), the sole consequence is that a long idle menu after
        // that point stops PINGing — music playback, driven by game-thread Send, is
        // unaffected. Real events keep the grace alive whenever anything is happening.
        private void KeepAliveLoop()
        {
            while (_running)
            {
                Thread.Sleep(1000);
                if (!_running) break;
                if (_sinceSend.ElapsedMilliseconds < KeepAliveMs) continue;
                lock (_writeLock)
                {
                    if (_sw == null) break;
                    try
                    {
                        AppendLine("PING");
                        _sinceSend.Restart();
                        if (_verbose()) _log.LogInfo("[Radio] wrote: PING (keepalive)");
                    }
                    catch (Exception e)
                    {
                        if (_verbose())
                            _log.LogWarning($"[Radio] write error (PING): {e.GetType().Name}: {e.Message}");
                    }
                }
            }
        }

        // Append one verb to the session's persistent handle and flush to the OS so the
        // player's reader sees it next poll. Caller MUST hold _writeLock (both writers
        // do). The enter/exit probes bracket the actual I/O so a hang is unambiguous in
        // the log; they earned their keep proving the wedge was the thread, not the write.
        private void AppendLine(string line)
        {
            bool v = _verbose();
            if (v) _log.LogInfo($"[Radio] append-enter: {line}");
            _sw.Write(line + "\n");
            _sw.Flush();       // char buffer -> FileStream -> OS cache; the reader is
                               // a separate process but shares the host FS, so an OS
                               // flush is enough for it to see the bytes (no need for
                               // a heavier FlushFileBuffers, which is likelier to
                               // block under wine mid-scene-load).
            if (v) _log.LogInfo($"[Radio] append-exit: {line}");
        }
    }
}
