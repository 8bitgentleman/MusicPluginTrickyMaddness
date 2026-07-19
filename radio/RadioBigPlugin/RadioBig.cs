using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using HarmonyLib;
using System;
using System.Collections.Generic;
using System.Net.Sockets;
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
    //   LevelManager.Start           -> START <level name>   (begin a broadcast)
    //   Play_00_Menu posted          -> END                  (back at the menu)
    // Both music-event suppression and the menu signal ride the same
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

        internal static string CurrentLevelName;
        internal static RadioClient Client;

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

            Client = new RadioClient(serverHost.Value, serverPort.Value, Log,
                                     () => verbose.Value);
            Client.Start();
            Client.Send("HELLO");

            new Harmony("com.mtv.radiobig").PatchAll(typeof(Patches));
            Logger.LogInfo("Radio Big loaded. Music slot -> external player at " +
                           $"{serverHost.Value}:{serverPort.Value}.");
        }

        private void OnDestroy()
        {
            if (Client != null) Client.Stop();
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

        // Course start -> tell the player to begin a broadcast.
        [HarmonyPatch(typeof(LevelManager), "Start")]
        [HarmonyPostfix]
        private static void LevelManagerStart_Postfix()
        {
            if (Plugin.masterEnable == null || !Plugin.masterEnable.Value) return;
            string name = Plugin.CurrentLevelName ?? "";
            Plugin.Client.Send("START " + name);
            Plugin.Verbose($"[Radio] START {name}");
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
                // Returning to (or booting into) the menu ends any broadcast.
                Plugin.Client.Send("END");
                Plugin.Verbose("[Radio] END (menu)");
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
