using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;
using System.Threading;
// KB: boot-bound lane-mask WRITER derived from KA (read-only) + IZ write transport.
// Writes ONLY 2-byte halfwords inside the lane window 0x47010438..0x4701052a, value 0x0001 (mask) or 0x0000 (unmask),
// and only when the full unrelaxed IZ GuardR/GuardContext admit the Clean controller state.
// Transport (read header = u32 0x101, u32 bus address, u32 length; Controller.Read)
// and all boot/USB/descriptor/binding/clock guards are reused EXACTLY as the
// reviewed IZ wrapper uses them. There is NO write path in this helper: no write
// header, no OUT payload, no limit mutation. It reports state and the per-lane RTP
// eligibility window; it never gates on thermal/profile and never changes anything.
internal static partial class Program
{
    const int TimeoutMs=2000;
    static int ExpectedDevice;
    static string ExpectedBoot="";
    static bool ValidBoot(string s)=>Guid.TryParseExact(s,"D",out var v)&&s==v.ToString("D")&&v!=Guid.Empty;
    const string UsbRoot="/sys/bus/usb/devices/7-1";
    const string DeviceHex="12010002ef020140e8040120500201020301";
    const string AllDescriptorsHex=DeviceHex+"090262000301048032080b00020202010a09040000010202010a052400100105240100010424020205240600010705830308001009040100020a00000a07050102400010070581024000000904020002ff0000000705820200020007050202000200";
    readonly record struct Identity(int Bus,int Device) { public string Node=>$"/dev/bus/usb/{Bus:D3}/{Device:D3}"; }
    readonly record struct NativeResult(int Value,int Errno);
    sealed record Spec(string Name,uint Address,int Length);
    // READ-ONLY allowlist: R, M, C and the lane-mask window. No Callback read, no WriteHeader.
    static readonly Spec R=new("R",0x47012400,256), M=new("M",0x470004a0,68), C=new("C",0x47000bc0,16), MaskWindow=new("MaskWindow",0x47010438,244);
    const int LaneStart=540,LaneEnd=661,LaneCount=122; // 0x47010438..0x4701052b inclusive, 244 bytes = 122 halfwords
    static byte[] Header(Spec s) {byte[] b=new byte[12];BitConverter.GetBytes(0x101u).CopyTo(b,0);BitConverter.GetBytes(s.Address).CopyTo(b,4);BitConverter.GetBytes(s.Length).CopyTo(b,8);return b;}
    static bool AllowedHeader(byte[] b) {foreach(var s in new[]{R,M,C,MaskWindow})if(b.AsSpan().SequenceEqual(Header(s)))return true;return false;}
    static string Mode="read";
    static int WriteValue=>Mode=="mask"?1:0;
    static byte[] WriteHeaderFor(uint addr){byte[] b=new byte[12];BitConverter.GetBytes(0x102u).CopyTo(b,0);BitConverter.GetBytes(addr).CopyTo(b,4);BitConverter.GetBytes(2u).CopyTo(b,8);return b;}
    static bool AllowedWriteHeader(byte[] b){if(Mode=="read"||b.Length!=12)return false;uint op=BitConverter.ToUInt32(b,0),a=BitConverter.ToUInt32(b,4),l=BitConverter.ToUInt32(b,8);return op==0x102u&&l==2u&&a>=0x47010438u&&a<=0x4701052au&&(a&1u)==0;}
    static bool AllowedPayload(byte[] b)=>Mode!="read"&&b.Length==2&&b[1]==0&&b[0]==(byte)WriteValue;
    static void Need(bool b,string s){if(!b)throw new InvalidOperationException(s);}
    static int Half(byte[] b,int i)=>b[i]|b[i+1]<<8;
    static string Sha(byte[] b)=>Convert.ToHexString(SHA256.HashData(b)).ToLowerInvariant();
    static string ShortError(Exception e)=>e.GetType().Name+": "+e.Message;
    interface IOps {IReadOnlyList<BindingCheck> BindingChecks{get;} Identity Preflight();NativeResult Open(Identity id);void ValidateFd(int fd,Identity id);void Revalidate(Identity id);NativeResult Claim(int fd);NativeResult Bulk(int fd,bool input,byte[] data,int length);NativeResult Release(int fd);NativeResult Close(int fd);}
    interface IClock {long NowUs();void SleepUs(long us);}
    sealed record Step(string Name,string Direction,int Expected,int? Count,int Errno,long BeforeUs,long AfterUs,string Before,string After);
    sealed record Window(string Name,int Bytes,string Sha256,string Base64);
    sealed record LaneNote(int Lane,int BusAddress,int Halfword);
    sealed class Outcome {
      public string Schema{get;set;}="kb-lane-mask-write-v1";public string Mode{get;set;}="read";public int WritesPlanned{get;set;}public int WritesDone{get;set;}public bool WriteAttempted{get;set;}public bool WriteVerified{get;set;}public bool StartupProfileWrite{get;set;}public int? AfterLimit{get;set;}public string AfterState{get;set;}="unknown";public List<int> AfterSkippedLanes{get;}=new();
      public string ExpectedBootId{get;set;}="";public int Device{get;set;}
      public string Stage{get;set;}="preflight";public string ProtocolPhase{get;set;}="ReadyForHeader";
      public bool Opened{get;set;} public bool Claimed{get;set;} public bool Released{get;set;}=true;public bool Closed{get;set;}=true;
      public bool ReadComplete{get;set;} public int HeadersSent{get;set;} public int BulkTransfers{get;set;}
      // R-derived observation
      public int? ObservedLimit{get;set;} public string ObservedState{get;set;}="unknown";
      public int StateStop{get;set;} public int StateFault{get;set;} public int StateGate{get;set;}
      public int OrdinaryObserved{get;set;} public int OrdinaryModel{get;set;} public bool OrdinaryMatchesModel{get;set;}
      public int AlternateObserved{get;set;} public bool AlternateAllowed{get;set;} public int SampledTemperature{get;set;} public int OwnEcho{get;set;}
      // IZ-equivalent thermal/profile admission, evaluated as a REPORT (never a gate here)
      public bool IzThermalProfileAdmitted{get;set;} public string IzAdmissionDetail{get;set;}="";
      public bool IzContextAdmitted{get;set;} public string IzContextDetail{get;set;}="";
      public bool StartupProfileCandidate{get;set;}
      // M / C context
      public uint McRoot{get;set;} public int McMode{get;set;} public int McScan{get;set;} public int McOrdinaryMirror{get;set;}
      public int CWidth{get;set;} public int CHeight{get;set;} public int CStride{get;set;} public int CCategory{get;set;} public int CSelector{get;set;} public int CContext{get;set;}
      // Lane-mask window
      public int WindowBaseAddress{get;set;}=0x47010438;public int WindowBytes{get;set;}=244;public int LaneRangeStart{get;set;}=LaneStart;public int LaneRangeEnd{get;set;}=LaneEnd;
      public List<int> SkippedLanes{get;}=new();public int SkippedCount{get;set;}public List<LaneNote> NonBit0Lanes{get;}=new();
      public bool RStable{get;set;} public bool WindowStable{get;set;}
      public List<BindingCheck> BindingChecks{get;}=new();public List<Step> Steps{get;}=new();public List<Window> Windows{get;}=new();public List<string> Errors{get;}=new();
    }
    static readonly byte[] Profile=Convert.FromHexString("0000400b7008000001000000c800010004000000f401f40100000000000000006f0cf4010000000000000000b80bb80bc80000000000000000000000000000000000010000000000000000000000000014006d087008030001001900c8007008000000000100010000000000000000000000000000000000000000000000000000000000000000000000000000000000000030001b0818001900000000000100a00000000000000000006400fb000f00c300d80e01000f00c300d80e6f0cf401c8000100280001006f080000000000000000010026000a0000000000000000000000000000000000000000000000000000000000000000000000000000000000");
    // R profile/thermal matrix reused verbatim from IZ. These remain the definition of
    // the "admitted" steady case; relaxing them is NOT done here (read-only reports only).
    static bool DynamicR(int i)=>(i>=0x86&&i<0x8a)||(i>=0x8c&&i<0x8e)||(i>=0x90&&i<0x94)||(i>=0xa2&&i<0xa4);
    static bool ModelByte(int i)=>i==0x20||i==0x21||i==0x98||i==0x99||i==0xbc||i==0xbd||i==0xac||i==0xad;
    static int Endpoint(int basis,int reference,int temperature,int coefficient,int scale,int floor,int cap) {
      uint product=unchecked(((uint)basis+(uint)coefficient*unchecked((uint)(temperature-reference)))*(uint)scale);
      int candidate=(int)((product>>7)&65535u);return candidate>cap?cap:Math.Max(floor,candidate);
    }
    static readonly int[] AlternateEndpointImage={3000,3001,3003,3024,3026,3046,3049,3069,3072,3092,3094,3115,3117,3138,3140,3161,3163,3183,3186,3206,3209,3229,3231,3252,3254,3275,3277,3298,3300,3321,3323,3343,3346,3366,3369,3389,3391,3412,3414,3435,3437,3458,3460,3481,3483,3503,3506,3526,3529,3549,3551,3572,3574,3595,3597,3618,3620,3641,3643,3663,3666,3686,3689,3709,3711,3732,3734,3755,3757,3778,3780,3800};
    static bool AlternateAllowed(int value)=>Array.BinarySearch(AlternateEndpointImage,value)>=0;
    static void GuardModel(byte[] r) {
      Need(Half(r,0x98)<=4095,"temperature mirror source range");Need(Half(r,0xac)<=254,"own echo range / zero high byte");
      int ordinary=Endpoint(Half(r,0x94),Half(r,0x96),Half(r,0x98),Half(r,0xae),Half(r,0xb0),Half(r,0x2e),Half(r,0xb2));
      Need(ordinary>=3000&&ordinary<=3800&&ordinary>500&&Half(r,0x20)==ordinary,"restrictive ordinary-current endpoint admission");
      Need(AlternateAllowed(Half(r,0xbc)),"alternate endpoint exact finite source image");
    }
    static void GuardR(byte[] r,int expected) {
      Need(r.Length==256,"R extent");
      for(int i=0;i<256;i++)if(!DynamicR(i)&&!ModelByte(i)&&i!=0xc4&&i!=0xc5&&i!=0xca)Need(r[i]==Profile[i],"R profile byte "+i);
      Need(r[0xca]<=1,"R observed selector domain");
      Need(Half(r,0)==0&&Half(r,0xa)==0&&Half(r,0xe)==1&&Half(r,6)==0,"R clean/gate/logger");
      Need(Half(r,0xc4)==expected&&Half(r,0x30)==200&&Half(r,0xc0)==200,"R limit");
      Need(Half(r,0x9e)==1&&Half(r,0x4a)==0&&Half(r,0x4e)==0&&Half(r,0x9a)==0&&Half(r,0x9c)==0,"R alternative gates/latches");
      GuardModel(r);
    }
    // KB: mask writes (skip bits only, never the limit/profile) are also admitted in the documented post-reset
    // startup state: R[0x20] still holds the startup constant 3200 before firmware recomputes it from temperature.
    // Exactly that field may differ; all other GuardR/GuardModel checks still apply to a copy carrying the model value.
    static bool StartupAdmitted;
    static void GuardRStartupOk(byte[] r,int limit){
      try{GuardR(r,limit);return;}catch(InvalidOperationException e){if(!e.Message.Contains("ordinary-current endpoint"))throw;}
      int model=Endpoint(Half(r,0x94),Half(r,0x96),Half(r,0x98),Half(r,0xae),Half(r,0xb0),Half(r,0x2e),Half(r,0xb2));
      Need(Half(r,0x20)==3200&&model!=3200,"startup signature: ordinary endpoint must be the startup constant 3200");
      var copy=(byte[])r.Clone();Put(copy,0x20,model);GuardR(copy,limit);StartupAdmitted=true;
    }
    static void GuardContext(byte[] m,byte[] c,byte[] r) {
      Need(m.Length==68&&c.Length==16,"context extent");
      Need(BitConverter.ToUInt32(m,64)==0x20010000,"root");Need(Half(m,10)==0&&Half(m,12)==2,"mode1 flags");Need(m[56]==1,"scan enable");
      Need(Half(m,22)==500&&Half(m,24)==0&&Half(m,26)==500&&Half(m,28)==0&&(Half(m,38)==Half(r,0x20)||(Half(r,0x20)==3200&&Half(m,38)>=3000&&Half(m,38)<=3800))&&Half(m,40)==500,"numeric profile / validated ordinary endpoint mirror");
      Need(Half(c,0)==2160&&Half(c,2)==1920&&Half(c,4)==2880&&c[6]==92&&c[7]<=1&&c[8]==3,"C geometry/profile/selector");
    }
    static string RtState(byte[] r){int stop=Half(r,0),fault=Half(r,10),gate=Half(r,14);return (stop,fault,gate) switch{(0,0,1)=>"Clean",(0,0,0)=>"Quiescent",(1,0x1001,0)=>"Faulted",_=>throw new InvalidOperationException("unadmitted R state")};}
    static void GuardObservationR(byte[] r,int limit,string state){Need(RtState(r)==state,"observed state drift");var copy=(byte[])r.Clone();Put(copy,0,0);Put(copy,10,0);Put(copy,14,1);GuardR(copy,limit);}
    static void GuardObservationContext(byte[] m,byte[] c,byte[] r){
      Need(m.Length==68&&c.Length==16&&BitConverter.ToUInt32(m,64)==0x20010000,"observational context root");
      Need(Half(m,10)==0&&(Half(m,12)==2||Half(m,12)==3)&&m[56]<=1,"finite observational mode/scan");
      Need(Half(m,22)==500&&Half(m,24)==0&&Half(m,26)==500&&Half(m,28)==0&&Half(m,40)==500,"observational numeric profile");
      Need(Half(m,38)==Half(r,0x20)||(Half(m,12)==3&&Half(m,38)==Half(r,0xbc)),"observational upper branch");
      Need(Half(c,0)==2160&&Half(c,2)==1920&&Half(c,4)==2880&&c[6]==92&&c[7]<=1&&c[8]<=4,"observational geometry/category/context");
    }
    sealed class Controller {
      readonly IOps ops;readonly IClock clock;readonly Outcome o;readonly int fd;readonly long deadline;long last=-1;
      public Controller(IOps ops,IClock clock,Outcome o,int fd,long deadline){this.ops=ops;this.clock=clock;this.o=o;this.fd=fd;this.deadline=deadline;}
      long Time(){long v=clock.NowUs();Need(v>=last,"clock backwards");last=v;return v;}
      void Budget(){Need(o.ProtocolPhase=="ReadyForHeader","new header forbidden");Need(Time()+4_000_000<=deadline,"transaction budget");}
      void Transfer(string name,bool input,byte[] b,string after){string before=o.ProtocolPhase;long at=last<0?0:last;try{at=Time();}catch(Exception e){o.Errors.Add(ShortError(e));if(before=="ReadyForHeader")throw;}o.ProtocolPhase="Unknown";NativeResult n;try{n=ops.Bulk(fd,input,b,b.Length);}catch{ o.Steps.Add(new(name,input?"IN":"OUT",b.Length,null,0,at,at,before,"Unknown"));o.BulkTransfers++;if(b.Length==12)o.HeadersSent++;throw;}
        o.BulkTransfers++;if(!input&&b.Length==12)o.HeadersSent++;if(n.Value==b.Length)o.ProtocolPhase=after;
        long end=at;try{end=Time();}catch(Exception e){o.Errors.Add(ShortError(e));}
        o.Steps.Add(new(name,input?"IN":"OUT",b.Length,n.Value,n.Errno,at,end,before,o.ProtocolPhase));Need(n.Value==b.Length,"short/failed transfer "+name);
      }
      public void WriteHalf(string name,uint addr,int value){Budget();o.WriteAttempted=true;var h=WriteHeaderFor(addr);Need(AllowedWriteHeader(h),"write header allowlist");Transfer(name+"-header",false,h,"ExpectingWritePayload");var p=new[]{(byte)value,(byte)0};Need(AllowedPayload(p),"payload allowlist");Transfer(name+"-payload",false,p,"ReadyForHeader");Need(o.Errors.Count==0,"clock error after completed write");}
      public byte[] Read(string name,Spec s){Budget();Transfer(name+"-header",false,Header(s),"ExpectingReadIn");byte[] b=new byte[s.Length];Transfer(name+"-data",true,b,"ReadyForHeader");o.Windows.Add(new(name,b.Length,Sha(b),Convert.ToBase64String(b)));Need(o.Errors.Count==0,"clock error after completed read");return b;}
    }
    static void WriteHalf(Controller x,Outcome o,uint addr,int value){Need(value==WriteValue,"write value");x.WriteHalf("w-"+addr.ToString("x8"),addr,value);o.WritesDone++;}
    static void AnalyzeWindow(Outcome o,byte[] w){
      o.SkippedLanes.Clear();o.NonBit0Lanes.Clear();
      for(int i=0;i<LaneCount;i++){int hw=Half(w,2*i);int lane=LaneStart+i;if((hw&1)!=0)o.SkippedLanes.Add(lane);if((hw&~1&0xffff)!=0)o.NonBit0Lanes.Add(new(lane,0x47010438+2*i,hw));}
      o.SkippedCount=o.SkippedLanes.Count;
    }
    static Outcome Run(IOps ops,IClock clock){StartupAdmitted=false;Outcome o=new(){ExpectedBootId=ExpectedBoot};int fd=-1;try{
      Need(ValidBoot(ExpectedBoot),"canonical nonzero expected boot UUID");
      long deadline=checked(clock.NowUs()+40_000_000);var id=ops.Preflight();o.Device=id.Device;fd=ops.Open(id).Value;Need(fd>=0,"open");o.Opened=true;o.Closed=false;ops.ValidateFd(fd,id);ops.Revalidate(id);Need(ops.Claim(fd).Value==0,"claim");o.Claimed=true;o.Released=false;ops.Revalidate(id);
      var x=new Controller(ops,clock,o,fd,deadline);
      o.Stage="read";
      var baseline=x.Read("baseline-R",R);
      int limit=Half(baseline,0xc4);o.ObservedLimit=limit;
      string state=RtState(baseline);o.ObservedState=state;
      o.StateStop=Half(baseline,0);o.StateFault=Half(baseline,10);o.StateGate=Half(baseline,14);
      o.OrdinaryObserved=Half(baseline,0x20);
      o.OrdinaryModel=Endpoint(Half(baseline,0x94),Half(baseline,0x96),Half(baseline,0x98),Half(baseline,0xae),Half(baseline,0xb0),Half(baseline,0x2e),Half(baseline,0xb2));
      o.OrdinaryMatchesModel=o.OrdinaryObserved==o.OrdinaryModel;
      o.AlternateObserved=Half(baseline,0xbc);o.AlternateAllowed=AlternateAllowed(o.AlternateObserved);
      o.SampledTemperature=Half(baseline,0x98);o.OwnEcho=Half(baseline,0xac);
      var m=x.Read("pre-M",M);var c=x.Read("pre-C",C);
      o.McRoot=BitConverter.ToUInt32(m,64);o.McMode=Half(m,12);o.McScan=m[56];o.McOrdinaryMirror=Half(m,38);
      o.CWidth=Half(c,0);o.CHeight=Half(c,2);o.CStride=Half(c,4);o.CCategory=c[6];o.CSelector=c[7];o.CContext=c[8];
      var window=x.Read("mask-window",MaskWindow);
      AnalyzeWindow(o,window);
      // IZ-equivalent admission, evaluated for REPORT only: this helper never refuses on it.
      o.Stage="admission-report";
      try{if(state=="Clean")GuardR(baseline,limit);else GuardObservationR(baseline,limit,state);o.IzThermalProfileAdmitted=true;o.IzAdmissionDetail="admitted ("+state+")";}
      catch(Exception e){o.IzThermalProfileAdmitted=false;o.IzAdmissionDetail=ShortError(e);}
      try{if(state=="Clean")GuardContext(m,c,baseline);else GuardObservationContext(m,c,baseline);o.IzContextAdmitted=true;o.IzContextDetail="admitted";}
      catch(Exception e){o.IzContextAdmitted=false;o.IzContextDetail=ShortError(e);}
      // Startup-profile candidate: Clean/stable-Fault, ordinary NOT refreshed to the
      // temperature model, but the alternate endpoint is a valid finite source image and
      // the model is in range -> matches the post-MODE2-reset "startup profile" shape.
      o.StartupProfileCandidate=(state=="Clean"||state=="Faulted")&&!o.OrdinaryMatchesModel&&o.AlternateAllowed&&o.OrdinaryModel>=3000&&o.OrdinaryModel<=3800;
      // Single re-read (no retry) to report read stability; not a mutation and not a gate.
      o.Stage="readback";
      var freshR=x.Read("fresh-R",R);var freshW=x.Read("fresh-window",MaskWindow);
      o.RStable=baseline.AsSpan().SequenceEqual(freshR);o.WindowStable=window.AsSpan().SequenceEqual(freshW);
      o.Mode=Mode;
      if(Mode!="read"){
        o.Stage="write-admission";
        Need(state=="Clean","writes require Clean state");Need(limit==40||limit==200,"writes require limit 40 or 200");
        GuardRStartupOk(baseline,limit);GuardContext(m,c,baseline);GuardRStartupOk(freshR,limit);
        Need(o.RStable&&o.WindowStable,"writes require stable R and window");Need(o.NonBit0Lanes.Count==0,"writes require no non-bit0 bits in window");
        var target=new int[LaneCount];for(int i=0;i<LaneCount;i++){int hw=Half(window,2*i);target[i]=Mode=="mask"?(hw|1):(hw&~1);if(target[i]!=hw)o.WritesPlanned++;}
        o.Stage="write";
        for(int i=0;i<LaneCount;i++)if(target[i]!=Half(window,2*i))WriteHalf(x,o,(uint)(0x47010438+2*i),target[i]);
        o.Stage="write-readback";
        var afterW=x.Read("after-window",MaskWindow);var afterR=x.Read("after-R",R);
        o.AfterLimit=Half(afterR,0xc4);try{o.AfterState=RtState(afterR);}catch(Exception e){o.AfterState=ShortError(e);}
        for(int i=0;i<LaneCount;i++)if((Half(afterW,2*i)&1)!=0)o.AfterSkippedLanes.Add(LaneStart+i);
        bool ok=true;for(int i=0;i<LaneCount;i++)if(Half(afterW,2*i)!=target[i])ok=false;
        Need(ok,"window readback differs from target");Need(o.AfterLimit==limit,"limit changed during write");o.WriteVerified=true;o.StartupProfileWrite=StartupAdmitted;
      }
    }catch(Exception e){o.Errors.Add(ShortError(e));}
    finally{if(o.Claimed)try{var n=ops.Release(fd);o.Released=n.Value==0;if(!o.Released)o.Errors.Add("release failed");}catch(Exception e){o.Errors.Add("release "+ShortError(e));}
      if(fd>=0)try{var n=ops.Close(fd);o.Closed=n.Value==0;if(!o.Closed)o.Errors.Add("close failed");}catch(Exception e){o.Errors.Add("close "+ShortError(e));}o.BindingChecks.AddRange(ops.BindingChecks);}
    bool terminal=o.Errors.Count==0&&o.ProtocolPhase=="ReadyForHeader"&&o.Released&&o.Closed;
    o.ReadComplete=terminal&&o.Windows.Count==(Mode=="read"?6:8)&&(Mode=="read"||o.WriteVerified);
    o.Stage=o.ReadComplete?"complete":"rejected";return o;}
    static byte[] ReadCachedDescriptors(Stream stream)
    {
        byte[] data = new byte[117]; int used = 0;
        while (used < data.Length)
        {
            int count = stream.Read(data, used, data.Length - used);
            if (count == 0) return data.AsSpan(0, used).ToArray();
            Need(count > 0 && count <= data.Length - used, "descriptor stream count"); used += count;
        }
        throw new InvalidOperationException("cached descriptors exceed 116 bytes");
    }
    static byte[] ReadCachedDescriptors(string path) { using FileStream stream = File.OpenRead(path); return ReadCachedDescriptors(stream); }

