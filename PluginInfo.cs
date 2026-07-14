namespace MusicPluginTrickyMaddness
{
    // Hand-written plugin metadata.
    //
    // The upstream project generated this class at build time via the
    // BepInEx.PluginInfoProps MSBuild task (as `MyPluginInfo`/`PluginInfo`).
    // The maintained build here is an `mcs` command line (build.sh), which has
    // no MSBuild code-gen, so the consts live in source. Keep PLUGIN_VERSION in
    // sync with any release tag.
    public static class PluginInfo
    {
        public const string PLUGIN_GUID = "com.glitcherog.musicplugin";
        public const string PLUGIN_NAME = "Tricky Madness Music Plugin";
        public const string PLUGIN_VERSION = "2.0.0";
    }
}
