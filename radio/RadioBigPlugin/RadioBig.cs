using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using HarmonyLib;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
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
    [BepInPlugin("com.mtv.radiobig", "Radio Big", "0.1.0")]
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

        internal static string CurrentLevelName;
        internal static RadioClient Client;
        internal static Process PlayerProc;   // the bundled player, if we launched it

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

            if (masterEnable.Value && autoLaunchPlayer.Value)
                LaunchPlayer();

            Client = new RadioClient(serverHost.Value, serverPort.Value, Log,
                                     () => verbose.Value);
            Client.Start();
            Client.Send("HELLO");

            new Harmony("com.mtv.radiobig").PatchAll(typeof(Patches));
            Logger.LogInfo("Radio Big loaded. Music slot -> external player at " +
                           $"{serverHost.Value}:{serverPort.Value}.");
        }

        // Spawn the frozen player that ships next to this DLL:
        //   plugins/RadioBigTM.dll
        //   plugins/RadioBig/player/RadioBigPlayer   (+ _internal)
        //   plugins/RadioBig/assets/{dj,ssx3,tricky}
        // In managed mode the player self-exits when our socket drops (game quit
        // or crash), so no orphan survives; OnDestroy kills it as a backstop.
        private static void LaunchPlayer()
        {
            try
            {
                string dir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
                string playerDir = Path.Combine(dir, "RadioBig", "player");
                string exe = Path.Combine(playerDir, "RadioBigPlayer");
                string assets = Path.Combine(dir, "RadioBig", "assets");
                if (!File.Exists(exe))
                {
                    Log.LogInfo($"[Radio] auto-launch skipped: no bundled player at {exe} " +
                                "(start it manually, or this is a source/dev build).");
                    return;
                }
                var psi = new ProcessStartInfo
                {
                    FileName = exe,
                    Arguments = $"--managed --host {serverHost.Value} --port {serverPort.Value}",
                    UseShellExecute = false,
                    WorkingDirectory = playerDir,
                };
                if (Directory.Exists(assets))
                    psi.EnvironmentVariables["RADIO_BIG_ASSETS"] = assets;
                PlayerProc = Process.Start(psi);
                Log.LogInfo($"[Radio] launched bundled player (pid {PlayerProc.Id}).");
            }
            catch (Exception e)
            {
                Log.LogWarning($"[Radio] could not auto-launch player: {e.Message}. " +
                               "Start it manually (run_radio.sh) or check permissions.");
            }
        }

        private void OnDestroy()
        {
            if (Client != null) Client.Stop();
            try
            {
                if (PlayerProc != null && !PlayerProc.HasExited)
                    PlayerProc.Kill();
            }
            catch { }
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

    // Background socket sender: the Unity main thread only ever enqueues a line;
    // all connect/reconnect/write happens here so game frames never block on I/O.
    // Reconnects transparently so the player can be (re)started at any time; a
    // bounded backlog keeps an early START alive until the server is up.
    internal class RadioClient
    {
        private readonly string _host;
        private readonly int _port;
        private readonly ManualLogSource _log;
        private readonly Func<bool> _verbose;
        private readonly Queue<string> _queue = new Queue<string>();
        private readonly object _gate = new object();
        private Thread _worker;
        private volatile bool _running;
        private const int MaxBacklog = 64;

        public RadioClient(string host, int port, ManualLogSource log, Func<bool> verbose)
        {
            _host = host; _port = port; _log = log; _verbose = verbose;
        }

        public void Start()
        {
            _running = true;
            _worker = new Thread(Run) { IsBackground = true, Name = "RadioBigSender" };
            _worker.Start();
        }

        public void Stop()
        {
            _running = false;
            lock (_gate) { Monitor.PulseAll(_gate); }
        }

        public void Send(string line)
        {
            if (string.IsNullOrEmpty(line)) return;
            lock (_gate)
            {
                if (_queue.Count >= MaxBacklog) _queue.Dequeue();  // drop oldest
                _queue.Enqueue(line);
                Monitor.PulseAll(_gate);
            }
        }

        private void Run()
        {
            TcpClient tcp = null;
            NetworkStream stream = null;
            while (_running)
            {
                string line = null;
                lock (_gate)
                {
                    while (_running && _queue.Count == 0)
                        Monitor.Wait(_gate, 500);
                    if (!_running) break;
                    if (_queue.Count > 0) line = _queue.Peek();
                }
                if (line == null) continue;

                try
                {
                    if (tcp == null || !tcp.Connected)
                    {
                        tcp = new TcpClient();
                        tcp.Connect(_host, _port);   // fast on localhost
                        stream = tcp.GetStream();
                    }
                    byte[] bytes = Encoding.UTF8.GetBytes(line + "\n");
                    stream.Write(bytes, 0, bytes.Length);
                    stream.Flush();
                    lock (_gate) { if (_queue.Count > 0) _queue.Dequeue(); }  // sent; drop it
                    if (_verbose())
                        _log.LogInfo($"[Radio] sent: {line}");
                }
                catch (Exception)
                {
                    // Server not up yet / dropped. Close and retry shortly; the
                    // line stays queued (we only Peek'd) so it isn't lost.
                    try { if (tcp != null) tcp.Close(); } catch { }
                    tcp = null; stream = null;
                    Thread.Sleep(1000);
                }
            }
            try { if (tcp != null) tcp.Close(); } catch { }
        }
    }
}