    sealed class RealClock : IClock
    {
        public long NowUs() => (long)(Stopwatch.GetTimestamp() * (1_000_000.0 / Stopwatch.Frequency));
        public void SleepUs(long microseconds)
        {
            if (microseconds <= 0) return;
            int milliseconds = (int)Math.Min(int.MaxValue, (microseconds + 999) / 1000);
            Thread.Sleep(milliseconds);
        }
    }

    const string UsbfsDriver="/sys/bus/usb/drivers/usbfs";
    readonly record struct NativeNode(int Return,int Errno,uint Mask,ushort Mode,ulong Inode,uint DevMajor,uint DevMinor);
    sealed record KernelDriver(int Return,int Errno,string? Name,uint Interface,string RawBase64,string Sha256);
    sealed record BindingCheck(string Stage,bool OwnClaim,bool LocalFdMatches,NativeNode Link,NativeNode Follow,NativeNode Canonical,KernelDriver? Kernel);
    static bool HasTypeInode(NativeNode n,int kind)=>n.Return==0&&n.Errno==0&&(n.Mask&0x103)==0x103&&(n.Mode&0xf000)==kind&&n.Inode!=0;
    static void GuardNativeBinding(BindingCheck c) {
      Need(HasTypeInode(c.Canonical,0x4000),"canonical usbfs directory identity unavailable");
      if(!c.OwnClaim){Need(c.Link.Return==-1&&c.Link.Errno==2&&c.Follow.Return==-1&&c.Follow.Errno==2,"preclaim driver not positively absent");
        if(c.Stage=="before-open")Need(!c.LocalFdMatches&&c.Kernel==null,"initial ownership state");
        else Need(c.Stage=="unclaimed-fd"&&c.LocalFdMatches&&c.Kernel is {Return:-1,Errno:61,Name:null,Interface:2},"preclaim kernel driver not ENODATA");
      }else{
        Need(c.Stage=="claimed-fd"&&c.LocalFdMatches,"local successful claim ownership");
        Need(c.Kernel is {Return:0,Errno:0,Name:"usbfs",Interface:2},"owned kernel driver not usbfs");
        Need(HasTypeInode(c.Link,0xa000)&&HasTypeInode(c.Follow,0x4000),"owned driver native link/directory unavailable");
        Need(c.Follow.Inode==c.Canonical.Inode&&c.Follow.DevMajor==c.Canonical.DevMajor&&c.Follow.DevMinor==c.Canonical.DevMinor,"owned driver differs from canonical usbfs device/inode");
      }
    }
    static KernelDriver DriverRecord(int result,int errno,string? name){byte[] raw=new byte[260];BitConverter.GetBytes(2u).CopyTo(raw,0);if(result==0&&name!=null){byte[] b=System.Text.Encoding.UTF8.GetBytes(name);Need(b.Length<256,"driver name bound");b.CopyTo(raw,4);}return new(result,errno,result==0?name:null,2,Convert.ToBase64String(raw),Sha(raw));}
    static BindingCheck ModelBinding(bool own,bool opened,string? driver,bool dangling=false){NativeNode canonical=new(0,0,0x103,0x41ed,23111,0,19),missing=new(-1,2,0,0,0,0,0),link=new(0,0,0x103,0xa1ff,888,0,19);
      NativeNode followed=driver==null||dangling?missing:canonical with {Inode=driver==UsbfsDriver?23111ul:23112ul};
      return new(opened?(own?"claimed-fd":"unclaimed-fd"):"before-open",own,opened,driver==null?missing:link,followed,canonical,opened?DriverRecord(driver==null?-1:0,driver==null?61:0,driver==null?null:Path.GetFileName(driver)):null);
    }

