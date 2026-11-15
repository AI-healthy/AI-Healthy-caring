"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const base = "/api/v1";
  let token = "", deviceToken = "", deviceId = "", run = null, session = null;
  let busy = false, rated = false, logLines = [];
  const key = () => crypto.randomUUID();
  const put = (id, data) => { $(id).textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2); };
  function log(text) { logLines.unshift(text); logLines = logLines.slice(0, 30); put("logs", logLines.join("\n")); }
  async function api(path, method="GET", body=null, mode="user") {
    const headers = {};
    const credential = mode === "device" ? deviceToken : mode === "user" ? token : "";
    if (credential) headers.Authorization = "Bearer " + credential;
    if (body !== null) headers["Content-Type"] = "application/json";
    let response;
    try {
      response = await fetch(base + path, {
        method, headers, cache:"no-store", credentials:"omit",
        ...(body !== null ? {body:JSON.stringify(body)} : {})
      });
    } catch (_) { throw new Error("网络不可用"); }
    log(method + " " + path + " → " + response.status);
    if (!response.ok) throw new Error("请求失败（HTTP " + response.status + "）");
    return response.status === 204 ? null : response.json();
  }
  function controls() {
    const logged = Boolean(token), awaiting = run?.status === "AWAITING_CONFIRMATION";
    const active = ["CREATED","RUNNING"].includes(session?.status);
    document.querySelectorAll("[data-login]").forEach(el => el.disabled = busy || !logged);
    $("init").disabled = busy || logged;
    $("plan").disabled = busy || !logged || active || awaiting;
    $("dismiss").disabled = busy || !logged || !awaiting;
    $("start").disabled = busy || !logged || session?.status !== "CREATED";
    $("robot").disabled = busy || !logged || session?.status !== "RUNNING" || !deviceToken;
    $("complete").disabled = busy || !logged || session?.status !== "RUNNING";
    $("cancel").disabled = busy || !logged || !active;
    $("feedback").disabled = busy || !logged || session?.status !== "COMPLETED" || rated;
    $("schedule").disabled = busy || !logged || active || !deviceToken;
    $("options").querySelectorAll("button").forEach(el => el.disabled = busy || !logged || !awaiting || active);
  }
  function action(fn) { return async () => {
    if (busy) return;
    busy = true; controls(); put("notice", "正在处理…"); $("notice").className = "";
    try { await fn(); put("notice", "操作成功"); }
    catch (e) { put("notice", e instanceof Error ? e.message : "操作失败"); $("notice").className="error"; }
    finally { busy = false; controls(); }
  }; }
  function showRun(data) {
    run = data; $("options").replaceChildren();
    put("trace", data ? {status:data.status, algorithm:data.algorithm, reason:data.reason, trace:data.trace} : "等待方案");
    if (data?.status !== "AWAITING_CONFIRMATION") return;
    for (const option of data.options) {
      const item = document.createElement("div"); item.className="option";
      const label = document.createElement("span"); label.textContent=option.title + " · " + option.duration_minutes + " min";
      const btn=document.createElement("button"); btn.textContent="选择";
      btn.addEventListener("click",action(async()=>{
        const confirmed=await api("/harness/runs/"+run.run_id+"/confirm","POST",{activity_id:option.activity_id});
        showRun(confirmed.run); showSession(confirmed.session); rated=false;
      }));
      item.append(label,btn); $("options").append(item);
    }
  }
  function showSession(data) { session=data; put("session",data?data.title+" / "+data.status:"无活动"); }
  async function refreshMemory() { put("memoryOut",await api("/harness/memory")); }
  async function refreshRun() {
    if (run) showRun(await api("/harness/runs/"+run.run_id));
  }
  async function settingsPatch(patch) {
    const settings=await api("/harness/settings");
    return api("/harness/settings","PUT",{...settings,...patch});
  }
  const on = (id, fn) => $(id).addEventListener("click",action(fn));
  on("init",async()=>{
    const credentials={username:"demo_"+key().replaceAll("-","").slice(0,20),password:key()+key()};
    await api("/users/register","POST",credentials,"none");
    const login=await api("/users/login","POST",credentials,"none");
    token=login.access_token;
    put("account",login.user.username+" · 合成账号");
    const device=await api("/users/me/simulated-devices","POST",{name:"Workbench simulator"});
    deviceId=device.device.device_id; deviceToken=device.device_token;
    put("deviceOut","模拟设备已绑定；凭证仅在本页内存。");
    await refreshMemory();
  });
  on("logout",async()=>{
    await api("/proactive/schedule","PUT",{enabled:false});
    if (deviceId) await api("/users/me/simulated-devices/"+deviceId,"DELETE");
    await api("/users/logout","POST"); token=deviceToken=deviceId="";
    showRun(null); showSession(null); rated=false; put("account","已退出");
    put("memoryOut","尚无记忆查询"); put("deviceOut","尚无模拟命令"); put("offerOut","无邀请");
    $("preference").value=""; $("feedbackMemory").checked=false; $("behaviorMemory").checked=false;
  });
  on("save",async()=>{
    await settingsPatch({preference_tags:$("preference").value?[$("preference").value]:[],
      use_feedback_memory:$("feedbackMemory").checked,use_behavior_memory:$("behaviorMemory").checked});
    await refreshRun(); await refreshMemory();
  });
  on("memory",refreshMemory);
  on("reset",async()=>{put("memoryOut",await api("/harness/memory/reset","POST"));await refreshRun();});
  on("plan",async()=>{
    const minutes=Number($("minutes").value), energy=$("energy").value;
    if (!Number.isInteger(minutes)||minutes<1||minutes>30) throw new Error("请输入1–30分钟的整数");
    showRun(await api("/harness/runs","POST",{client_request_id:key(),available_minutes:minutes,
      ...(energy?{energy_level:Number(energy)}:{})}));
  });
  on("dismiss",async()=>showRun(await api("/harness/runs/"+run.run_id+"/dismiss","POST")));
  for (const [id,verb] of [["start","start"],["complete","complete"],["cancel","cancel"]]) {
    on(id,async()=>showSession(await api("/activities/sessions/"+session.session_id+"/"+verb,"POST")));
  }
  on("robot",async()=>{
    const command=await api("/devices/commands","POST",{session_id:session.session_id,
      device_id:deviceId,preset:"happy",client_request_id:key()});
    const path="/devices/"+deviceId;
    const pending=await api(path+"/pending","GET",null,"device");
    if (!pending || pending.command_id!==command.command_id) throw new Error("模拟队列当前没有对应命令");
    for (const type of ["COMMAND_ACKNOWLEDGED","COMMAND_COMPLETED"]) {
      await api(path+"/events","POST",{schema_version:pending.schema_version,event_id:key(),
        device_id:deviceId,type,command_id:pending.command_id,occurred_at:new Date().toISOString(),
        is_demo:true},"device");
    }
    put("deviceOut",await api("/devices/commands/"+command.command_id));
  });
  on("feedback",async()=>{
    await api("/activities/feedback","POST",{session_id:session.session_id,activity_id:session.activity_id,
      completed:true,enjoyment:Number($("rating").value),client_event_id:"workbench:"+session.session_id});
    rated=true; await refreshMemory();
  });
  on("schedule",async()=>{
    await settingsPatch({proactive_enabled:true});
    await refreshRun();
    put("offerOut",await api("/proactive/schedule","PUT",{enabled:true,available_minutes:5,
      available_for_minutes:30,channel:"simulator",device_id:deviceId}));
  });
  on("pause",async()=>{
    put("offerOut",await api("/proactive/schedule","PUT",{enabled:false})); await refreshRun();
  });
  on("poll",async()=>{
    const offer=await api("/proactive/offers/pending");
    if (!offer) { put("offerOut",await api("/proactive/schedule")); return; }
    const path="/proactive/devices/"+deviceId;
    const pending=await api(path+"/pending","GET",null,"device");
    if (pending) await api(path+"/offers/"+pending.offer_id+"/ack","POST",null,"device");
    put("offerOut",{offer_id:offer.offer_id,message:"模拟邀请：要不要试试时宜的小活动？",device_receipt:Boolean(pending||offer.acknowledged_at)});
    showRun(offer.run);
  });
  controls();
})();
