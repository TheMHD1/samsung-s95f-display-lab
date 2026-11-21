// Read-only external-controller memory dump for the owner's S95F.
// The only OUT traffic is 12-byte read headers (opcode 0x101 direct, or 0x1 with a comp buffer ID). There is no write path in this program.
// TconDump-rt (Claude 2026-11-19): copy of TconDump-e2 (existing commands unchanged; they DO write: --poke/--restore/--wpoke/--armwait)
// plus --rt (power-on runtime gains, rtsvc/RT-SPEC.md), which writes only 586955CC/D0/D4/D8 and the pair 58602700/58622700.
using System; using System.Collections.Generic; using System.Diagnostics; using System.IO; using System.Linq;
using System.Net; using System.Net.Sockets; using System.Runtime.InteropServices; using System.Security.Cryptography; using System.Text.Json;
static class P {
  const string Usb="/sys/bus/usb/devices/7-1"; const uint Claim=0x8004550f, Release=0x80045510, Bulk=0xc0105502; const uint Timeout=2000;
  [StructLayout(LayoutKind.Sequential,Pack=4)] struct T{public uint Ep,Len,To;public IntPtr Data;}
  [DllImport("libc.so.6",SetLastError=true)] static extern int open(string p,int f);
  [DllImport("libc.so.6",SetLastError=true)] static extern int close(int f);
  [DllImport("libc.so.6",EntryPoint="ioctl",SetLastError=true)] static extern int ioN(int f,uint r,ref uint d);
  [DllImport("libc.so.6",EntryPoint="ioctl",SetLastError=true)] static extern int ioT(int f,uint r,ref T d);
  static int fd=-1; static long bulks=0;
  static void Need(bool b,string s){if(!b)throw new InvalidOperationException(s);}
  static string Rd(string n)=>File.ReadAllText(Usb+"/"+n).Trim();
  static void Xfer(bool input,byte[] b){
#if RT_FAKE
    if(FakeDev.On){bulks++;FakeDev.Xfer(input,b);return;}   // test harness only (rtsvc/csfake); not in the shipped build
#endif
    var h=GCHandle.Alloc(b,GCHandleType.Pinned);try{var t=new T{Ep=input?0x82u:0x02u,Len=(uint)b.Length,To=Timeout,Data=h.AddrOfPinnedObject()};int r=ioT(fd,Bulk,ref t);bulks++;Need(r==b.Length,$"bulk {(input?"IN":"OUT")} len={b.Length} r={r} errno={Marshal.GetLastWin32Error()}");}finally{h.Free();}}
  static readonly Dictionary<int,byte[]> Pool=new();static byte[] Read(uint op,uint addr,int len){var h=new byte[12];BitConverter.GetBytes(op).CopyTo(h,0);BitConverter.GetBytes(addr).CopyTo(h,4);BitConverter.GetBytes(len).CopyTo(h,8);Need(op==0x101||op==0x1||op==0x103,"op");Xfer(false,h);if(!Pool.TryGetValue(len,out var b))Pool[len]=b=new byte[len];Xfer(true,b);return b;}
  static int H(byte[] b,int i)=>b[i]|b[i+1]<<8;
  static (int s,int f,int g,int l) R(){var r=Read(0x101,0x47012400,256);return (H(r,0),H(r,10),H(r,14),H(r,0xc4));}
  static void Clean((int s,int f,int g,int l) r,string w){Need(r.s==0&&r.f==0&&r.g==1&&r.l==40,$"{w}: controller not Clean/limit40 {r}");}
  static int Serve(int port,string path){var l=new TcpListener(IPAddress.Loopback,port);l.Start();var t=l.AcceptTcpClientAsync();if(!t.Wait(120000)){l.Stop();return 3;}using var c=t.Result;l.Stop();using var f=File.OpenRead(path);using var n=c.GetStream();f.CopyTo(n,1<<20);n.Flush();return 0;}

