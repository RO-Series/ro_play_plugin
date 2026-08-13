const bridge = window.AstrBotPluginPage;

async function main() {
  await bridge.ready();
  const conf = await bridge.apiGet("broadcast");
  document.getElementById("enabled").checked = !!conf.enabled;
  document.getElementById("mode").value = conf.mode || "interval";
  document.getElementById("intervalSec").value = conf.intervalSec || 3600;
  document.getElementById("atAll").checked = !!conf.atAll;
  document.getElementById("content").value = conf.content || "";
  document.getElementById("targets").value = (conf.targets || []).join("\n");

  document.getElementById("save").addEventListener("click", async () => {
    const body = {
      enabled: document.getElementById("enabled").checked,
      mode: document.getElementById("mode").value,
      intervalSec: parseInt(document.getElementById("intervalSec").value, 10) || 3600,
      atAll: document.getElementById("atAll").checked,
      content: document.getElementById("content").value,
      targets: document.getElementById("targets").value.split("\n").map((s) => s.trim()).filter(Boolean),
    };
    const res = await bridge.apiPost("broadcast", body);
    document.getElementById("msg").textContent = res.ok ? "定时广播配置已保存" : "保存失败: " + (res.error || "");
  });

  document.getElementById("send").addEventListener("click", async () => {
    const targets = document.getElementById("targets").value.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!targets.length) { document.getElementById("msg").textContent = "请先填写目标群号"; return; }
    const res = await bridge.apiPost("broadcast/send", {
      targets,
      content: document.getElementById("content").value,
    });
    document.getElementById("msg").textContent = res.ok ? `已向 ${res.sent || 0} 个群发送` : "发送失败: " + (res.error || "");
  });
}

main().catch((e) => {
  document.getElementById("msg").textContent = "初始化失败: " + e;
});
