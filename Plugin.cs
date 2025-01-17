using BepInEx;
using HarmonyLib;
using UnityEngine;

namespace MusicPluginTrickyMaddness
{
    [BepInPlugin(PluginInfo.PLUGIN_GUID, PluginInfo.PLUGIN_NAME, PluginInfo.PLUGIN_VERSION)]
    [BepInProcess("Tricky Madness.exe")]
    public class Plugin : BaseUnityPlugin
    {
        public static Plugin Instance;

        public static Harmony harmony;

        bool Loaded = false;

        private void Awake()
        {
            // Plugin startup logic
            Instance = this;
            Logger.LogInfo($"Plugin {PluginInfo.PLUGIN_GUID} is loaded!");
            DoPatching();
        }

        public static void DoPatching()
        {
            harmony = new Harmony("com.glitcherog.patch");

            var mOriginal = AccessTools.Method(typeof(MenuManager), "Awake"); // if possible use nameof() here
            var mPrefix = SymbolExtensions.GetMethodInfo(() => AddMusicPlus());

            harmony.Patch(mOriginal, null, new HarmonyMethod(mPrefix));
        }

        public static void AddMusicPlus()
        {
            GameObject gameObject = new GameObject("Test");
            gameObject.transform.parent = MenuManager.Instance.musicPlayer.transform;
            gameObject.transform.localPosition = new Vector3(0, 0, 0);
            gameObject.AddComponent<MusicReplacer>();
        }

        public static void StopMusic()
        {
            AkSoundEngine.StopAll();
        }

        public void Log(string Log)
        {
            Logger.LogInfo(Log);
        }
    }
}
