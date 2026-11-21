// Read-only external-controller memory dump for the owner's S95F.
// The only OUT traffic is 12-byte read headers (opcode 0x101 direct, or 0x1 with a comp buffer ID). There is no write path in this program.
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
  static void Xfer(bool input,byte[] b){var h=GCHandle.Alloc(b,GCHandleType.Pinned);try{var t=new T{Ep=input?0x82u:0x02u,Len=(uint)b.Length,To=Timeout,Data=h.AddrOfPinnedObject()};int r=ioT(fd,Bulk,ref t);bulks++;Need(r==b.Length,$"bulk {(input?"IN":"OUT")} len={b.Length} r={r} errno={Marshal.GetLastWin32Error()}");}finally{h.Free();}}
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
  static void Claimed(int dev,string boot){Need(File.ReadAllText("/proc/sys/kernel/random/boot_id").Trim()==boot,"boot changed");Need(Rd("idVendor")=="04e8"&&Rd("idProduct")=="2001","ids");Need(int.Parse(Rd("busnum"))==7&&int.Parse(Rd("devnum"))==dev,"device");Need(Rd("power/runtime_status")=="active","usb not active");string drv=Usb+":1.2/driver";if(Directory.Exists(drv))Need(Path.GetFileName(new DirectoryInfo(drv).ResolveLinkTarget(true)?.FullName??"")=="usbfs","interface driver");fd=open($"/dev/bus/usb/007/{dev:D3}",2|0x80000|0x8000);Need(fd>=0,"open");uint itf=2;Need(ioN(fd,Claim,ref itf)==0,"claim");}
  static int Tool(string[] a){var o=new Dictionary<string,object?>();int rc=1;bool c=false;string path=a[1];try{int dev=int.Parse(a[2]);string boot=a[3];Claimed(dev,boot);c=true;var r0=R();o["before"]=r0.ToString();Clean(r0,"before");
    if(a[0]=="--restore"){var log=new List<string>();var items=a[4].Split(',').Select(s=>s.Split(':')).Select(s=>(ad:Convert.ToUInt32(s[0],16),nw:Convert.ToUInt32(s[1],16))).ToList();Need(items.Count<=32,"count");foreach(var i in items){if(IsEnable(i.ad))Need(i.nw<=1,"enable values are 0/1");else{CheckAddr(i.ad);CheckVal(i.nw);}}foreach(var i in items){Write32(i.ad,i.nw);uint v=R32(i.ad);log.Add($"{i.ad:x8}={v:x8}");Need(v==i.nw,$"restore readback {i.ad:x8} {v:x8}");}o["writes"]=log;}
    else if(a[0]=="--poke"){var log=new List<string>();var items=a[4].Split(',').Select(s=>s.Split(':')).Select(s=>(ad:Convert.ToUInt32(s[0],16),old:Convert.ToUInt32(s[1],16),nw:Convert.ToUInt32(s[2],16))).ToList();Need(items.Count<=32,"count");foreach(var i in items){CheckPoke(i.ad,i.old,i.nw);uint v=R32(i.ad);Need(v==i.old,$"precheck {i.ad:x8} has {v:x8}");}if(a.Length>5&&a[5]=="flip")WaitFlip(o);foreach(var i in items){Write32(i.ad,i.nw);uint v=R32(i.ad);log.Add($"{i.ad:x8}:{i.old:x8}->{v:x8}");Need(v==i.nw,$"readback {i.ad:x8} {v:x8}");}o["writes"]=log;}
    else{int n=int.Parse(a[5]),ms=int.Parse(a[6]);var ads=a[4].Split(',').Select(s=>Convert.ToUInt32(s,16)).ToArray();foreach(var ad in ads)Need(ad==0x587005D8u||(ad>=0x450158A8u&&ad<0x45015900u)||(ad>=0x58602600u&&ad<0x58602800u),"watch address");var sw=Stopwatch.StartNew();var rows=new List<string>();string last="";for(int k=0;k<n;k++){var s=string.Join(" ",ads.Select(x=>R32(x).ToString("x8")));if(s!=last){rows.Add($"{sw.ElapsedMilliseconds} {s}");last=s;}System.Threading.Thread.Sleep(ms);}o["changes"]=rows;o["span_ms"]=sw.ElapsedMilliseconds;}
    var r1=R();o["after"]=r1.ToString();Clean(r1,"after");rc=0;}catch(Exception e){o["error"]=e.GetType().Name+": "+e.Message;}finally{if(c){uint itf=2;o["released"]=ioN(fd,Release,ref itf)==0;}if(fd>=0)o["closed"]=close(fd)==0;}o["rc"]=rc;var js=JsonSerializer.Serialize(o);File.WriteAllText(path,js);Console.WriteLine(js);return rc;}
    // --armwait LOG POKES WAIT_S SAMPLE_S: wait (on the TV) for the controller USB device to appear, wait until every OLD value
  // is present (table loaded), require stop=0 fault=0 limit=40 (gate may be 0 during off-sensing), write, read back, then log
  // the sequencer record, R guard, bank selector and the poked words every 50 ms. Same address/value bounds as --poke.
  // s0svc v2 (Claude): SIGTERM = cancel (checked in every loop); after any write, an abnormal exit (cancel,
  // readback mismatch, USB/guard error before the scan power-down stage 0x0011xxxx) restores OLD where the word still reads
  // NEW and logs it; device loss after stage 0x0011 = normal end (rc 3).
  static volatile bool cancel;
  static int Arm(string[] a){var log=new StreamWriter(a[1],true){AutoFlush=true};var sw=Stopwatch.StartNew();void L(string m)=>log.WriteLine($"{DateTime.UtcNow:HH:mm:ss.fff} +{sw.ElapsedMilliseconds} {m}");int rc=1;bool c=false;
    using var term=PosixSignalRegistration.Create(PosixSignal.SIGTERM,ctx=>{ctx.Cancel=true;cancel=true;});var written=new List<(uint ad,uint old,uint nw)>();bool ended=false,inWrite=false;
    static bool Fresh(string f)=>File.Exists(f)&&(DateTime.UtcNow-File.GetLastWriteTimeUtc(f)).TotalSeconds<2.0;
    try{var items=a[2].Split(',').Select(s=>s.Split(':')).Select(s=>(ad:Convert.ToUInt32(s[0],16),old:Convert.ToUInt32(s[1],16),nw:Convert.ToUInt32(s[2],16))).ToList();Need(items.Count<=8,"count");foreach(var i in items)CheckPoke(i.ad,i.old,i.nw);
      long waitMs=long.Parse(a[3])*1000,sampleMs=long.Parse(a[4])*1000;L("armed "+a[2]);
      while(!Directory.Exists(Usb)){Need(!cancel,"cancelled");Need(sw.ElapsedMilliseconds<waitMs,"no controller within wait");System.Threading.Thread.Sleep(50);}
      var t0=sw.ElapsedMilliseconds;L("usb present");Need(Fresh(a[1]+".standby"),"TV not in standby (flag missing or stale)");int dev=0;
      while(true){try{if(Rd("idVendor")=="04e8"&&Rd("idProduct")=="2001"&&Rd("power/runtime_status")=="active"){dev=int.Parse(Rd("devnum"));Need(int.Parse(Rd("busnum"))==7,"bus");string drv=Usb+":1.2/driver";bool ok=!Directory.Exists(drv)||Path.GetFileName(new DirectoryInfo(drv).ResolveLinkTarget(true)?.FullName??"")=="usbfs";if(ok){fd=open($"/dev/bus/usb/007/{dev:D3}",2|0x80000|0x8000);if(fd>=0){uint itf=2;if(ioN(fd,Claim,ref itf)==0){c=true;break;}close(fd);fd=-1;}}}}catch(IOException){}catch(UnauthorizedAccessException){}
        Need(!cancel,"cancelled");Need(sw.ElapsedMilliseconds-t0<20000,"claim timeout");System.Threading.Thread.Sleep(20);}
      L($"claimed dev {dev}");string lastPre="";
      while(true){var r=R();var vals=items.Select(i=>R32(i.ad)).ToArray();string pre=$"R {r} vals "+string.Join(",",vals.Select(v=>v.ToString("x8")));if(pre!=lastPre){L(pre);lastPre=pre;}
        bool loaded=items.Select((i,k)=>vals[k]==i.old).All(x=>x);if(loaded&&r.s==0&&r.f==0&&r.l==40)break;
        Need(!cancel,"cancelled");Need(sw.ElapsedMilliseconds-t0<30000,"table not loaded / guard not ok within 30 s");System.Threading.Thread.Sleep(5);}
      Need(Fresh(a[1]+".standby"),"TV left standby before write");foreach(var i in items){Need(!cancel,"cancelled");written.Add(i);inWrite=true;Write32(i.ad,i.nw);inWrite=false;uint v=R32(i.ad);L($"write {i.ad:x8}:{i.old:x8}->{v:x8}");Need(v==i.nw,"readback");}
      var t1=sw.ElapsedMilliseconds;string last="";
      while(sw.ElapsedMilliseconds-t1<sampleMs){Need(!cancel,"cancelled");var r=R();uint rec=R32(0x450158A8u);if((rec>>16)==0x0011u)ended=true;string s=$"rec {rec:x8} {R32(0x450158ACu):x8} sel {R32(0x587005D8u):x8} R {r} pk "+string.Join(",",items.Select(i=>R32(i.ad).ToString("x8")));if(s!=last){L(s);last=s;}System.Threading.Thread.Sleep(50);}
      if(!ended||Directory.Exists(Usb))throw new InvalidOperationException(ended?"sampling ended with the controller still up":"sampling ended before the scan power-down stage");
      rc=0;L("done");}
    catch(Exception e){L("stop: "+e.GetType().Name+": "+e.Message);
      bool gone=false;if(written.Count>0&&ended&&!cancel){for(int k=0;k<40&&!gone;k++){gone=!Directory.Exists(Usb);if(!gone)System.Threading.Thread.Sleep(50);}}
      if(written.Count>0&&ended&&!cancel&&gone){rc=3;L("normal end: controller powered down after the scan");}
      else if(inWrite){L("write transfer failed: no further traffic (no restore attempt)");}
      else if(written.Count>0&&c){foreach(var i in written){try{uint v=R32(i.ad);if(v==i.nw){Write32(i.ad,i.old);uint v2=R32(i.ad);L($"restore {i.ad:x8}:{i.nw:x8}->{v2:x8}"+(v2==i.old?" ok":" MISMATCH"));}else L($"restore skip {i.ad:x8} reads {v:x8}");}catch(Exception e2){L($"restore failed {i.ad:x8}: {e2.GetType().Name}: {e2.Message}");}}}
      else if(written.Count>0)L("restore impossible: not claimed");}
    finally{if(c){uint itf=2;try{ioN(fd,Release,ref itf);}catch{}}if(fd>=0)close(fd);L($"exit rc={rc}");log.Dispose();}return rc;}
  static int Main(string[] a){
    if(a.Length==5&&a[0]=="--armwait")return Arm(a);
    if(a.Length>=5&&(a[0]=="--poke"||a[0]=="--watch"||a[0]=="--restore"))return Tool(a);
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
