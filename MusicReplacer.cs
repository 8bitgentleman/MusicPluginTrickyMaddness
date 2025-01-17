using System;
using System.Collections.Generic;
using UnityEngine;
using System.Collections;
using System.IO;
using UnityEngine.Networking;
using UnityEngine.Events;
using HarmonyLib;
using MusicPluginTrickyMaddness;

public class MusicReplacer : MonoBehaviour
{
    public static MusicReplacer instance;
    uint BankID;
    public void Start()
    {
        var mOriginal = AccessTools.Method(typeof(MenuManager), "StartNewSong"); // if possible use nameof() here
        var mPrefix = SymbolExtensions.GetMethodInfo(() => PlayReplacement());

        MusicPluginTrickyMaddness.Plugin.harmony.Patch(mOriginal, null, new HarmonyMethod(mPrefix));

        LoadData(Directory.GetCurrentDirectory() + "\\Music");

        SongIndex = UnityEngine.Random.Range(0, audioInfos.Count);

        instance = this;
        audioSource = MenuManager.Instance.musicPlayer;

        AkSoundEngine.LoadBank(Directory.GetCurrentDirectory() + "\\Music\\GeneratedSoundBanks\\Windows\\New_SoundBank.bnk", out BankID, 0);
    }

    public static void PlayReplacement()
    {
        AkSoundEngine.StopAll();

        if(instance.SongIndex== instance.audioInfos.Count)
        {
            instance.SongIndex = 0;
        }

        AkSoundEngine.PostEvent(instance.audioInfos[instance.SongIndex].Path, audioSource.gameObject);
        //Plugin.Instance.Log("Playing New Song");
        //instance.audioSource.clip = instance.audioInfos[instance.SongIndex].clip;
        //instance.audioSource.Play();
        instance.SongIndex++;
    }

    public void NewSong(object in_cookie, AkCallbackType in_type, object in_callbackInfo)
    {
        PlayReplacement();
    }

    // Token: 0x060001BD RID: 445 RVA: 0x0000E4A0 File Offset: 0x0000C6A0
    public void LoadData(string path)
    {
        Banks = new List<string>();

        string[] array = File.ReadAllLines(path + "\\Music.cfg");
        this.audioInfos = new List<MusicReplacer.AudioInfo>();
        MusicReplacer.AudioInfo item = default(MusicReplacer.AudioInfo);
        bool flag = true;
        for (int i = 0; i < array.Length; i++)
        {
            string[] array2 = array[i].Split(new char[]
            {
                    ':'
            });
            if (array2[0].ToLower() == "bank")
            {
                Banks.Add(array2[1]);
            }
            if (array2[0].ToLower() == "name")
            {
                if (!flag)
                {
                    this.audioInfos.Add(item);
                    item = default(MusicReplacer.AudioInfo);
                }
                flag = false;
                item.Name = array2[1];
            }
            if (array2[0].ToLower() == "artist")
            {
                item.Artist = array2[1];
            }
            if (array2[0].ToLower() == "event")
            {
                item.Path = array2[1];
            }
        }
        this.audioInfos.Add(item);

        for (int j = 0; j < this.Banks.Count; j++)
        {
            this.LoadBanks(path + "\\" + this.Banks[j]);
        }
    }

    public void LoadBanks(string Path)
    {
        AkSoundEngine.LoadBank(Path, out BankID, 0);
    }

    // Token: 0x060001BF RID: 447 RVA: 0x00002EA1 File Offset: 0x000010A1
    //private IEnumerator GetAudioClip(string fileName, int AudioInfoPos)
    //{
    //    UnityWebRequest webRequest = UnityWebRequestMultimedia.GetAudioClip(fileName, (AudioType)13);
    //    yield return webRequest.SendWebRequest();
    //    if (webRequest.isNetworkError)
    //    {
    //        Debug.Log(webRequest.error);
    //    }
    //    else
    //    {

    //        AudioClip content = DownloadHandlerAudioClip.GetContent(webRequest);
    //        content.name = fileName;
    //        MusicReplacer.AudioInfo value = this.audioInfos[AudioInfoPos];
    //        value.clip = content;
    //        this.audioInfos[AudioInfoPos] = value;
    //        this.Loaded++;
    //    }

    //    Plugin.Instance.Log(AudioInfoPos.ToString());
    //    yield break;
    //}

    public static AudioSource audioSource;

    // Token: 0x0400020A RID: 522
    public List<MusicReplacer.AudioInfo> audioInfos = new List<MusicReplacer.AudioInfo>();

    // Token: 0x0400020C RID: 524
    private int Loaded;

    int SongIndex;

    public List<string> Banks;

    // Token: 0x0200004B RID: 75
    [Serializable]
    public struct AudioInfo
    {
        // Token: 0x0400020D RID: 525
        public string Name;

        // Token: 0x0400020E RID: 526
        public AudioClip clip;

        // Token: 0x0400020F RID: 527
        public string Artist;

        // Token: 0x04000211 RID: 529
        public string Path;
    }
}
