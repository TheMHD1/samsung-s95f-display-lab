using System;
using System.Linq;
using System.Text;
using System.Text.Json;
internal static partial class Program {
 const string OldBoot="0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",NewBoot="11111111-2222-4333-8444-555555555555";
 static Outcome Fixture(string kind){var f=new FakeOps{SimulatedBoot=ExpectedBoot,Device=ExpectedDevice==0?57:ExpectedDevice};
  switch(kind){
   case "steady40":break;
   case "steady200":f.Current=200;break;
   case "startup":f.Current=40;f.StaleNormal=true;break;              // post-MODE2-reset: ordinary 3200 not refreshed to model 3183
   case "fault40":f.Current=40;f.States=new[]{"Faulted"};f.ObservationContext=true;break;
   case "fault200":f.Current=200;f.States=new[]{"Faulted"};f.ObservationContext=true;break;
   case "quiescent40":f.Current=40;f.States=new[]{"Quiescent"};f.ObservationContext=true;break;
   case "quiescent200":f.Current=200;f.States=new[]{"Quiescent"};f.ObservationContext=true;break;
   case "skip3":f.SkipLanes=new[]{540,600,661};break;
   case "allskip":f.WindowHalfwords=Enumerable.Repeat((ushort)1,LaneCount).ToArray();break;
   case "nonbit0":f.SkipLanes=new[]{550};f.NonBit0SetLanes=new[]{550,661};break;
   default:throw new InvalidOperationException("fixed host kind");
  }
  return Run(f,new FakeClock());
 }
 static int SelfTest(){int checks=0,max=0;string saved=ExpectedBoot;int device=ExpectedDevice;ExpectedDevice=0;
  void Check(bool v,string s){Need(v,s);checks++;}
  Outcome Test(FakeOps f,FakeClock? c=null){var o=Run(f,c??new());Check(o.Steps.All(st=>st.Direction!="OUT"||st.Expected==12),"no non-header OUT ever");Check(f.Closes==(f.Opens==1&&!f.OpenFail?1:0),"exact close");Check(f.Releases==(f.Claims==1&&!f.ClaimFail?1:0),"exact release");max=Math.Max(max,Encoding.UTF8.GetByteCount(Serialize(o))+1);return o;}
  foreach(string boot in new[]{OldBoot,NewBoot}){ExpectedBoot=boot;
   // (1) read: steady Clean, limit reported, admitted, no skips
   foreach(int limit in new[]{40,200}){var f=new FakeOps{SimulatedBoot=boot,Current=limit};var o=Test(f);
    Check(o.ReadComplete&&o.ObservedState=="Clean"&&o.ObservedLimit==limit&&o.ExpectedBootId==boot,"read completes, limit+state reported");
    Check(o.HeadersSent==6&&o.BulkTransfers==12&&o.Windows.Count==6,"six read-only reads, zero writes");
    Check(o.IzThermalProfileAdmitted&&o.IzContextAdmitted&&o.OrdinaryMatchesModel&&!o.StartupProfileCandidate,"steady matches IZ admitted case");
    Check(o.SkippedCount==0&&o.SkippedLanes.Count==0&&o.NonBit0Lanes.Count==0&&o.LaneRangeStart==540&&o.LaneRangeEnd==661&&o.WindowBytes==244,"all-zero window: no lanes skipped");
    Check(o.RStable&&o.WindowStable,"re-read stable");}
  }
  ExpectedBoot=OldBoot;
  // (2) startup-profile admission: read still completes; IZ would REFUSE on ordinary endpoint
  {var f=new FakeOps{StaleNormal=true};var o=Test(f);
   Check(o.ReadComplete&&o.ObservedState=="Clean","startup profile: read-only still completes");
   Check(o.OrdinaryObserved==3200&&o.OrdinaryModel==3183&&!o.OrdinaryMatchesModel,"startup ordinary 3200 vs model 3183 captured");
   Check(!o.IzThermalProfileAdmitted&&o.IzAdmissionDetail.Contains("ordinary-current endpoint"),"IZ thermal/profile would refuse with exact reason");
   Check(o.AlternateObserved==3183&&o.AlternateAllowed&&o.StartupProfileCandidate,"flagged as startup-profile candidate");}
  // (3) fault-state behaviour: stable Fault is an admitted observation, read completes
  foreach(int limit in new[]{40,200}){var f=new FakeOps{Current=limit,States=new[]{"Faulted"},ObservationContext=true};var o=Test(f);
   Check(o.ReadComplete&&o.ObservedState=="Faulted"&&o.ObservedLimit==limit,"fault state read completes");
   Check(o.StateStop==1&&o.StateFault==0x1001&&o.StateGate==0,"fault tuple reported");
   Check(o.IzThermalProfileAdmitted&&o.IzContextAdmitted&&!o.StartupProfileCandidate,"stable fault admitted as observation");}
  // quiescent completes too
  {var f=new FakeOps{States=new[]{"Quiescent"},ObservationContext=true};var o=Test(f);Check(o.ReadComplete&&o.ObservedState=="Quiescent","quiescent read completes");}
  // (4) boot mismatch refusal: nothing opened, read not complete
  {ExpectedBoot=OldBoot;var f=new FakeOps{SimulatedBoot=NewBoot};var o=Test(f);Check(!o.ReadComplete&&f.Opens==0&&f.Calls==0&&o.Errors.Count>0,"boot mismatch refuses before any transfer");}
  foreach(string bad in new[]{"","0A1B2C3D-4E5F-4A6B-8C7D-9E0F1A2B3C4D","00000000-0000-0000-0000-000000000000","x;reboot"}){ExpectedBoot=bad;var f=new FakeOps();var o=Test(f);Check(!o.ReadComplete&&f.Opens==0&&f.Calls==0,"invalid boot UUID refuses before device");}
  ExpectedBoot=OldBoot;
  // (5) wrong device refusal
  {ExpectedDevice=78;var f=new FakeOps();var o=Test(f);Check(!o.ReadComplete&&f.Calls==0,"wrong expected device refuses");ExpectedDevice=0;}
  // (6) window: some lanes skipped, reported exactly
  {var f=new FakeOps{SkipLanes=new[]{540,600,661}};var o=Test(f);
   Check(o.ReadComplete&&o.SkippedCount==3&&o.SkippedLanes.SequenceEqual(new[]{540,600,661}),"specific skipped lanes reported");
   Check(o.NonBit0Lanes.Count==0,"skip-only has no other-bit notes");}
  // (7) window: all lanes already skipped
  {var f=new FakeOps{WindowHalfwords=Enumerable.Repeat((ushort)1,LaneCount).ToArray()};var o=Test(f);
   Check(o.ReadComplete&&o.SkippedCount==122&&o.SkippedLanes.First()==540&&o.SkippedLanes.Last()==661,"all 122 lanes skipped reported");}
  // (8) window: halfwords with bits other than bit0 are RECORDED (never refused)
  {var f=new FakeOps{SkipLanes=new[]{550},NonBit0SetLanes=new[]{550,661}};var o=Test(f);
   Check(o.ReadComplete,"non-bit0 content does not refuse a read");
   Check(o.SkippedLanes.SequenceEqual(new[]{550}),"lane 550 (0x0101) counts as skipped");
   Check(o.NonBit0Lanes.Select(n=>n.Lane).SequenceEqual(new[]{550,661}),"both other-bit lanes recorded");
   Check(o.NonBit0Lanes[0].Halfword==0x0101&&o.NonBit0Lanes[0].BusAddress==0x47010438+2*(550-540),"recorded halfword value and bus address");}
  // transport integrity: any short/thrown transfer stops immediately, no retry, read not complete
  foreach(bool thrown in new[]{false,true})for(int cut=1;cut<=12;cut++){var f=new FakeOps{Fail=thrown?-1:cut,ThrowAt=thrown?cut:-1};var o=Test(f);Check(!o.ReadComplete&&f.Calls==cut&&o.ProtocolPhase=="Unknown","bad transfer absolute stop");}
  for(int i=1;i<=40;i++){var f=new FakeOps();var o=Test(f,new FakeClock{Fail=i});Check(!o.ReadComplete||o.Errors.Count==0,"clock failure never silently completes");}
  // binding / transport / identity failures cannot complete a read (these DO protect read integrity)
  foreach(var f in new[]{new FakeOps{OpenFail=true},new FakeOps{ClaimFail=true},new FakeOps{ValidateFail=true},new FakeOps{Driver=UsbfsDriver},new FakeOps{BindBeforeClaim=true},new FakeOps{DriverAfterClaim=null},new FakeOps{PostClaimDangling=true},new FakeOps{ChangedBoot=NewBoot}}){var o=Test(f);Check(!o.ReadComplete,"binding/transport/identity failure cannot complete");}
  // unadmitted R STATE (not Clean/Quiescent/Faulted) refuses cleanly (RtState throws, caught)
  {var f=new FakeOps{Dirty=true};var o=Test(f);Check(!o.ReadComplete&&o.Errors.Count>0,"unadmitted R state refused cleanly");}
  // bad M context (content, not binding) does NOT gate a read-only report; it completes and reports not-admitted
  foreach(var f in new[]{new FakeOps{ContextBad=true},new FakeOps{RootBad=true}}){var o=Test(f);Check(o.ReadComplete&&!o.IzContextAdmitted,"bad context is reported, not refused, in read-only");}
  // release/close failure cannot report completion
  foreach(var f in new[]{new FakeOps{ReleaseFail=true},new FakeOps{CloseFail=true}}){var o=Test(f);Check(!o.ReadComplete,"release/close failure not complete");}
  // R profile matrix unchanged vs IZ definition
  for(int i=0;i<256;i++){var a=(byte[])Profile.Clone();a[i]^=0x80;bool pass=true;try{GuardR(a,40);}catch{pass=false;}Check(pass==(DynamicR(i)||i==0xac),"unchanged profile matrix");}
  Check(Header(MaskWindow).AsSpan().SequenceEqual(Convert.FromHexString("0101000038040147f4000000")),"mask-window read header = 0x101 / bus 0x47010438 / len 244");
  Check(MaskWindow.Address==0x47010438&&MaskWindow.Length==244&&R.Address==0x47012400&&R.Length==256&&M.Address==0x470004a0&&C.Address==0x47000bc0,"fixed read addresses/lengths");
  Check(max<24576,"serialized cap");ExpectedBoot=saved;ExpectedDevice=device;Console.WriteLine(JsonSerializer.Serialize(new{selfTestsPassed=checks,maxSerializedBytes=max,targetOperations=0,writes=0}));return 0;
 }
}
