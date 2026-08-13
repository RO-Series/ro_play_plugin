const bridge = window.AstrBotPluginPage;

async function main() {
  await bridge.ready();
  const data = await bridge.apiGet("auto-like");
  document.getElementById("enabled").checked = !!data.enabled;
  document.getElementById("mode").value = data.mode || "all";
  document.getElementById("times").value = 20;
  document.getElementById("users").value = (data.users || []).join("\n");

  document.getElementById("save").addEventListener("click", async () => {
    const body = {
      enabled: document.getElementById("enabled").checked,
      mode: document.getElementById("mode").value,
      users: document.getElementById("users").value.split("\n").map((s) => s.trim()).filter(Boolean),
    };
    const res = await bridge.apiPost("auto-like", body);
    document.getElementById("msg").textContent = res.ok ? "已保存" : "保存失败: " + (res.error || "");
  });
}

main().catch((e) => {
  document.getElementById("msg").textContent = "初始化失败: " + e;
});
