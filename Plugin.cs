using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using HarmonyLib;
using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace MusicPluginTrickyMaddness
{
    // Per-level Wwise-event music selector for Tricky Madness.
    //
    // The game's music is Wwise-only and NOT scoped to a level: both the menu
    // and every gameplay heat pull a blind random event from one 7-song pool
    // (see ssx/MUSIC_MOD_RE.md for the static RE). This plugin adds real
    // per-level selection by learning the current level's name and re-posting a
    // configured event, and can override the menu track and load custom .bnk
    // banks. Everything is a Wwise event name — there is no Unity AudioClip path
    // in this game, so a drop-in mp3/ogg is out of scope (README explains why).
    //
    // API note: this targets the CURRENT game build. The historical mod fields
    // (audioInfos / SongIndex / StartNewSong / audioSource) do not exist here.
    // Verified members (monodis on Assembly-CSharp.dll + AK.Wwise.Unity.API.dll):
    //   MenuManager.musicPlayer            : public GameObject (Wwise emitter GO)
    //   MenuManager.Instance               : public static property
    //   MenuManager.LoadScene(LevelEntry)  : instance IEnumerator (level load entry)
    //   LevelEntry.name                    : public string
    //   LevelManager.Start()               : posts the gameplay track inline
    //   AkSoundEngine.PostEvent(string, GameObject) / StopAll(GameObject) /
    //   LoadBank(string, out uint, uint)
    [BepInPlugin(PluginInfo.PLUGIN_GUID, PluginInfo.PLUGIN_NAME, PluginInfo.PLUGIN_VERSION)]
    public class Plugin : BaseUnityPlugin
    {
        public static Plugin Instance;
        public static Harmony harmony;
        internal static ManualLogSource Log;

        // --- BepInEx config (BepInEx/config/com.glitcherog.musicplugin.cfg) ---
        internal static ConfigEntry<bool> masterEnable;
        internal static ConfigEntry<bool> verboseLogging;
        internal static ConfigEntry<bool> overrideMenuMusic;

        // --- JSON config (Music/music_config.json) ---
        internal static MusicConfigData ConfigData;
        // level name -> Wwise event, built from ConfigData.levels (case-insensitive).
        private static readonly Dictionary<string, string> LevelToEvent =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        // Name of the level currently loading/loaded, captured in the
        // MenuManager.LoadScene(LevelEntry) prefix. This is the same value our
        // LevelHook registers custom maps under, so custom maps map cleanly too.
        internal static string CurrentLevelName;

        // Resolved absolute path to the Music folder (cross-platform).
        internal static string MusicDir;

        // Banks are loaded lazily on the first menu/level music post, by which
        // point the game itself has already initialised the Wwise sound engine.
        private static bool banksLoaded;

        private void Awake()
        {
            Instance = this;
            Log = Logger;

            masterEnable = Config.Bind("General", "Enabled", true,
                "Master switch. When false the plugin loads but applies no music " +
                "overrides and loads no custom banks.");
            verboseLogging = Config.Bind("General", "VerboseLogging", false,
                "Log every music decision (level name seen, event posted, bank " +
                "loads). Leave false for normal play.");
            overrideMenuMusic = Config.Bind("Menu", "OverrideMenuMusic", false,
                "Replace the main-menu track with the 'menuEvent' from the JSON " +
                "config. No effect if menuEvent is empty.");

            MusicDir = ResolveMusicDir();
            if (!Directory.Exists(MusicDir))
                Directory.CreateDirectory(MusicDir);
            Logger.LogInfo($"Music directory resolved to: {MusicDir}");

            LoadJsonConfig();

            harmony = new Harmony(PluginInfo.PLUGIN_GUID);
            harmony.PatchAll(typeof(Patches));
            Logger.LogInfo($"Plugin {PluginInfo.PLUGIN_GUID} v{PluginInfo.PLUGIN_VERSION} is loaded!");
        }

        // GameRootPath points at the executable's folder. On macOS that is
        // TrickyMadness.app/Contents/MacOS; walk up out of the .app so Music sits
        // next to run_bepinex.sh — the same relative layout as the Windows build
        // (next to the exe). Mirrors LevelHook's ResolveMapsDir. NO hardcoded '\\'.
        private static string ResolveMusicDir()
        {
            string root = BepInEx.Paths.GameRootPath;
            int idx = root.IndexOf(".app" + Path.DirectorySeparatorChar + "Contents",
                StringComparison.OrdinalIgnoreCase);
            if (idx < 0)
                idx = root.IndexOf(".app/Contents", StringComparison.OrdinalIgnoreCase);
            if (idx >= 0)
            {
                int slash = root.LastIndexOfAny(new[] { '/', '\\' }, idx);
                if (slash > 0) root = root.Substring(0, slash);
            }
            return Path.Combine(root, "Music");
        }

        private void LoadJsonConfig()
        {
            string path = Path.Combine(MusicDir, "music_config.json");
            try
            {
                if (!File.Exists(path))
                {
                    ConfigData = MusicConfigData.Default();
                    File.WriteAllText(path, JsonUtility.ToJson(ConfigData, true));
                    Logger.LogInfo($"Wrote default music config to {path}");
                }
                else
                {
                    ConfigData = JsonUtility.FromJson<MusicConfigData>(File.ReadAllText(path));
                    if (ConfigData == null)
                    {
                        Logger.LogWarning("music_config.json parsed to null; using empty config.");
                        ConfigData = new MusicConfigData();
                    }
                }
            }
            catch (Exception e)
            {
                Logger.LogError($"Failed to load music_config.json ({e.Message}); using empty config.");
                ConfigData = new MusicConfigData();
            }

            LevelToEvent.Clear();
            if (ConfigData.levels != null)
            {
                foreach (var ls in ConfigData.levels)
                {
                    if (ls == null || string.IsNullOrEmpty(ls.level) || string.IsNullOrEmpty(ls.@event))
                        continue;
                    LevelToEvent[ls.level] = ls.@event; // last duplicate wins
                }
            }
            Logger.LogInfo($"Loaded {LevelToEvent.Count} per-level song mapping(s); " +
                $"{(ConfigData.banks == null ? 0 : ConfigData.banks.Count)} custom bank(s) configured; " +
                $"menuEvent='{ConfigData.menuEvent}'.");
        }

        // Load user banks once, the first time we are about to post music. The
        // game has posted its own events by then, so the Wwise engine is up.
        internal static void EnsureBanksLoaded()
        {
            if (banksLoaded) return;
            banksLoaded = true;
            if (ConfigData == null || ConfigData.banks == null) return;
            foreach (var bank in ConfigData.banks)
            {
                if (string.IsNullOrEmpty(bank)) continue;
                string full = Path.IsPathRooted(bank) ? bank : Path.Combine(MusicDir, bank);
                if (!File.Exists(full))
                {
                    Log.LogWarning($"[Bank] configured bank not found: {full}");
                    continue;
                }
                try
                {
                    uint bankId;
                    AKRESULT res = AkSoundEngine.LoadBank(full, out bankId, 0u);
                    if (res == AKRESULT.AK_Success)
                        Log.LogInfo($"[Bank] loaded '{Path.GetFileName(full)}' (id {bankId})");
                    else
                        Log.LogWarning($"[Bank] LoadBank('{full}') returned {res}");
                }
                catch (Exception e)
                {
                    Log.LogError($"[Bank] exception loading '{full}': {e.Message}");
                }
            }
        }

        internal static bool TryGetLevelEvent(string levelName, out string ev)
        {
            ev = null;
            if (string.IsNullOrEmpty(levelName)) return false;
            return LevelToEvent.TryGetValue(levelName, out ev) && !string.IsNullOrEmpty(ev);
        }

        internal static void Verbose(string msg)
        {
            if (verboseLogging != null && verboseLogging.Value) Log.LogInfo(msg);
        }
    }

    // Harmony patches kept in a dedicated type so PatchAll(typeof(Patches))
    // picks them up by attribute, matching how our LevelHook is structured.
    internal static class Patches
    {
        // Capture the current level's name as the load coroutine is created.
        // levelEntry is the exact entry being loaded (the game sets
        // lastLevelEntry from it later, inside the coroutine), so this is the
        // earliest reliable point — and it fires for custom mod maps too, since
        // the LevelHook registers them as ordinary LevelEntry values.
        [HarmonyPatch(typeof(MenuManager), "LoadScene")]
        [HarmonyPrefix]
        private static void LoadScene_Prefix(LevelEntry levelEntry)
        {
            Plugin.CurrentLevelName = levelEntry.name;
            Plugin.Verbose($"[Level] LoadScene: current level = '{levelEntry.name}'");
        }

        // Gameplay music. Vanilla LevelManager.Start (verified inline, ~1.8 KB of
        // IL doing racer/camera/HUD setup as well) posts a RANDOM event from the
        // 7-song pool and drives the "MusicState" group (None -> Intro). We use a
        // POSTFIX, not a false-returning prefix: Start does far more than music,
        // so suppressing it would break the level. The postfix stops the random
        // track the vanilla code just posted and re-posts the mapped event on the
        // same musicPlayer GO. "MusicState" is left at Intro (as vanilla set it),
        // so the game's live Intro/Verse/Outro transitions still fire for
        // built-in events. Unmapped levels are untouched (vanilla random plays).
        [HarmonyPatch(typeof(LevelManager), "Start")]
        [HarmonyPostfix]
        private static void LevelManagerStart_Postfix()
        {
            if (Plugin.masterEnable == null || !Plugin.masterEnable.Value) return;

            string ev;
            if (!Plugin.TryGetLevelEvent(Plugin.CurrentLevelName, out ev))
            {
                Plugin.Verbose($"[Level] no mapping for '{Plugin.CurrentLevelName}'; vanilla random music kept");
                return;
            }

            var mm = MenuManager.Instance;
            if (mm == null || mm.musicPlayer == null)
            {
                Plugin.Log.LogWarning("[Level] MenuManager.musicPlayer unavailable; cannot post mapped song");
                return;
            }

            Plugin.EnsureBanksLoaded();
            AkSoundEngine.StopAll(mm.musicPlayer);          // kill the vanilla random pick
            AkSoundEngine.PostEvent(ev, mm.musicPlayer);    // post the mapped event
            Plugin.Log.LogInfo($"[Level] '{Plugin.CurrentLevelName}' -> posted '{ev}'");
        }

        // Menu music override. Vanilla MenuManager.Start posts "Play_00_Menu" on
        // musicPlayer. When enabled and a menuEvent is configured, stop it and
        // post the override on the same GO. (Note: returning to the menu from a
        // level re-posts the vanilla menu track from MenuManager.UnloadLevel,
        // which this postfix does not cover — documented limitation.)
        [HarmonyPatch(typeof(MenuManager), "Start")]
        [HarmonyPostfix]
        private static void MenuManagerStart_Postfix(MenuManager __instance)
        {
            if (Plugin.masterEnable == null || !Plugin.masterEnable.Value) return;
            if (Plugin.overrideMenuMusic == null || !Plugin.overrideMenuMusic.Value) return;

            string ev = Plugin.ConfigData != null ? Plugin.ConfigData.menuEvent : null;
            if (string.IsNullOrEmpty(ev)) return;
            if (__instance == null || __instance.musicPlayer == null) return;

            Plugin.EnsureBanksLoaded();
            AkSoundEngine.StopAll(__instance.musicPlayer);
            AkSoundEngine.PostEvent(ev, __instance.musicPlayer);
            Plugin.Log.LogInfo($"[Menu] menu music overridden -> '{ev}'");
        }
    }
}