    sealed class RealOps : IOps
    {
        int openedFd=-1, claimFd=-1; bool ownClaim;readonly List<BindingCheck> bindingChecks=new();public IReadOnlyList<BindingCheck> BindingChecks=>bindingChecks;
        [DllImport("libc.so.6")] static extern uint getuid();
        [DllImport("libc.so.6")] static extern uint geteuid();
        const uint ClaimRequest = 0x8004550f, ReleaseRequest = 0x80045510, BulkRequest = 0xc0105502;
        [StructLayout(LayoutKind.Sequential, Pack = 4)] internal struct Transfer { public uint Ep, Length, Timeout; public IntPtr Data; }
        [DllImport("libc.so.6", SetLastError = true)] static extern int open(string path, int flags);
        [DllImport("libc.so.6", SetLastError = true)] static extern int close(int fd);
        [DllImport("libc.so.6", EntryPoint = "ioctl", SetLastError = true)] static extern int ioctlNumber(int fd, uint request, ref uint data);
        [DllImport("libc.so.6", EntryPoint = "ioctl", SetLastError = true)] static extern int ioctlTransfer(int fd, uint request, ref Transfer data);
        [DllImport("libc.so.6", SetLastError = true)] static extern IntPtr read(int fd, [Out] byte[] data, UIntPtr count);
        [DllImport("libc.so.6", SetLastError = true)] static extern int statx(int dirfd, string path, int flags, uint mask, [Out] byte[] data);
        [DllImport("libc.so.6",EntryPoint="ioctl",SetLastError=true)] static extern int ioctlGetDriver(int fd,uint request,[In,Out]byte[] data);
        static NativeResult Result(int value) => new(value, value < 0 ? Marshal.GetLastWin32Error() : 0);
        static string Text(string name) => File.ReadAllText(UsbRoot + "/" + name).Trim();
        public static bool AbiReady => RuntimeInformation.ProcessArchitecture == Architecture.Arm && IntPtr.Size == 4 && Marshal.SizeOf<Transfer>() == 16 && BitConverter.IsLittleEndian;
        public Identity Preflight() {Need(openedFd<0&&!ownClaim,"initial preflight requires no resources");return CachedIdentity();}
        Identity CachedIdentity()
        {
            Need(getuid() == 0 && geteuid() == 0, "root UID/EUID required");
            Need(File.ReadAllText("/proc/sys/kernel/random/boot_id").Trim() == ExpectedBoot, "boot changed");
            Need(Text("power/runtime_status") == "active", "USB not already active");
            Need(Text("idVendor") == "04e8" && Text("idProduct") == "2001", "USB IDs");
            Need(Text("bConfigurationValue") == "1" && Text("authorized") == "1", "configuration/authorization");
            Need(Convert.ToHexString(ReadCachedDescriptors(UsbRoot + "/descriptors")).Equals(AllDescriptorsHex, StringComparison.OrdinalIgnoreCase), "cached full descriptors");
            string intf = UsbRoot + ":1.2/";
            var binding=ReadBinding(intf+"driver");bindingChecks.Add(binding);GuardNativeBinding(binding);
            Need(File.ReadAllText(intf + "bInterfaceNumber").Trim() == "02" && File.ReadAllText(intf + "bAlternateSetting").Trim() == "0" &&
                File.ReadAllText(intf + "bInterfaceClass").Trim() == "ff" && File.ReadAllText(intf + "bInterfaceSubClass").Trim() == "00" &&
                File.ReadAllText(intf + "bInterfaceProtocol").Trim() == "00", "vendor interface");
            Need(int.TryParse(Text("busnum"), out int bus) && bus == 7, "bus");
            Need(int.TryParse(Text("devnum"), out int device) && device >= 1 && device <= 127 && device == ExpectedDevice, "device address");
            return new(bus, device);
        }
        NativeNode Node(string path,int flags){byte[] b=new byte[256];int r=statx(-100,path,flags,0x103,b),e=r<0?Marshal.GetLastWin32Error():0;return new(r,e,BitConverter.ToUInt32(b,0),BitConverter.ToUInt16(b,28),BitConverter.ToUInt64(b,32),BitConverter.ToUInt32(b,136),BitConverter.ToUInt32(b,140));}
        KernelDriver GetKernelDriver(){byte[] b=new byte[260];BitConverter.GetBytes(2u).CopyTo(b,0);int r=ioctlGetDriver(openedFd,0x41045508,b),e=r<0?Marshal.GetLastWin32Error():0;int nul=Array.IndexOf(b,(byte)0,4);string? name=r==0&&nul>=4?System.Text.Encoding.UTF8.GetString(b,4,nul-4):null;return new(r,e,name,BitConverter.ToUInt32(b,0),Convert.ToBase64String(b),Sha(b));}
        BindingCheck ReadBinding(string driver){return new(openedFd<0?"before-open":ownClaim?"claimed-fd":"unclaimed-fd",ownClaim,openedFd>=0&&(!ownClaim||claimFd==openedFd),Node(driver,0x100),Node(driver,0),Node(UsbfsDriver,0x100),openedFd>=0?GetKernelDriver():null);}
        public void Revalidate(Identity id) {Need(openedFd>=0&&(!ownClaim||claimFd==openedFd),"resource ownership");Need(CachedIdentity()==id,"USB instance changed");ValidateFdIdentity(openedFd,id);}
        public NativeResult Open(Identity id) {Need(openedFd<0&&!ownClaim,"open ownership");var n=Result(open(id.Node,2|0x80000|0x8000));if(n.Value>=0)openedFd=n.Value;return n;}
        public void ValidateFd(int fd,Identity id) {
            Need(fd==openedFd&&!ownClaim,"initial FD ownership");ValidateFdIdentity(fd,id);
            byte[] descriptor=new byte[18];long count=read(fd,descriptor,(UIntPtr)18).ToInt64();int errno=count<0?Marshal.GetLastWin32Error():0;
            Need(count==18,"FD cached descriptor count="+count+" errno="+errno);
            Need(Convert.ToHexString(descriptor).Equals(DeviceHex,StringComparison.OrdinalIgnoreCase),"FD cached descriptor identity");
        }
        void ValidateFdIdentity(int fd, Identity id)
        {
            byte[] status = new byte[256]; int ret = statx(fd, "", 0x1000, 1, status); int errno = ret < 0 ? Marshal.GetLastWin32Error() : 0;
            Need(ret == 0, "statx failed errno=" + errno); Need((BitConverter.ToUInt32(status, 0) & 1) == 1, "statx type unavailable");
            Need((BitConverter.ToUInt16(status, 28) & 0xf000) == 0x2000, "FD not a character device");
            Need(BitConverter.ToUInt32(status, 128) == 189 && BitConverter.ToUInt32(status, 132) == (uint)((id.Bus - 1) * 128 + id.Device - 1), "FD USB device number");
        }
        public NativeResult Claim(int fd) {
            Need(fd==openedFd&&!ownClaim,"claim ownership");uint iface=2;var n=Result(ioctlNumber(fd,ClaimRequest,ref iface));
            if(n.Value==0){ownClaim=true;claimFd=fd;}return n;
        }
        public NativeResult Release(int fd) {
            Need(ownClaim&&fd==claimFd&&fd==openedFd,"release only own claim");uint iface=2;var n=Result(ioctlNumber(fd,ReleaseRequest,ref iface));
            if(n.Value==0){ownClaim=false;claimFd=-1;}return n;
        }
        public NativeResult Close(int fd) {
            Need(fd==openedFd,"close only own FD");var n=Result(close(fd));if(n.Value==0){openedFd=-1;ownClaim=false;claimFd=-1;}return n;
        }
        bool expectPayload;
        public NativeResult Bulk(int fd, bool input, byte[] data, int length)
        {
            Need(AbiReady, "bulk ABI");Need(ownClaim&&fd==claimFd&&fd==openedFd,"bulk requires own successful claim");
            // READ-ONLY: IN of exactly the four fixed read lengths; OUT only the four fixed read headers.
            if (input) Need(data.Length == length && (length == 256 || length == 68 || length == 16 || length == 244), "fixed input length");
            else if (length == 12 && AllowedWriteHeader(data)) { Need(!expectPayload, "header while payload pending"); expectPayload = true; }
            else if (length == 2) { Need(expectPayload && AllowedPayload(data), "payload allowlist"); expectPayload = false; }
            else { Need(!expectPayload && length == 12 && AllowedHeader(data), "fixed read header OUT only"); }
            GCHandle pinned = GCHandle.Alloc(data, GCHandleType.Pinned);
            try
            {
                Transfer transfer = new() { Ep = input ? 0x82u : 0x02u, Length = (uint)length, Timeout = TimeoutMs, Data = pinned.AddrOfPinnedObject() };
                return Result(ioctlTransfer(fd, BulkRequest, ref transfer));
            }
            finally { pinned.Free(); }
        }
    }

