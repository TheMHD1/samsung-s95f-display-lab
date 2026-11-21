using System;
using System.Linq;
internal static partial class Program {
 // Host-only FakeOps tests of the KB write path. Mode is set by the caller (mask|unmask).
 static int WriteSelfTest(){
  Need(Mode=="mask"||Mode=="unmask","write self-test mode");string mode=Mode;int checks=0;
  void Check(bool v,string s){Need(v,s);checks++;}
  ExpectedBoot=OldBoot;ExpectedDevice=0;
  Outcome T(FakeOps f,FakeClock? c=null){Mode=mode;var o=Run(f,c??new FakeClock());
   int outs=o.Steps.Where(s=>s.Direction=="OUT"&&s.Expected==2).Count();Check(outs==o.WritesDone||(outs==o.WritesDone+1&&o.Errors.Count>0),"every 2-byte OUT is a counted write: outs="+outs+" done="+o.WritesDone+" err="+string.Join(";",o.Errors));
   Check(f.Closes==1&&f.Releases==1,"released and closed");return o;}
  if(mode=="mask"){
   foreach(int limit in new[]{40,200}){var f=new FakeOps{Current=limit};var o=T(f);
    Check(o.ReadComplete&&o.WriteVerified&&o.WritesPlanned==122&&o.WritesDone==122&&f.FakeWrites==122,"mask from zero writes 122 and verifies");
    Check(o.AfterSkippedLanes.Count==122&&o.AfterSkippedLanes.First()==540&&o.AfterSkippedLanes.Last()==661&&o.AfterLimit==limit&&o.AfterState=="Clean","all 122 lanes skipped, limit unchanged");}
   {var f=new FakeOps{SkipLanes=new[]{540,600}};var o=T(f);Check(o.WriteVerified&&o.WritesDone==120,"partial pre-mask: only missing lanes written");}
   {var f=new FakeOps{WindowHalfwords=Enumerable.Repeat((ushort)1,LaneCount).ToArray()};var o=T(f);Check(o.ReadComplete&&o.WriteVerified&&o.WritesDone==0,"already masked: verified no-op");}
  } else {
   {var f=new FakeOps{WindowHalfwords=Enumerable.Repeat((ushort)1,LaneCount).ToArray()};var o=T(f);Check(o.ReadComplete&&o.WriteVerified&&o.WritesDone==122&&o.AfterSkippedLanes.Count==0,"unmask clears all 122");}
   {var f=new FakeOps();var o=T(f);Check(o.ReadComplete&&o.WriteVerified&&o.WritesDone==0,"already unmasked: no-op");}
  }
  // startup profile (ordinary 3200 before firmware recompute) is admitted for mask writes only
  if(mode=="mask"){var f=new FakeOps{StaleNormal=true};var o=T(f);Check(o.ReadComplete&&o.WriteVerified&&o.StartupProfileWrite&&o.WritesDone==122,"startup-profile mask write admitted");}
  {var f=new FakeOps();var o=T(f);if(mode=="mask")Check(!o.StartupProfileWrite,"steady profile not flagged as startup");}
  // refusals: no writes at all
  foreach(var f in new[]{new FakeOps{States=new[]{"Faulted"},ObservationContext=true},new FakeOps{States=new[]{"Quiescent"},ObservationContext=true},new FakeOps{ContextBad=true},new FakeOps{NonBit0SetLanes=new[]{560}},new FakeOps{Current=100}}){
   var o=T(f);Check(!o.ReadComplete&&o.WritesDone==0&&f.FakeWrites==0&&!o.WriteAttempted,"guard refusal before any write: "+string.Join(";",o.Errors));}
  // injected transfer failure mid-write: stops, no retry, reports
  {var f=new FakeOps{Fail=20};if(mode=="unmask")f.WindowHalfwords=Enumerable.Repeat((ushort)1,LaneCount).ToArray();var o=T(f);Check(!o.ReadComplete&&!o.WriteVerified&&o.Errors.Count>0&&f.FakeWrites<122,"mid-write failure stops without retry");}
  // boot mismatch: nothing opened
  {ExpectedBoot=NewBoot;var f=new FakeOps();Mode=mode;var o=Run(f,new FakeClock());Check(!o.ReadComplete&&f.Opens==0&&f.FakeWrites==0,"boot mismatch refuses");ExpectedBoot=OldBoot;}
  Console.WriteLine("{\"writeSelfTestsPassed\":"+checks+",\"mode\":\""+mode+"\"}");return 0;
 }
}