  // Poke list entries are ADDR:OLD:NEW in hex. Only live CA fine gain/offset words for sense entries 600..660 are accepted, each change is bounded, and OLD must match before any write.
  static readonly uint[] CaBase={0x58691000u,0x58694C00u,0x58698800u};
  static bool Half(int v)=>v>=8000&&v<=26000;
  static readonly uint[] Enables={0x58602604u,0x58622604u,0x58602608u,0x5860260Cu,0x58602610u,0x58602618u,0x5860261Cu,0x58622608u,0x5862260Cu,0x58622610u,0x58622618u,0x5862261Cu};
  static bool IsEnable(uint a)=>Array.IndexOf(Enables,a)>=0;
  static void CheckAddr(uint a){bool ok=false;foreach(var b in CaBase){long i=((long)a-b)/4;if(a>=b&&(a-b)%4==0&&i>=600&&i<=660)ok=true;}Need(ok,"poke address not allowed");}
  static void CheckVal(uint v){Need(Half((int)(v&0xffff))&&Half((int)(v>>16)),"gain outside bound");}
  static void CheckPoke(uint a,uint o,uint n){if(IsEnable(a)){Need(o<=1&&n<=1,"enable values are 0/1");return;}CheckAddr(a);CheckVal(o);CheckVal(n);for(int s=0;s<2;s++)Need(Math.Abs((int)((o>>(16*s))&0xffff)-(int)((n>>(16*s))&0xffff))<=8000,"step bound");}
  static void WaitFlip(Dictionary<string,object?> o){uint s=R32(0x587005D8u);var w=Stopwatch.StartNew();while(w.ElapsedMilliseconds<100000){System.Threading.Thread.Sleep(40);if(R32(0x587005D8u)!=s){o["flip_ms"]=w.ElapsedMilliseconds;return;}}o["flip_ms"]=-1;}
  static void Write32(uint a,uint v){var h=new byte[12];BitConverter.GetBytes(0x102u).CopyTo(h,0);BitConverter.GetBytes(a).CopyTo(h,4);BitConverter.GetBytes(4).CopyTo(h,8);Xfer(false,h);Xfer(false,BitConverter.GetBytes(v));}
  static uint R32(uint a){var b=Read(0x101,a,16);return BitConverter.ToUInt32(b,0);}
  static void Claimed(int dev,string boot){
#if RT_FAKE
    if(FakeDev.On)return;
#endif
    Need(File.ReadAllText("/proc/sys/kernel/random/boot_id").Trim()==boot,"boot changed");Need(Rd("idVendor")=="04e8"&&Rd("idProduct")=="2001","ids");Need(int.Parse(Rd("busnum"))==7&&int.Parse(Rd("devnum"))==dev,"device");Need(Rd("power/runtime_status")=="active","usb not active");string drv=Usb+":1.2/driver";if(Directory.Exists(drv))Need(Path.GetFileName(new DirectoryInfo(drv).ResolveLinkTarget(true)?.FullName??"")=="usbfs","interface driver");fd=open($"/dev/bus/usb/007/{dev:D3}",2|0x80000|0x8000);Need(fd>=0,"open");uint itf=2;Need(ioN(fd,Claim,ref itf)==0,"claim");}
  // ---- --rt MODE PLAN (Claude 2026-11-19; rtsvc/RT-SPEC.md, CONSULT-14 §5-§6): power-on runtime gains -------------------
  // The ONLY addresses --rt ever writes: the four S1 words of lanes 627..630 and the weight pairs (blue 58602700/58622700;
  // since CONSULT-18 red 586026F8/586226F8 and green 586026FC/586226FC, Claude 2026-11-20).
  // PLAN = S1A:STOCK:NEW,S1B:STOCK:NEW,S1C:STOCK:NEW,S1D:STOCK:NEW,W (hex words; W = BLUE, or RED/GREEN/BLUE, decimal;
  // BLUE alone = red and green stay 205). All bounds are checked before the claim (RtParse, from Main) and again in front
  // of every single write (RtCheck).
  static readonly uint[] RtS1={0x586955CCu,0x586955D0u,0x586955D4u,0x586955D8u};
  static readonly uint[] RtStock={0x40AA40AEu,0x40A340A6u,0x409B409Fu,0x40944098u};       // stored stock words (hard-coded)
  static readonly uint[] RtW={0x586026F8u,0x586026FCu,0x58602700u,0x586226F8u,0x586226FCu,0x58622700u}; // R,G,B, twins R,G,B
  const uint BlueA=0x58602700u,BlueB=0x58622700u,RtRec=0x450158A8u; const int RtFloor=9900,RtStep=8000,WStock=205,BlueMin=205,BlueMax=820,RgMax=430;
  static readonly uint[] RgRegs={0x586026F8u,0x586226F8u,0x586026FCu,0x586226FCu};       // red pair, green pair
  static bool Pair(uint[] w,int i,int v)=>w[i]==v&&w[i+3]==v;                             // i: 0 red, 1 green, 2 blue
  static bool Dec(string s,out int v)=>int.TryParse(s,System.Globalization.NumberStyles.None,System.Globalization.CultureInfo.InvariantCulture,out v);
  static int Hf(uint w,int s)=>(int)((w>>(16*s))&0xffffu);
  static bool RtNewOk(int k,uint nw){if(nw==RtStock[k])return false;for(int s=0;s<2;s++){int h=Hf(nw,s),st=Hf(RtStock[k],s);if(h<RtFloor||h>st||st-h>RtStep)return false;}return true;}
  static string? RtParse(string mode,string plan,out uint[] nw,out int blue,out int rw,out int gw){
    nw=new uint[4];blue=0;rw=gw=WStock;
    if(mode!="audit"&&mode!="apply"&&mode!="apply-s1"&&mode!="restore")return "rt mode";
    if(mode=="restore")return null;                                   // restore uses only the hard-coded stock words
    var p=plan.Split(',');if(p.Length!=5)return "rt plan: 4 S1 entries + BLUE";var seen=new bool[4];
    for(int i=0;i<4;i++){var f=p[i].Split(':');if(f.Length!=3)return "rt plan entry ADDR:STOCK:NEW";uint ad,st,n;
      try{ad=Convert.ToUInt32(f[0],16);st=Convert.ToUInt32(f[1],16);n=Convert.ToUInt32(f[2],16);}catch{return "rt plan hex";}
      int k=Array.IndexOf(RtS1,ad);if(k<0)return $"rt S1 address {ad:x8} not allowed";if(seen[k])return $"rt S1 address {ad:x8} twice";seen[k]=true;
      if(st!=RtStock[k])return $"rt S1 {ad:x8} STOCK {st:x8} is not the stored stock {RtStock[k]:x8}";
      if(!RtNewOk(k,n))return $"rt S1 {ad:x8} NEW {n:x8} outside bounds (halves {RtFloor}..stock, step <= {RtStep}, not stock)";nw[k]=n;}
    var wf=p[4].Split('/');if(wf.Length!=1&&wf.Length!=3)return "rt weights: BLUE or RED/GREEN/BLUE";
    if(wf.Length==3&&(!Dec(wf[0],out rw)||!Dec(wf[1],out gw)||rw<WStock||rw>RgMax||gw<WStock||gw>RgMax))return $"rt RED/GREEN outside {WStock}..{RgMax}";
    if(!Dec(wf[^1],out blue)||blue<BlueMin||blue>BlueMax)return $"rt BLUE outside {BlueMin}..{BlueMax}";
    return null;}
  static void RtCheck(uint a,uint v,uint[] nw){int k=Array.IndexOf(RtS1,a);
    if(k>=0)Need(v==RtStock[k]||(v==nw[k]&&RtNewOk(k,v)),$"rt write {a:x8}={v:x8} refused");
    else if(Array.IndexOf(RgRegs,a)>=0)Need(v>=WStock&&v<=RgMax,$"rt write {a:x8}={v} refused");
    else Need((a==BlueA||a==BlueB)&&v>=BlueMin&&v<=BlueMax,$"rt write {a:x8}={v} refused");}
  // Live CA block (0x58691000, 0x16800 bytes; S1 = +0x3C00) against the stored copy captures/007-ca-state/ca0.bin (read only).
  const uint CaStart=0x58691000u; const int CaLen=0x16800;
  // PLACEHOLDERS: fill from YOUR TV with offline/ca_ref.py (GUIDE section 11). Until then CaCompare never matches and
  // apply refuses (fail closed). The S95F values used during development are not published (panel-unique data).
  const string CaRefSha="REPLACE_WITH_YOUR_CA_BLOCK_SHA256";
  static readonly uint[] CaS1Ref=new uint[61]; // S1 lanes 600..660
  // -> (whole block equals the stored copy, S1 600..660 differences). allowPlan: the four plan words holding NEW count as stock.
  static (bool eq,List<string> diff) CaCompare(uint[] nw,bool allowPlan){var b=new byte[CaLen];
    for(int off=0;off<CaLen;off+=512){var r=Read(0x101,CaStart+(uint)off,512);Buffer.BlockCopy(r,0,b,off,512);}
    for(int k=0;k<4;k++){int off=(int)(RtS1[k]-CaStart);if(allowPlan&&nw[k]!=0&&BitConverter.ToUInt32(b,off)==nw[k])BitConverter.GetBytes(RtStock[k]).CopyTo(b,off);}
    var diff=new List<string>();for(int L=600;L<=660;L++){uint v=BitConverter.ToUInt32(b,0x3C00+4*L);if(v!=CaS1Ref[L-600])diff.Add($"lane {L} {v:x8} (stored {CaS1Ref[L-600]:x8})");}
    using var sha=SHA256.Create();bool eq=Convert.ToHexString(sha.ComputeHash(b)).ToLowerInvariant()==CaRefSha;return (eq,diff);}
  // Re-checked immediately before the first S1 write and before every blue and R/G step (the first checks are up to ~106 s older).
  // Also requires the TV-side flag OUT.lcdon (refreshed by rt_tool every 3 s only while deviced reports "lcdon") 0..20 s old.
  static void RtGate(string w,string flag){var fi=new FileInfo(flag);double age=fi.Exists?(DateTime.UtcNow-fi.LastWriteTimeUtc).TotalSeconds:-1;
    Need(fi.Exists&&age>=0&&age<20,$"TV not lcdon: flag {(fi.Exists?$"{age:F0} s old":"missing")} ({w})");
    Clean(R(),w);uint rec=R32(RtRec);Need((rec&0xFFFFu)==0x0803u,$"record is not type 3 mode 8 ({w}: {rec:x8})");}
  static void Rt(string[] a,Dictionary<string,object?> o){
    string mode=a[4];var err=RtParse(mode,a[5],out var nw,out int blue,out int rw,out int gw);Need(err==null,err??"");o["mode"]=mode;
    var log=new List<string>();o["writes"]=log;bool inW=false;
    void Wr(uint ad,uint v){RtCheck(ad,v,nw);inW=true;Write32(ad,v);inW=false;}
    uint[] S1()=>RtS1.Select(R32).ToArray(); uint[] Wt()=>RtW.Select(R32).ToArray();
    void Report(){var s=S1();var w=Wt();var (ce,cd)=CaCompare(nw,mode!="restore");o["s1"]=s.Select(x=>x.ToString("x8")).ToArray();
      o["ca_equal"]=ce;if(cd.Count>0)o["ca_s1_diff"]=cd.Take(16).ToArray();
      o["s1_state"]=!ce?"other":s.SequenceEqual(RtStock)?"stock":(mode!="restore"&&s.SequenceEqual(nw))?"plan":"other";o["weights"]=w;
      o["blue_state"]=Pair(w,2,WStock)?"stock":(mode!="restore"&&Pair(w,2,blue))?"plan":"other";
      o["rg_state"]=(Pair(w,0,WStock)&&Pair(w,1,WStock))?"stock":(mode!="restore"&&Pair(w,0,rw)&&Pair(w,1,gw))?"plan":"other";}
    if(mode=="audit"){Report();o["rec"]=R32(RtRec).ToString("x8");o["state"]=R().ToString();return;}
    if(mode=="restore"){var left=new List<string>();
      try{uint a0=R32(BlueA),b0=R32(BlueB);o["blue_before"]=$"{a0},{b0}";
        if(a0!=WStock||b0!=WStock){if(a0<=820&&b0<=820){foreach(var ad in new[]{BlueA,BlueB}){Wr(ad,(uint)WStock);uint v=R32(ad);log.Add($"{ad:x8}->{v}");if(v!=WStock)left.Add($"{ad:x8} reads {v}");}}
          else left.Add($"blue pair {a0},{b0} outside 0..820: left");}
        foreach(var ad in RgRegs){uint v0=R32(ad);if(v0==WStock)continue;              // red/green pairs back to 205 (CONSULT-18)
          if(v0<=820){Wr(ad,(uint)WStock);uint v=R32(ad);log.Add($"{ad:x8}:{v0}->{v}");if(v!=WStock)left.Add($"{ad:x8} reads {v}");}
          else left.Add($"{ad:x8}={v0} outside 0..820: left");}
        for(int k=0;k<4;k++){uint v=R32(RtS1[k]);if(v==RtStock[k])continue;
          if(Half(Hf(v,0))&&Half(Hf(v,1))){Wr(RtS1[k],RtStock[k]);uint r=R32(RtS1[k]);log.Add($"{RtS1[k]:x8}:{v:x8}->{r:x8}");if(r!=RtStock[k])left.Add($"{RtS1[k]:x8} reads {r:x8}");}
          else left.Add($"{RtS1[k]:x8}={v:x8} outside 8000..26000: left");}}
      catch{if(inW)log.Add("write transfer failed: no further traffic");throw;}
      Report();
      if(!(o["ca_equal"] is bool ok&&ok))left.Add("CA block differs from stored copy after restore");
      Need(left.Count==0,"restore incomplete: "+string.Join("; ",left));return;}
    // apply / apply-s1
    var recs=new List<string>();o["rec"]=recs;
    for(int i=0;i<3;i++){if(i>0)System.Threading.Thread.Sleep(1000);uint rec=R32(RtRec);recs.Add(rec.ToString("x8"));Need((rec&0xFFFFu)==0x0803u,"record is not type 3 mode 8");}
    var s0=S1();o["s1_before"]=s0.Select(x=>x.ToString("x8")).ToArray();
    for(int k=0;k<4;k++)Need(s0[k]==RtStock[k]||s0[k]==nw[k],"S1 not stock/plan");
    var (ce0,cd0)=CaCompare(nw,true);Need(ce0,"CA block differs from stored copy"+(cd0.Count>0?": "+string.Join(", ",cd0.Take(4)):""));
    bool allNew=s0.SequenceEqual(nw);var w0=Wt();o["weights_before"]=w0;
    bool rgStock=Pair(w0,0,WStock)&&Pair(w0,1,WStock),rgPlan=Pair(w0,0,rw)&&Pair(w0,1,gw);
    Need(rgStock||(rgPlan&&allNew),"R/G weights not 205 (nor the plan with S1 all plan)");
    Need(w0[2]==w0[5],"blue pair unequal");
    Need(w0[2]==WStock||(w0[2]==blue&&allNew),$"blue pair {w0[2]} with S1 not all plan");
    if(allNew&&(mode=="apply-s1"||(w0[2]==blue&&rgPlan))){o["already"]=true;Report();return;}
    WaitFlip(o);Need(o["flip_ms"] is long fm&&fm>=0,"no bank flip within 100 s");
    var ws=Stopwatch.StartNew();
    while(ws.ElapsedMilliseconds<5000){System.Threading.Thread.Sleep(100);Need(Wt().SequenceEqual(w0),"weights changing (fade-in not finished)");}
    var doneS1=new List<int>();bool blueTouched=false,rgTouched=false;
    try{
      RtGate("before S1 writes",a[1]+".lcdon");var (ce1,cd1)=CaCompare(nw,true);Need(ce1,"CA block differs from stored copy (before S1 writes)");
      for(int k=0;k<4;k++){uint v=R32(RtS1[k]);
        if(s0[k]!=RtStock[k]){Need(v==nw[k],$"S1 {RtS1[k]:x8} changed to {v:x8}");continue;}
        Need(v==RtStock[k],$"OLD check {RtS1[k]:x8} has {v:x8}");Wr(RtS1[k],nw[k]);doneS1.Add(k);
        v=R32(RtS1[k]);log.Add($"{RtS1[k]:x8}:{RtStock[k]:x8}->{v:x8}");Need(v==nw[k],$"readback {RtS1[k]:x8} {v:x8}");}
      if(mode=="apply"&&w0[2]!=blue){int cur=WStock;bool first=true;
        while(cur<blue){int nx=Math.Min(cur+64,blue);if(!first)System.Threading.Thread.Sleep(300);first=false;RtGate($"before blue step {nx}",a[1]+".lcdon");
          foreach(var ad in new[]{BlueA,BlueB}){blueTouched=true;Wr(ad,(uint)nx);uint v=R32(ad);log.Add($"{ad:x8}:{cur}->{v}");Need(v==nx,$"readback {ad:x8} {v}");}
          cur=nx;}}
      if(mode=="apply"&&!rgPlan){int cr=WStock,cg=WStock;bool first=true;          // red/green pairs, steps <= 64, after blue
        while(cr<rw||cg<gw){int nr=Math.Min(cr+64,rw),ng=Math.Min(cg+64,gw);if(!first)System.Threading.Thread.Sleep(300);first=false;
          RtGate($"before R/G step {nr}/{ng}",a[1]+".lcdon");
          foreach(var (ad,cur,t) in new[]{(RgRegs[0],cr,nr),(RgRegs[1],cr,nr),(RgRegs[2],cg,ng),(RgRegs[3],cg,ng)}){if(t==cur)continue;
            rgTouched=true;Wr(ad,(uint)t);uint v=R32(ad);log.Add($"{ad:x8}:{cur}->{v}");Need(v==t,$"readback {ad:x8} {v}");}
          cr=nr;cg=ng;}}
      Clean(R(),"after writes");}
    catch{
      if(inW){log.Add("write transfer failed: no further traffic (no undo)");throw;}
      try{if(rgTouched)foreach(var ad in RgRegs){Wr(ad,(uint)WStock);uint v=R32(ad);log.Add($"undo {ad:x8}={v}");if(v!=WStock)log.Add($"undo readback mismatch {ad:x8}");}
        if(blueTouched)foreach(var ad in new[]{BlueA,BlueB}){Wr(ad,(uint)WStock);uint v=R32(ad);log.Add($"undo {ad:x8}={v}");if(v!=WStock)log.Add($"undo readback mismatch {ad:x8}");}
        for(int j=doneS1.Count-1;j>=0;j--){int k=doneS1[j];Wr(RtS1[k],RtStock[k]);uint v=R32(RtS1[k]);log.Add($"undo {RtS1[k]:x8}={v:x8}");if(v!=RtStock[k])log.Add($"undo readback mismatch {RtS1[k]:x8}");}}
      catch(Exception ue){log.Add(inW?"undo write transfer failed: no further traffic":"undo failed: "+ue.Message);}
      throw;}
    Report();}
  static int Tool(string[] a){var o=new Dictionary<string,object?>();int rc=1;bool c=false;string path=a[1];try{int dev=int.Parse(a[2]);string boot=a[3];Claimed(dev,boot);c=true;var r0=R();o["before"]=r0.ToString();Clean(r0,"before");
    if(a[0]=="--rt")Rt(a,o);
    else if(a[0]=="--restore"){var log=new List<string>();var items=a[4].Split(',').Select(s=>s.Split(':')).Select(s=>(ad:Convert.ToUInt32(s[0],16),nw:Convert.ToUInt32(s[1],16))).ToList();Need(items.Count<=32,"count");foreach(var i in items){if(IsEnable(i.ad))Need(i.nw<=1,"enable values are 0/1");else{CheckAddr(i.ad);CheckVal(i.nw);}}foreach(var i in items){Write32(i.ad,i.nw);uint v=R32(i.ad);log.Add($"{i.ad:x8}={v:x8}");Need(v==i.nw,$"restore readback {i.ad:x8} {v:x8}");}o["writes"]=log;}
    else if(a[0]=="--wpoke"){
      // CONSULT-13 E2 (Claude 2026-11-19): runtime per-colour weights 0x586026F8/FC/2700 + twins 0x586226F8/FC/2700 only.
      // Values 0..820; every register written together with its twin (same old/new); refuses unless the record is
      // type 3 mode 8 and all six weights are unchanged for 5 s; OLD must match; read-back must equal NEW, else both
      // already-written registers are put back to OLD and the call fails.
      var W=new uint[]{0x586026F8u,0x586026FCu,0x58602700u,0x586226F8u,0x586226FCu,0x58622700u};var log=new List<string>();
      var items=a[4].Split(',').Select(s=>s.Split(':')).Select(s=>(ad:Convert.ToUInt32(s[0],16),old:Convert.ToUInt32(s[1],16),nw:Convert.ToUInt32(s[2],16))).ToList();
      Need(items.Count>=2&&items.Count<=6&&items.Select(i=>i.ad).Distinct().Count()==items.Count,"weight count");
      foreach(var i in items){Need(Array.IndexOf(W,i.ad)>=0,"weight address");Need(i.old<=820&&i.nw<=820,"weight range 0..820");
        var t=items.Where(j=>j.ad==(i.ad^0x20000u)).ToList();Need(t.Count==1&&t[0].old==i.old&&t[0].nw==i.nw,"weight twin pair");}
      uint rec=R32(0x450158A8u);o["rec"]=rec.ToString("x8");Need((rec&0xFFFFu)==0x0803u,"record is not type 3 mode 8");
      var w0=W.Select(R32).ToArray();o["weights_before"]=string.Join(",",w0.Select(v=>v.ToString()));var ws=Stopwatch.StartNew();
      while(ws.ElapsedMilliseconds<5000){System.Threading.Thread.Sleep(100);Need(W.Select(R32).SequenceEqual(w0),"weights changing (fade-in not finished)");}
      foreach(var i in items){uint v=R32(i.ad);Need(v==i.old,$"precheck {i.ad:x8} has {v}");}
      var done=new List<(uint ad,uint old)>();bool inW=false;
      try{foreach(var i in items){inW=true;Write32(i.ad,i.nw);inW=false;done.Add((i.ad,i.old));uint v=R32(i.ad);log.Add($"{i.ad:x8}:{i.old}->{v}");Need(v==i.nw,$"readback {i.ad:x8} {v}");}}
      catch{if(inW)log.Add("write transfer failed: no further traffic (no undo)");else foreach(var d in done){try{Write32(d.ad,d.old);log.Add($"undo {d.ad:x8}={R32(d.ad)}");}catch{log.Add("undo failed");break;}}o["writes"]=log;throw;}
      o["writes"]=log;o["weights_after"]=string.Join(",",W.Select(R32).Select(v=>v.ToString()));}
    else if(a[0]=="--poke"){var log=new List<string>();var items=a[4].Split(',').Select(s=>s.Split(':')).Select(s=>(ad:Convert.ToUInt32(s[0],16),old:Convert.ToUInt32(s[1],16),nw:Convert.ToUInt32(s[2],16))).ToList();Need(items.Count<=32,"count");foreach(var i in items){CheckPoke(i.ad,i.old,i.nw);uint v=R32(i.ad);Need(v==i.old,$"precheck {i.ad:x8} has {v:x8}");}if(a.Length>5&&a[5]=="flip")WaitFlip(o);foreach(var i in items){Write32(i.ad,i.nw);uint v=R32(i.ad);log.Add($"{i.ad:x8}:{i.old:x8}->{v:x8}");Need(v==i.nw,$"readback {i.ad:x8} {v:x8}");}o["writes"]=log;}
    else{int n=int.Parse(a[5]),ms=int.Parse(a[6]);var ads=a[4].Split(',').Select(s=>Convert.ToUInt32(s,16)).ToArray();foreach(var ad in ads)Need(ad==0x587005D8u||(ad>=0x450158A8u&&ad<0x45015900u)||(ad>=0x58602600u&&ad<0x58602800u),"watch address");var sw=Stopwatch.StartNew();var rows=new List<string>();string last="";for(int k=0;k<n;k++){var s=string.Join(" ",ads.Select(x=>R32(x).ToString("x8")));if(s!=last){rows.Add($"{sw.ElapsedMilliseconds} {s}");last=s;}System.Threading.Thread.Sleep(ms);}o["changes"]=rows;o["span_ms"]=sw.ElapsedMilliseconds;}
    var r1=R();o["after"]=r1.ToString();Clean(r1,"after");rc=0;}catch(Exception e){o["error"]=e.GetType().Name+": "+e.Message;}finally{if(c){uint itf=2;o["released"]=ioN(fd,Release,ref itf)==0;}if(fd>=0)o["closed"]=close(fd)==0;}o["rc"]=rc;var js=JsonSerializer.Serialize(o);File.WriteAllText(path,js);Console.WriteLine(js);return rc;}
    // --armwait LOG POKES WAIT_S SAMPLE_S: wait (on the TV) for the controller USB device to appear, wait until every OLD value
  // is present (table loaded), require stop=0 fault=0 limit=40 (gate may be 0 during off-sensing), write, read back, then log
  // the sequencer record, R guard, bank selector and the poked words every 50 ms. Same address/value bounds as --poke.
  static int Arm(string[] a){var log=new StreamWriter(a[1],true){AutoFlush=true};var sw=Stopwatch.StartNew();void L(string m)=>log.WriteLine($"{DateTime.UtcNow:HH:mm:ss.fff} +{sw.ElapsedMilliseconds} {m}");int rc=1;bool c=false;
    try{var items=a[2].Split(',').Select(s=>s.Split(':')).Select(s=>(ad:Convert.ToUInt32(s[0],16),old:Convert.ToUInt32(s[1],16),nw:Convert.ToUInt32(s[2],16))).ToList();Need(items.Count<=8,"count");foreach(var i in items)CheckPoke(i.ad,i.old,i.nw);
      long waitMs=long.Parse(a[3])*1000,sampleMs=long.Parse(a[4])*1000;L("armed "+a[2]);
      while(!Directory.Exists(Usb)){Need(sw.ElapsedMilliseconds<waitMs,"no controller within wait");System.Threading.Thread.Sleep(50);}
      var t0=sw.ElapsedMilliseconds;L("usb present");Need(File.Exists(a[1]+".standby"),"TV not in standby (flag missing)");int dev=0;
      while(true){try{if(Rd("idVendor")=="04e8"&&Rd("idProduct")=="2001"&&Rd("power/runtime_status")=="active"){dev=int.Parse(Rd("devnum"));Need(int.Parse(Rd("busnum"))==7,"bus");string drv=Usb+":1.2/driver";bool ok=!Directory.Exists(drv)||Path.GetFileName(new DirectoryInfo(drv).ResolveLinkTarget(true)?.FullName??"")=="usbfs";if(ok){fd=open($"/dev/bus/usb/007/{dev:D3}",2|0x80000|0x8000);if(fd>=0){uint itf=2;if(ioN(fd,Claim,ref itf)==0){c=true;break;}close(fd);fd=-1;}}}}catch(IOException){}catch(UnauthorizedAccessException){}
        Need(sw.ElapsedMilliseconds-t0<20000,"claim timeout");System.Threading.Thread.Sleep(20);}
      L($"claimed dev {dev}");string lastPre="";
      while(true){var r=R();var vals=items.Select(i=>R32(i.ad)).ToArray();string pre=$"R {r} vals "+string.Join(",",vals.Select(v=>v.ToString("x8")));if(pre!=lastPre){L(pre);lastPre=pre;}
        bool loaded=items.Select((i,k)=>vals[k]==i.old).All(x=>x);if(loaded&&r.s==0&&r.f==0&&r.l==40)break;
        Need(sw.ElapsedMilliseconds-t0<30000,"table not loaded / guard not ok within 30 s");System.Threading.Thread.Sleep(5);}
      Need(File.Exists(a[1]+".standby"),"TV left standby before write");foreach(var i in items){Write32(i.ad,i.nw);uint v=R32(i.ad);L($"write {i.ad:x8}:{i.old:x8}->{v:x8}");Need(v==i.nw,"readback");}
      var t1=sw.ElapsedMilliseconds;string last="";
      while(sw.ElapsedMilliseconds-t1<sampleMs){var r=R();string s=$"rec {R32(0x450158A8u):x8} {R32(0x450158ACu):x8} sel {R32(0x587005D8u):x8} R {r} pk "+string.Join(",",items.Select(i=>R32(i.ad).ToString("x8")));if(s!=last){L(s);last=s;}System.Threading.Thread.Sleep(50);}
      rc=0;L("done");}
    catch(Exception e){L("stop: "+e.GetType().Name+": "+e.Message);}
    finally{if(c){uint itf=2;try{ioN(fd,Release,ref itf);}catch{}}if(fd>=0)close(fd);L($"exit rc={rc}");log.Dispose();}return rc;}
  static int Main(string[] a){
    if(a.Length==5&&a[0]=="--armwait")return Arm(a);
    if(a.Length>=1&&a[0]=="--rt"){                                     // --rt OUT DEVNUM BOOT MODE PLAN; plan refused before any claim
      string? e=a.Length!=6?"usage: --rt OUT DEVNUM BOOT MODE PLAN":RtParse(a[4],a[5],out _,out _,out _,out _);if(e==null)return Tool(a);
      var ej=JsonSerializer.Serialize(new Dictionary<string,object?>{["error"]="InvalidOperationException: "+e,["rc"]=1});
      try{if(a.Length>1)File.WriteAllText(a[1],ej);}catch{}Console.WriteLine(ej);return 1;}
    if(a.Length>=5&&(a[0]=="--poke"||a[0]=="--watch"||a[0]=="--restore"||a[0]=="--wpoke"))return Tool(a);
    if(a.Length==3&&a[0]=="--serve")return Serve(int.Parse(a[1]),a[2]);
    string rcpt="/dev/null";for(int i=0;i+1<a.Length;i++)if(a[i]=="--out")rcpt=a[i+1]+".json";var o=new Dictionary<string,object?>();var ranges=new List<object>();FileStream? fs=null;bool claimed=false;var sw=Stopwatch.StartNew();int rc=1;
    try{
      string boot="",outp="";int dev=0,chunk=512,budget=90000,guardEvery=128;string spec="";
      for(int i=0;i+1<a.Length;i+=2)switch(a[i]){case "--boot":boot=a[i+1];break;case "--device":dev=int.Parse(a[i+1]);break;case "--out":outp=a[i+1];break;case "--chunk":chunk=int.Parse(a[i+1]);break;case "--budget-ms":budget=int.Parse(a[i+1]);break;case "--ranges":spec=a[i+1];break;default:throw new ArgumentException(a[i]);}
      Need(chunk>=512&&chunk<=16384&&chunk%512==0,"chunk");Need(budget<=600000,"budget");
      Need(File.ReadAllText("/proc/sys/kernel/random/boot_id").Trim()==boot,"boot changed");Need(Rd("idVendor")=="04e8"&&Rd("idProduct")=="2001","ids");Need(int.Parse(Rd("busnum"))==7&&int.Parse(Rd("devnum"))==dev,"device");Need(Rd("power/runtime_status")=="active","usb not active");
      string drv=Usb+":1.2/driver";if(Directory.Exists(drv))Need(Path.GetFileName(new DirectoryInfo(drv).ResolveLinkTarget(true)?.FullName??"")=="usbfs","interface driver");
      var plan=new List<(string name,uint op,uint addr,long len)>();
      foreach(var e in spec.Split(',',StringSplitOptions.RemoveEmptyEntries)){var p=e.Split(':');
        if(p[0]=="id"){uint id=uint.Parse(p[1]);int n=int.Parse(p[2]);Need(id>=6&&id<=10&&n>0&&n<=16384&&n%16==0,"id range");plan.Add(($"id{id}",1,id,n));}
        else if(p[0]=="st"){uint ad=Convert.ToUInt32(p[1],16);long n=Convert.ToInt64(p[2],16);Need(ad%512==0&&n%512==0&&n>0&&n<=0x4000000&&ad>=0x04f00000u&&ad+n<=0x60000000L,"storage range");plan.Add(($"st:{p[1]}",0x103,ad,n));}
        else if(p[0].StartsWith("45")||p[0].StartsWith("47")){uint ad=Convert.ToUInt32(p[0],16);long n=Convert.ToInt64(p[1],16);Need(ad%4==0&&n>0&&n<=0x20000&&(ad&0xfffe0000u)==(ad&0xff000000u)&&((ad&0xff000000u)==0x45000000u||(ad&0xff000000u)==0x47000000u),"sram range");plan.Add((e,0x101,ad,n));}
        else if(p[0].StartsWith("58")){uint ad=Convert.ToUInt32(p[0],16);long n=Convert.ToInt64(p[1],16);Need(ad%4==0&&n%4==0&&n>0&&((ad>=0x58691000u&&ad+n<=0x586A7800L)||(ad>=0x58602600u&&ad+n<=0x58602800L)||(ad>=0x58622600u&&ad+n<=0x58622800L)||(ad>=0x58700000u&&ad+n<=0x58700900L)||(ad>=0x58650000u&&ad+n<=0x58650200L)),"mmio allowlist");plan.Add((e,0x101,ad,n));}
        else{uint ad=Convert.ToUInt32(p[0],16);long n=Convert.ToInt64(p[1],16);Need(ad>=0x60000000u&&n>0&&ad+n<=0x80000000L&&ad%4==0&&n%chunk==0||ad>=0x60000000u&&n<=chunk&&n>0&&ad+n<=0x80000000L&&ad%4==0,"address outside DDR allowlist");plan.Add((e,0x101,ad,n));}}
      Need(plan.Count>0,"no ranges");fs=new FileStream(outp,FileMode.CreateNew,FileAccess.Write,FileShare.None);
      fd=open($"/dev/bus/usb/007/{dev:D3}",2|0x80000|0x8000);Need(fd>=0,"open errno="+Marshal.GetLastWin32Error());uint itf=2;Need(ioN(fd,Claim,ref itf)==0,"claim errno="+Marshal.GetLastWin32Error());claimed=true;
      var r0=R();o["before"]=r0.ToString();Clean(r0,"before");int since=0;bool stop=false;
      foreach(var q in plan){using var sha=SHA256.Create();long done=0;string head="";long t0=sw.ElapsedMilliseconds;
        while(done<q.len&&!stop){int n=(int)Math.Min(chunk,q.len-done);var b=Read(q.op,q.op==1?q.addr:(uint)(q.addr+done),n);fs.Write(b);sha.TransformBlock(b,0,n,null,0);if(done==0)head=Convert.ToHexString(b,0,Math.Min(64,n)).ToLowerInvariant();done+=n;
          if(q.op==1)break; if(++since>=guardEvery){since=0;Clean(R(),"during");} if(sw.ElapsedMilliseconds>budget){stop=true;o["stopped"]="budget";}}
        sha.TransformFinalBlock(Array.Empty<byte>(),0,0);ranges.Add(new{q.name,op=q.op,addr=$"0x{q.addr:x8}",requested=q.len,read=done,ms=sw.ElapsedMilliseconds-t0,sha256=Convert.ToHexString(sha.Hash!).ToLowerInvariant(),head});if(stop)break;}
      var r1=R();o["after"]=r1.ToString();Clean(r1,"after");rc=stop?2:0;
    }catch(Exception e){o["error"]=e.GetType().Name+": "+e.Message;}
    finally{try{fs?.Dispose();}catch{} if(claimed){uint itf=2;o["released"]=ioN(fd,Release,ref itf)==0;} if(fd>=0)o["closed"]=close(fd)==0;}
    o["ranges"]=ranges;o["bulks"]=bulks;o["ms"]=sw.ElapsedMilliseconds;o["rc"]=rc;var js=JsonSerializer.Serialize(o);try{File.WriteAllText(rcpt,js);}catch{}Console.WriteLine(js);return rc;
  }
}