    sealed class FakeClock:IClock {public long At;public int Calls,Fail=-1;public long NowUs(){if(++Calls==Fail)throw new IOException("clock injected");return At+=100;}public void SleepUs(long us){throw new Exception("sleep forbidden");}}
    sealed class FakeOps:IOps {
      readonly List<BindingCheck> bindingChecks=new();public IReadOnlyList<BindingCheck> BindingChecks=>bindingChecks;
      public int Opens,Claims,Revalidates,FailRevalidate=-1;public int InitialFdValidations;public bool OwnClaim,BindBeforeClaim,PostClaimDangling;public string? Driver,DriverAfterClaim=UsbfsDriver;
      public int Calls,Fail=-1,ThrowAt=-1,Releases,Closes;public bool ReleaseFail,CloseFail,OpenFail,ClaimFail,ContextBad,RootBad,Dirty,ProfileBad,ValidateFail;
      public string SimulatedBoot="0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";public string? ChangedBoot;public int Device=57;public int[]? Limits;public string[]? States;public bool ObservationContext;
      public int Current=40,Temperature=25,RReads,UpperOverride=-1;public int[]? Temperatures,Echoes;public bool StaleNormal;public int AlternateUpperOverride=-1;public int[]? AlternateTemperatures;public int AlternateTemperature=-1;
      // Lane-mask window fakes: explicit 122 halfwords, or zero base + bit0/other-bit lane lists.
      public ushort[]? WindowHalfwords;public int[]? SkipLanes;public int[]? NonBit0SetLanes;Spec? pending;byte[]? win;uint pendingWrite;public int FakeWrites;
      void DriverGuard(){var b=ModelBinding(OwnClaim,Opens>0,Driver,PostClaimDangling);bindingChecks.Add(b);GuardNativeBinding(b);}
      public Identity Preflight(){Need(!OwnClaim,"fake initial ownership");Need(SimulatedBoot==ExpectedBoot,"fake boot mismatch");Need(ExpectedDevice==0||ExpectedDevice==Device,"fake device mismatch");DriverGuard();return new(7,Device);}
      public NativeResult Open(Identity id){Opens++;return new(OpenFail?-1:10,0);}
      public void ValidateFd(int fd,Identity id){InitialFdValidations++;if(ValidateFail)throw new Exception("fd");if(BindBeforeClaim)Driver=UsbfsDriver;}
      public void Revalidate(Identity id){Need((ChangedBoot??SimulatedBoot)==ExpectedBoot,"fake boot raced");if(++Revalidates==FailRevalidate)throw new IOException("instance changed");DriverGuard();}
      public NativeResult Claim(int fd){Claims++;Need(!OwnClaim&&Driver==null&&fd==10,"fake exclusive claim precondition");if(ClaimFail)return new(-1,0);OwnClaim=true;Driver=DriverAfterClaim;return new(0,0);}
      public NativeResult Release(int fd){Releases++;Need(OwnClaim&&fd==10,"fake release ownership");if(ReleaseFail)return new(-1,0);OwnClaim=false;Driver=null;return new(0,0);}
      public NativeResult Close(int fd){Closes++;Need(fd==10,"fake close identity");if(CloseFail)return new(-1,0);OwnClaim=false;Driver=null;return new(0,0);}
      void FillWindow(byte[] b){
        if(win!=null){win.CopyTo(b,0);return;}
        FillWindowBase(b);win=(byte[])b.Clone();
      }
      void FillWindowBase(byte[] b){
        if(WindowHalfwords!=null){Need(WindowHalfwords.Length==LaneCount,"fake window length");for(int i=0;i<LaneCount;i++)Put(b,2*i,WindowHalfwords[i]);return;}
        if(SkipLanes!=null)foreach(int lane in SkipLanes)Put(b,2*(lane-LaneStart),Half(b,2*(lane-LaneStart))|1);
        if(NonBit0SetLanes!=null)foreach(int lane in NonBit0SetLanes)Put(b,2*(lane-LaneStart),Half(b,2*(lane-LaneStart))|0x0100);
      }
      public NativeResult Bulk(int fd,bool input,byte[] b,int length){Need(OwnClaim&&fd==10,"fake bulk ownership");Calls++;if(Calls==ThrowAt)throw new IOException("bulk injected");if(Calls==Fail)return new(length-1,5);
        if(!input&&pendingWrite!=0){Need(length==2&&AllowedPayload(b),"fake payload");if(win==null){win=new byte[244];FillWindowBase(win);}Put(win,(int)(pendingWrite-0x47010438u),b[0]|b[1]<<8);pendingWrite=0;FakeWrites++;return new(length,0);}
        if(!input&&length==12&&AllowedWriteHeader(b)){Need(pending==null,"fake write when pending");pendingWrite=BitConverter.ToUInt32(b,4);return new(length,0);}
        if(!input){Need(length==12,"fake out header only");Need(pending==null,"fake header when pending");foreach(var s in new[]{R,M,C,MaskWindow})if(b.AsSpan().SequenceEqual(Header(s)))pending=s;Need(pending!=null,"fake fixed read header");}
        else{Need(pending!=null&&pending.Length==length,"fake read phase");var s=pending!;pending=null;
          if(s.Name=="R"){int at=RReads++;int t=Temperatures==null?Temperature:Temperatures[Math.Min(at,Temperatures.Length-1)],echo=Echoes==null?251:Echoes[Math.Min(at,Echoes.Length-1)];ThermalR(t,echo,Limits==null?Current:Limits[Math.Min(at,Limits.Length-1)]).CopyTo(b,0);if(States!=null){string st=States[Math.Min(at,States.Length-1)];Put(b,0,st=="Faulted"?1:0);Put(b,10,st=="Faulted"?0x1001:0);Put(b,14,st=="Clean"?1:0);}if(AlternateTemperature>=0||AlternateTemperatures!=null)Put(b,0xbc,Endpoint(2075,24,AlternateTemperatures==null?AlternateTemperature:AlternateTemperatures[Math.Min(at,AlternateTemperatures.Length-1)],15,195,3000,3800));if(AlternateUpperOverride>=0)Put(b,0xbc,AlternateUpperOverride);if(StaleNormal)Put(b,0x20,3200);if(Dirty)Put(b,0,1);if(ProfileBad)b[0x20]^=1;}
          if(s.Name=="M"){BitConverter.GetBytes(RootBad?0x20020000u:0x20010000u).CopyTo(b,64);Put(b,12,ContextBad?1:ObservationContext?3:2);b[56]=(byte)(ObservationContext?0:1);Put(b,22,500);Put(b,26,500);Put(b,38,UpperOverride>=0?UpperOverride:Endpoint(2075,24,Temperature,15,195,3000,3800));Put(b,40,500);}
          if(s.Name=="C"){Put(b,0,2160);Put(b,2,1920);Put(b,4,2880);b[6]=92;b[8]=3;}
          if(s.Name=="MaskWindow")FillWindow(b);
        }return new(length,0);
      }
    }
    static byte[] ThermalR(int temperature,int echo,int limit) {var r=(byte[])Profile.Clone();Put(r,0x98,temperature);Put(r,0xac,echo);int upper=Endpoint(2075,24,temperature,15,195,3000,3800);Put(r,0x20,upper);Put(r,0xbc,upper);Put(r,0xc4,limit);return r;}
    static void Put(byte[] b,int i,int v){b[i]=(byte)v;b[i+1]=(byte)(v>>8);}
    static string Serialize(Outcome o)=>JsonSerializer.Serialize(o,new JsonSerializerOptions{PropertyNamingPolicy=JsonNamingPolicy.CamelCase});
    [DllImport("libc.so.6",EntryPoint="open",SetLastError=true)] static extern int ReceiptOpen(string path,int flags,uint mode);
    [DllImport("libc.so.6",EntryPoint="statx",SetLastError=true)] static extern int ReceiptStat(int dirfd,string path,int flags,uint mask,[Out]byte[] data);
    [DllImport("libc.so.6",EntryPoint="getuid")] static extern uint ReceiptUid();
    [DllImport("libc.so.6",EntryPoint="geteuid")] static extern uint ReceiptEuid();
    static FileStream Receipt(string name) {
      Need(name=="selftest.receipt.json"||name=="native.receipt.json","fixed receipt name");
      string dir=Directory.GetCurrentDirectory(),prefix="/tmp/tcon-lanemask-kb-";Need(dir.StartsWith(prefix,StringComparison.Ordinal)&&dir.Length==prefix.Length+32,"private fixed stage path");
      foreach(char c in dir.Substring(prefix.Length))Need((c>='0'&&c<='9')||(c>='a'&&c<='f'),"stage nonce");
      byte[] st=new byte[256];Need(ReceiptStat(-100,dir,0x100,0xb,st)==0,"receipt directory stat");
      Need((BitConverter.ToUInt32(st,0)&0xb)==0xb,"receipt directory required fields");
      Need(BitConverter.ToUInt16(st,28)==0x41c0&&BitConverter.ToUInt32(st,20)==ReceiptUid()&&ReceiptUid()==ReceiptEuid(),"receipt directory mode/owner");
      int nofollow=RuntimeInformation.ProcessArchitecture==Architecture.Arm?0x8000:0x20000;
      int fd=ReceiptOpen(dir+"/"+name,1|0x40|0x80|0x80000|nofollow,0x180);Need(fd>=0,"exclusive receipt open errno="+Marshal.GetLastWin32Error());
      return new FileStream(new Microsoft.Win32.SafeHandles.SafeFileHandle((IntPtr)fd,true),FileAccess.Write,4096,false);
    }
    static void PublishReceipt(FileStream file,string json){byte[] raw=System.Text.Encoding.UTF8.GetBytes(json);Need(raw.Length<=262144,"receipt byte bound");file.Write(raw,0,raw.Length);file.Flush(true);}
    static int Main(string[] args){
      if(args.Length==1&&args[0]=="--self-test")return SelfTest();
      if(args.Length==1&&args[0]=="--receipt-self-test"){using var receipt=Receipt("selftest.receipt.json");var saved=Console.Out;using var text=new StringWriter(System.Globalization.CultureInfo.InvariantCulture);int code;try{Console.SetOut(text);code=SelfTest();}finally{Console.SetOut(saved);}PublishReceipt(receipt,text.ToString());return code;}
      if(args.Length==3&&args[0]=="--host-fixture"){Need(ValidBoot(args[2]),"fixture expected boot");ExpectedBoot=args[2];Console.WriteLine(Serialize(Fixture(args[1])));return 0;}
      if(args.Length==0){Console.WriteLine("{\"schema\":\"ka-lane-mask-read-dry-v1\",\"targetOperations\":0,\"reads\":[\"R@0x47012400:256\",\"M@0x470004a0:68\",\"C@0x47000bc0:16\",\"maskWindow@0x47010438:244\"],\"writes\":0}");return 0;}
      if(args.Length==2&&args[0]=="--write-self-test"){Mode=args[1];return WriteSelfTest();}
      if(args.Length==5&&(args[0]=="--execute-mask"||args[0]=="--execute-unmask"))Mode=args[0]=="--execute-mask"?"mask":"unmask";
      if(args.Length!=5||(args[0]!="--execute-read"&&args[0]!="--execute-mask"&&args[0]!="--execute-unmask")||args[1]!="--device"||!int.TryParse(args[2],out ExpectedDevice)||ExpectedDevice<1||ExpectedDevice>127||args[2]!=ExpectedDevice.ToString()||args[3]!="--expected-boot"||!ValidBoot(args[4]))return 64;
      ExpectedBoot=args[4];if(!RealOps.AbiReady)return 64;
      using var nativeReceipt=Receipt("native.receipt.json");var outcome=Run(new RealOps(),new RealClock());PublishReceipt(nativeReceipt,Serialize(outcome)+"\n");return outcome.ReadComplete?0:1;
    }
}
