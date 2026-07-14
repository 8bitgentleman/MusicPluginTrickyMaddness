using System;
using System.Collections.Generic;

namespace MusicPluginTrickyMaddness
{
    // JSON config model, shaped for UnityEngine.JsonUtility.
    //
    // JsonUtility CANNOT serialize a Dictionary, so the level->song map is a
    // List<LevelSong> inside this wrapper. Only public fields on [Serializable]
    // types are (de)serialized. No Newtonsoft (not shipped with the game).

    [Serializable]
    public class LevelSong
    {
        // The level identity, matched against LevelEntry.name (the name shown
        // on the level-select card). For our custom mod maps this is the map
        // file name (e.g. "Garibaldi Rebuilt"), because the LevelHook registers
        // each map's LevelEntry.name from its .asset filename.
        public string level;

        // The Wwise event to post for this level. Either a built-in game event
        // (e.g. "Play_04_LSD") or a custom event from a user-loaded .bnk bank.
        // Verbatim identifier so the JSON key is the natural word "event"
        // ("event" is a C# keyword; the '@' only escapes the identifier).
        public string @event;
    }

    [Serializable]
    public class MusicConfigData
    {
        // Wwise event posted for the main menu when [Menu] OverrideMenuMusic is
        // enabled in the BepInEx config. Empty = leave the vanilla menu track.
        public string menuEvent = "";

        // Bank files (relative to the resolved Music folder, or absolute) to
        // load via AkSoundEngine.LoadBank at startup. Custom events referenced
        // by menuEvent / levels[] must live in one of these banks.
        public List<string> banks = new List<string>();

        // Per-level song overrides. First match on level name wins.
        public List<LevelSong> levels = new List<LevelSong>();

        // A sensible default written on first run so users have a worked
        // example to edit. The Garibaldi entry maps our flagship custom map to
        // a built-in song (no custom bank required).
        public static MusicConfigData Default()
        {
            var d = new MusicConfigData();
            d.menuEvent = "";
            d.banks = new List<string>();
            d.levels = new List<LevelSong>
            {
                new LevelSong { level = "Garibaldi Rebuilt", @event = "Play_04_LSD" },
                new LevelSong { level = "Elysium Alps",      @event = "Play_01_White_Powder" }
            };
            return d;
        }
    }
}
