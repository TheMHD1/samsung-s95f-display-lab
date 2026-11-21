using System;
using System.Linq;
internal static partial class Program {
 // Host-only checks for the separately named AC1 first-scan policy.  These tests
 // never construct RealOps and therefore cannot contact a USB device.
 static int StartupMaskSelfTest(){
  string savedBoot=ExpectedBoot,savedMode=Mode;int savedDevice=ExpectedDevice,checks=0;ExpectedBoot=OldBoot;ExpectedDevice=0;Mode="startup-mask";
  void Check(bool value,string name){Need(value,name);checks++;}
  Outcome T(FakeOps f){Mode="startup-mask";var o=Run(f,new FakeClock());Check(f.Closes==1&&f.Releases==1,"release and close: "+name(f));return o;}
  string name(FakeOps f)=>"startup fake";
  void Refuses(FakeOps f,string reason){var o=T(f);Check(!o.ReadComplete&&!o.WriteVerified&&o.WritesDone==0&&f.FakeWrites==0&&!o.WriteAttempted,reason);}

  // AC1 is a separate lifecycle category.  AC2 is intentionally not admitted
  // before a write; it is accepted only after a successful transaction as the
  // firmware's documented first-scan completion transition.
  {var f=new FakeOps{Current=40,StaleNormal=true,Acs=new[]{1,1,2}};var o=T(f);
   Check(o.ReadComplete&&o.WriteVerified&&o.Schema=="s95f-lane-mask-startup-ac1-v1"&&o.AdmissionPolicy=="first-scan-clean40-v1","AC1 receipt policy");
   Check(o.WritesPlanned==122&&o.WritesDone==122&&f.FakeWrites==122&&o.AfterSkippedLanes.Count==122,"exact 122 primary bit0 writes");
   Check(o.PreAa==0&&o.PreAc==1&&o.AfterAa==0&&o.AfterAc==2&&o.AfterScan==1&&o.ContextStable,"AC1/AC2 context recorded and stable");
   Check(o.AfterState=="Clean"&&o.AfterLimit==40&&f.Revalidates==3,"post Clean/40 and fresh revalidation");}
  Refuses(new FakeOps{Current=40,StaleNormal=true,Acs=new[]{2}},"AC other refuses before write");
  Refuses(new FakeOps{Current=40,StaleNormal=true,Aas=new[]{1},Acs=new[]{1}},"AA1 refuses before write");
  Refuses(new FakeOps{Current=40,StaleNormal=true,Acs=new[]{1},Scans=new[]{0}},"scan0 refuses before write");
  Refuses(new FakeOps{Current=200,StaleNormal=true,Acs=new[]{1}},"limit200 refuses before write");
  Refuses(new FakeOps{Current=40,StaleNormal=true,Acs=new[]{1},States=new[]{"Faulted"}},"Faulted refuses before write");
  Refuses(new FakeOps{Current=40,StaleNormal=true,Acs=new[]{1,2}},"changed M refuses before write");
  Refuses(new FakeOps{Current=40,StaleNormal=true,Acs=new[]{1},M22s=new[]{500,499}},"changed M numeric refuses before write");
  {var f=new FakeOps{Current=40,StaleNormal=true,Acs=new[]{1,1,2},Ticks=new[]{49,50,51}};var o=T(f);
   Check(o.ReadComplete&&o.WriteVerified&&o.ContextStable&&o.WritesDone==122,"v2: ticking scan counters (M18,M20-21,M48-50) still admit");}
  Refuses(new FakeOps{Current=40,StaleNormal=true,Acs=new[]{1},Ticks=new[]{49,50},M30s=new[]{0,1}},"v2: any other changed M byte still refuses");
  Refuses(new FakeOps{Current=40,StaleNormal=true,Acs=new[]{1},CContexts=new[]{3,2}},"changed C refuses before write");
  Refuses(new FakeOps{Current=40,StaleNormal=true,Acs=new[]{1},Temperatures=new[]{25,26}},"changed R refuses before write");
  var changed=new ushort[LaneCount];changed[0]=1;
  Refuses(new FakeOps{Current=40,StaleNormal=true,Acs=new[]{1},WindowSnapshots=new[]{new ushort[LaneCount],changed}},"changed window refuses before write");
  Refuses(new FakeOps{Current=40,StaleNormal=true,Acs=new[]{1},NonBit0SetLanes=new[]{540}},"nonbit0 refuses startup-only");
  Refuses(new FakeOps{Current=40,StaleNormal=true,Acs=new[]{1},SkipLanes=new[]{540}},"already masked/partial refuses startup-only");
  {var f=new FakeOps{Current=40,StaleNormal=true,Acs=new[]{1},Fail=20};var o=T(f);
   Check(!o.ReadComplete&&!o.WriteVerified&&o.Errors.Count>0&&f.FakeWrites<122&&f.Calls==20,"mid-write failure stops without retry");}
  ExpectedBoot=savedBoot;ExpectedDevice=savedDevice;Mode=savedMode;
  Console.WriteLine("{\"startupMaskSelfTestsPassed\":"+checks+",\"mode\":\"startup-mask\",\"targetOperations\":0}");return 0;
 }
}
