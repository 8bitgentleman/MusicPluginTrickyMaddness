using System;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;

namespace RadioBigTM
{
    // Mirrors the JSON the external player (radio/radio_server.py, --statusfile)
    // writes roughly every 200-250ms, atomically (temp+rename). Field names
    // must match the JSON keys exactly -- JsonUtility maps by name, no
    // [JsonProperty]-style renaming available without Newtonsoft, which this
    // project deliberately doesn't reference (JsonUtility covers this flat
    // shape fine).
    [Serializable]
    internal class TrackDto
    {
        public string title;
        public string artist;
        public string source;
        public float elapsed;
        // <=0 means "unknown" -- either the source JSON had a real `null` here
        // (neutralised to -1 by RadioStatusReader before JsonUtility ever sees
        // it, see there) or the key was omitted, which JsonUtility leaves at
        // the float default of 0. Either way the HUD treats it the same way:
        // show elapsed time only, skip the progress fraction.
        public float duration;
    }

    [Serializable]
    internal class StatusDto
    {
        public string state;      // "menu" | "racing" | "finished" | "idle"
        // `null` when nothing's playing. RadioJson sets this null for both an
        // explicit JSON `null` and an absent key -- tested, not assumed. The
        // HUD still also treats an empty title as "no track", which costs
        // nothing and keeps it honest if the player ever emits a blank one.
        public TrackDto track;
        public bool dj_talking;
        // Music bed suspended by the pill's play/pause key. Distinct from
        // "no track": a paused track is still the current track, still shown,
        // with its elapsed time frozen player-side.
        public bool paused;
    }

    // What the HUD actually reads: a snapshot that has already folded in the
    // freshness check, so nothing downstream needs to touch file timestamps.
    internal class RadioStatusSnapshot
    {
        public readonly string State;
        public readonly TrackDto Track;
        public readonly bool DjTalking;
        public readonly bool Paused;
        public readonly bool Fresh;

        public static readonly RadioStatusSnapshot Empty =
            new RadioStatusSnapshot("idle", null, false, false, false);

        public RadioStatusSnapshot(string state, TrackDto track, bool djTalking, bool paused,
                                   bool fresh)
        {
            State = state;
            Track = track;
            DjTalking = djTalking;
            Paused = paused;
            Fresh = fresh;
        }
    }

    // Polls Plugin.StatusFile on a timer (NOT every frame) and exposes the
    // latest parsed snapshot statically, mirroring how Plugin.CurrentLevelName
    // and Plugin.Client are already exposed. Lives on the plugin's persistent
    // GameObject, added alongside RadioBigHud in Plugin.Awake.
    internal class RadioStatusReader : MonoBehaviour
    {
        private const float PollIntervalSeconds = 0.22f;   // player writes ~200-250ms
        private const double StaleSeconds = 3.0;           // player gone -> treat as idle

        internal static RadioStatusSnapshot Latest { get; private set; } = RadioStatusSnapshot.Empty;

        private float _timer;
        // Poll failures keep the LAST GOOD snapshot rather than blanking the
        // HUD over one bad read -- which means a persistent failure is
        // invisible unless it says so. It logs unconditionally (not behind
        // VerboseLogging) but only when the message changes, so a stuck reader
        // costs one line, not one per poll. Without this a parse that started
        // failing the moment a real track appeared froze the HUD on "menu, no
        // track" for an entire race with a completely clean log.
        private string _lastProblem = "";

        private void Problem(string msg)
        {
            if (msg == _lastProblem) return;
            _lastProblem = msg;
            if (msg.Length > 0) Plugin.Log.LogWarning("[Radio] status reader: " + msg);
        }

        private void Update()
        {
            _timer += Time.unscaledDeltaTime;
            if (_timer < PollIntervalSeconds) return;
            _timer = 0f;
            Poll();
        }

        private void Poll()
        {
            string path = Plugin.StatusFile;
            if (string.IsNullOrEmpty(path) || !File.Exists(path))
            {
                // Player hasn't started (or hasn't written its first status
                // yet) -- nothing to show, not an error.
                Latest = RadioStatusSnapshot.Empty;
                return;
            }

            DateTime writeUtc;
            try { writeUtc = File.GetLastWriteTimeUtc(path); }
            catch { return; }   // transient I/O hiccup -- keep the last-known snapshot

            bool fresh = (DateTime.UtcNow - writeUtc).TotalSeconds <= StaleSeconds;
            if (!fresh)
            {
                // Stale file: the player process likely died. Fall back to
                // Empty (state "idle", track null) rather than leaving a
                // frozen ghost track on screen -- explicitly required by the
                // spec, and it's why this check exists at all instead of just
                // "file exists -> trust it".
                Latest = RadioStatusSnapshot.Empty;
                return;
            }

            string text;
            try { text = File.ReadAllText(path); }
            catch (Exception e)
            {
                // e.g. a race despite the writer's atomic rename -- skip this
                // poll, but say so if it keeps happening.
                Problem("read failed: " + e.GetType().Name + ": " + e.Message);
                return;
            }
            if (string.IsNullOrEmpty(text)) { Problem("file is empty"); return; }

            StatusDto dto;
            string error;
            if (!RadioJson.TryParse(text, out dto, out error))
            {
                Problem("parse failed (" + error + ") on: " + Trim(text));
                return;
            }

            Problem("");   // recovered
            Latest = new RadioStatusSnapshot(dto.state, dto.track, dto.dj_talking, dto.paused, true);
        }

        // Keep a bad payload readable in the log without dumping a whole file.
        private static string Trim(string s)
        {
            s = s.Replace('\n', ' ').Replace('\r', ' ');
            return s.Length <= 160 ? s : s.Substring(0, 160) + "...";
        }
    }

    // Hand-rolled extractor for the player's status JSON.
    //
    // This replaced JsonUtility, which froze the HUD in the field (2026-08-20):
    // the reader parsed the menu payload ("track": null) fine, then every
    // payload carrying a real track object failed, and because the only failure
    // log sat behind VerboseLogging (off by default) the HUD simply held the
    // last good snapshot -- state "menu", no track -- for the whole race, with
    // nothing in the log to say so.
    //
    // The payload is seven known scalars in a flat, fixed shape, so a real JSON
    // dependency would be overkill and JsonUtility brought two documented
    // unknowns with it (whether a JSON null maps to a C# null on a nested
    // [Serializable], and what a null does to a float field). Both are gone:
    // this is explicit, culture-invariant, and testable outside Unity -- which
    // is the point, since this plugin has no Editor project to run Unity's
    // serializer in.
    internal static class RadioJson
    {
        internal static bool TryParse(string json, out StatusDto dto, out string error)
        {
            dto = null;
            error = null;
            if (string.IsNullOrEmpty(json)) { error = "empty payload"; return false; }

            string state = ReadString(json, FindValue(json, "state", 0));
            if (state == null) { error = "no \"state\" string"; return false; }

            var d = new StatusDto();
            d.state = state;

            d.dj_talking = ReadTrue(json, FindValue(json, "dj_talking", 0));
            // Absent (an older player build) reads false, which is the right
            // default: nothing paused until something says so.
            d.paused = ReadTrue(json, FindValue(json, "paused", 0));

            // Absent or literal null both leave d.track null, which is exactly
            // what "nothing playing" means downstream.
            string track = ReadObject(json, FindValue(json, "track", 0));
            if (track != null)
            {
                var t = new TrackDto();
                t.title = ReadString(track, FindValue(track, "title", 0));
                t.artist = ReadString(track, FindValue(track, "artist", 0));
                t.source = ReadString(track, FindValue(track, "source", 0));
                t.elapsed = ReadNumber(track, FindValue(track, "elapsed", 0), 0f);
                // -1 for a null/absent/garbage duration -- the HUD's documented
                // "unknown, show elapsed only" sentinel.
                t.duration = ReadNumber(track, FindValue(track, "duration", 0), -1f);
                d.track = t;
            }

            dto = d;
            return true;
        }

        private static bool ReadTrue(string s, int i)
        {
            return i >= 0 && i + 4 <= s.Length && string.CompareOrdinal(s, i, "true", 0, 4) == 0;
        }

        // Index of the first character of key's value, or -1.
        private static int FindValue(string s, string key, int from)
        {
            string pat = "\"" + key + "\"";
            int i = s.IndexOf(pat, from, StringComparison.Ordinal);
            if (i < 0) return -1;
            i += pat.Length;
            while (i < s.Length && char.IsWhiteSpace(s[i])) i++;
            if (i >= s.Length || s[i] != ':') return -1;
            i++;
            while (i < s.Length && char.IsWhiteSpace(s[i])) i++;
            return i < s.Length ? i : -1;
        }

        private static string ReadString(string s, int i)
        {
            if (i < 0 || i >= s.Length || s[i] != '"') return null;   // null, number, absent
            var sb = new StringBuilder();
            i++;
            while (i < s.Length)
            {
                char c = s[i];
                if (c == '"') return sb.ToString();
                if (c != '\\') { sb.Append(c); i++; continue; }
                if (i + 1 >= s.Length) break;
                char n = s[i + 1];
                switch (n)
                {
                    case 'b': sb.Append('\b'); break;
                    case 'f': sb.Append('\f'); break;
                    case 'n': sb.Append('\n'); break;
                    case 'r': sb.Append('\r'); break;
                    case 't': sb.Append('\t'); break;
                    case 'u':
                        int cp;
                        if (i + 5 < s.Length && int.TryParse(s.Substring(i + 2, 4),
                                NumberStyles.HexNumber, CultureInfo.InvariantCulture, out cp))
                        {
                            sb.Append((char)cp);
                            i += 4;
                        }
                        break;
                    default: sb.Append(n); break;   // covers \" \\ \/
                }
                i += 2;
            }
            return null;   // unterminated
        }

        private static float ReadNumber(string s, int i, float fallback)
        {
            if (i < 0 || i >= s.Length) return fallback;
            int start = i;
            if (s[i] == '-' || s[i] == '+') i++;
            while (i < s.Length && (char.IsDigit(s[i]) || s[i] == '.'
                   || s[i] == 'e' || s[i] == 'E' || s[i] == '-' || s[i] == '+')) i++;
            if (i == start) return fallback;
            float v;
            // Invariant culture: the player writes '.' decimals regardless of
            // the machine's locale, and float.Parse would otherwise reject them
            // (or worse, read 485.964 as 485964) under e.g. de_DE.
            return float.TryParse(s.Substring(start, i - start), NumberStyles.Float,
                                  CultureInfo.InvariantCulture, out v) ? v : fallback;
        }

        // The raw "{...}" at i, brace-matched and string-aware, or null if the
        // value there isn't an object (e.g. a literal null).
        private static string ReadObject(string s, int i)
        {
            if (i < 0 || i >= s.Length || s[i] != '{') return null;
            int depth = 0;
            bool inStr = false;
            for (int j = i; j < s.Length; j++)
            {
                char c = s[j];
                if (inStr)
                {
                    if (c == '\\') j++;
                    else if (c == '"') inStr = false;
                    continue;
                }
                if (c == '"') inStr = true;
                else if (c == '{') depth++;
                else if (c == '}' && --depth == 0) return s.Substring(i, j - i + 1);
            }
            return null;   // unbalanced
        }
    }
}
